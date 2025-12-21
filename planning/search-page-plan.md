# Unified Search Page - Implementation Plan

## 1. Executive Summary

### Purpose
Create a comprehensive Search page that allows users to search across all data stored in the application in a unified interface. Users can search files, analysis results (Rekognition + Nova), transcripts, and face collections from a single location with advanced filtering and result categorization.

### Key Benefits
- **Unified Access**: Single entry point to search all application data
- **Time Savings**: Find relevant information across multiple data types without navigating multiple pages
- **Discovery**: Enable users to discover relationships between files, analysis results, and transcripts
- **Power User Workflow**: Advanced filters and search operators for complex queries
- **Performance**: Optimized queries delivering results in <500ms for 10,000+ records

---

## 2. Data Analysis

### Complete Data Inventory

Based on codebase analysis, the following data types are searchable:

#### A. Files Table
**Location**: `files` table in SQLite
**Searchable Fields**:
- `filename` (TEXT) - File name
- `s3_key` (TEXT) - S3 object key
- `file_type` (TEXT) - 'video' or 'image'
- `content_type` (TEXT) - MIME type
- `metadata` (JSON) - Custom metadata
- `local_path` (TEXT) - Local file path
- `codec_video` (TEXT) - Video codec
- `codec_audio` (TEXT) - Audio codec
- `uploaded_at` (TIMESTAMP) - Upload date
- `size_bytes` (INTEGER) - File size
- `duration_seconds` (REAL) - Video duration
- `resolution_width`, `resolution_height` (INTEGER) - Video resolution

**Total Records**: ~3,161+ files (per CLAUDE.md)

#### B. Analysis Jobs Table
**Location**: `analysis_jobs` table
**Searchable Fields**:
- `job_id` (TEXT) - Unique job identifier
- `analysis_type` (TEXT) - Type of analysis (8 video + 8 image types)
- `status` (TEXT) - SUBMITTED, IN_PROGRESS, SUCCEEDED, FAILED
- `parameters` (JSON) - Analysis parameters
- `results` (JSON) - **Rich searchable content** containing:
  - Label detection: label names, categories, confidence scores
  - Face detection: emotions, age ranges, gender
  - Celebrity recognition: celebrity names
  - Text detection: detected text (OCR)
  - Content moderation: flagged content
  - Person tracking: person indices
  - Segment detection: scene/shot types
- `started_at`, `completed_at` (TIMESTAMP) - Job timestamps
- `error_message` (TEXT) - Error details

**Analysis Types**:
- **Video**: label_detection, face_detection, celebrity_recognition, content_moderation, text_detection, person_tracking, face_search, shot_segmentation
- **Image**: label_detection, face_detection, celebrity_recognition, content_moderation, text_detection, ppe_detection, face_search, face_comparison

#### C. Nova Jobs Table
**Location**: `nova_jobs` table
**Schema** (from documentation):
- `id` (INTEGER PRIMARY KEY)
- `analysis_job_id` (INTEGER FK to analysis_jobs.id)
- `model` (TEXT) - Nova model (micro, lite, pro, premier)
- `analysis_types` (JSON) - ['summary', 'chapters', 'elements']
- `user_options` (JSON) - Processing options
- `status` (TEXT) - Job status
- `summary_result` (JSON) - **Video summary text**
- `chapters_result` (JSON) - **Chapter titles, summaries, timestamps**
- `elements_result` (JSON) - **Detected elements (equipment, topics, people)**
- `started_at`, `completed_at` (TIMESTAMP)
- `progress_percent` (INTEGER)
- `current_chunk`, `total_chunks` (INTEGER) - For chunked processing
- `estimated_cost`, `actual_cost` (REAL) - Cost tracking
- `input_tokens`, `output_tokens` (INTEGER) - Token usage
- `processing_time` (REAL) - Processing duration

**Searchable Content**:
- Summary text (rich AI-generated descriptions)
- Chapter titles and summaries
- Element names (equipment, topics, people)

#### D. Transcripts Table
**Location**: `transcripts` table
**Searchable Fields**:
- `file_path` (TEXT) - Source file path
- `file_name` (TEXT) - Source filename
- `model_name` (TEXT) - Whisper model or nova-2-sonic
- `language` (TEXT) - Detected/specified language
- `transcript_text` (TEXT) - **Full transcript text** (primary search target)
- `segments` (TEXT/JSON) - Timestamped segments with text
- `word_timestamps` (TEXT/JSON) - Word-level timing
- `character_count`, `word_count` (INTEGER) - Metrics
- `duration_seconds` (REAL) - Video duration
- `confidence_score` (REAL) - Transcription quality
- `status` (TEXT) - PENDING, IN_PROGRESS, COMPLETED, FAILED
- `error_message` (TEXT) - Error details
- `created_at`, `completed_at` (TEXT) - Timestamps
- Video metadata: resolution, frame_rate, codecs, bitrate

**Total Records**: ~3,154+ transcripts (per CLAUDE.md)

#### E. Face Collections Table
**Location**: `face_collections` table
**Searchable Fields**:
- `collection_id` (TEXT) - Collection identifier
- `collection_arn` (TEXT) - AWS ARN
- `face_count` (INTEGER) - Number of indexed faces
- `metadata` (JSON) - Custom metadata
- `created_at` (TIMESTAMP) - Creation date

---

### Data Relationships

```
files (1) ─┬─> (N) analysis_jobs ──> (1) nova_jobs
           │
           ├─> (N) transcripts (via local_path)
           │
           └─> (1) proxy_files (is_proxy=1, source_file_id FK)

face_collections (used in face_search analysis_jobs via parameters)
```

**Key Insights**:
1. **Files are central**: All other data links to files
2. **Nova jobs extend analysis_jobs**: 1:1 relationship via FK
3. **Transcripts link via path**: Uses `local_path` instead of FK
4. **Proxy files are special**: Same table with `is_proxy=1` flag

---

### Search Scope Definition

#### Full-Text Searchable Fields (Priority Order)

**Tier 1 - Primary Content** (highest relevance):
- `transcripts.transcript_text` - Full speech-to-text content
- `nova_jobs.summary_result.text` - AI-generated video summaries
- `nova_jobs.chapters_result[*].title` - Chapter titles
- `nova_jobs.chapters_result[*].summary` - Chapter summaries
- `analysis_jobs.results` (extracted text):
  - Celebrity names (celebrity_recognition)
  - Detected text (text_detection - OCR)
  - Label names (label_detection)

**Tier 2 - Metadata** (medium relevance):
- `files.filename` - File names
- `files.local_path` - File paths
- `files.metadata` - Custom metadata
- `transcripts.file_name` - Transcript file names
- `nova_jobs.elements_result` - Element names/descriptions
- `face_collections.collection_id` - Collection names

**Tier 3 - Identifiers** (low relevance):
- `analysis_jobs.job_id` - Job identifiers
- `files.s3_key` - S3 keys
- `files.codec_video`, `files.codec_audio` - Codec names

---

## 3. Technical Architecture

### Database Strategy

**Approach**: Hybrid SQLite LIKE + JSON extraction (no FTS5 initially for simplicity)

#### Why NOT FTS5 (Full-Text Search Extension)?
- **Complexity**: Requires maintaining shadow tables, triggers for sync
- **JSON Challenge**: FTS5 doesn't natively index JSON fields
- **Performance**: LIKE with proper indexes is sufficient for <10,000 records
- **Flexibility**: Easier to adjust relevance ranking and field weighting

#### Search Query Structure

```sql
-- Unified search query with UNION approach
-- Results combined from multiple data sources with source tagging

-- 1. Search in files
SELECT
    'file' as source_type,
    id as source_id,
    filename as title,
    file_type as category,
    uploaded_at as timestamp,
    CASE
        WHEN filename LIKE '%' || :search || '%' THEN 'filename'
        WHEN local_path LIKE '%' || :search || '%' THEN 'path'
        WHEN metadata LIKE '%' || :search || '%' THEN 'metadata'
    END as match_field,
    size_bytes,
    duration_seconds
FROM files
WHERE (
    filename LIKE '%' || :search || '%'
    OR local_path LIKE '%' || :search || '%'
    OR metadata LIKE '%' || :search || '%'
    OR codec_video LIKE '%' || :search || '%'
    OR codec_audio LIKE '%' || :search || '%'
)

UNION ALL

-- 2. Search in transcripts
SELECT
    'transcript' as source_type,
    id as source_id,
    file_name as title,
    'Transcript (' || model_name || ')' as category,
    created_at as timestamp,
    'transcript' as match_field,
    NULL as size_bytes,
    duration_seconds
FROM transcripts
WHERE status = 'COMPLETED'
AND (
    transcript_text LIKE '%' || :search || '%'
    OR file_name LIKE '%' || :search || '%'
)

UNION ALL

-- 3. Search in Rekognition analysis results (JSON extraction)
SELECT
    'rekognition' as source_type,
    aj.id as source_id,
    f.filename || ' - ' || aj.analysis_type as title,
    aj.analysis_type as category,
    aj.completed_at as timestamp,
    'analysis_results' as match_field,
    f.size_bytes,
    f.duration_seconds
FROM analysis_jobs aj
JOIN files f ON aj.file_id = f.id
WHERE aj.status = 'SUCCEEDED'
AND aj.results IS NOT NULL
AND (
    -- Search in stringified JSON results
    CAST(aj.results AS TEXT) LIKE '%' || :search || '%'
)

UNION ALL

-- 4. Search in Nova analysis (summary, chapters, elements)
SELECT
    'nova' as source_type,
    nj.id as source_id,
    f.filename || ' - Nova ' || nj.model as title,
    'Nova Analysis' as category,
    nj.completed_at as timestamp,
    CASE
        WHEN CAST(nj.summary_result AS TEXT) LIKE '%' || :search || '%' THEN 'summary'
        WHEN CAST(nj.chapters_result AS TEXT) LIKE '%' || :search || '%' THEN 'chapters'
        WHEN CAST(nj.elements_result AS TEXT) LIKE '%' || :search || '%' THEN 'elements'
    END as match_field,
    f.size_bytes,
    f.duration_seconds
FROM nova_jobs nj
JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id
JOIN files f ON aj.file_id = f.id
WHERE nj.status = 'COMPLETED'
AND (
    CAST(nj.summary_result AS TEXT) LIKE '%' || :search || '%'
    OR CAST(nj.chapters_result AS TEXT) LIKE '%' || :search || '%'
    OR CAST(nj.elements_result AS TEXT) LIKE '%' || :search || '%'
)

UNION ALL

-- 5. Search in face collections
SELECT
    'face_collection' as source_type,
    id as source_id,
    collection_id as title,
    'Face Collection' as category,
    created_at as timestamp,
    'collection' as match_field,
    NULL as size_bytes,
    NULL as duration_seconds
FROM face_collections
WHERE collection_id LIKE '%' || :search || '%'

ORDER BY timestamp DESC
LIMIT :limit OFFSET :offset
```

#### Index Requirements

**New Indexes Needed**:
```sql
-- Files table (already has idx_files_uploaded_at)
CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename);
CREATE INDEX IF NOT EXISTS idx_files_local_path ON files(local_path);

-- Analysis jobs (already has idx_jobs_status, idx_jobs_file_id)
CREATE INDEX IF NOT EXISTS idx_jobs_analysis_type ON analysis_jobs(analysis_type);
CREATE INDEX IF NOT EXISTS idx_jobs_completed_at ON analysis_jobs(completed_at DESC);

-- Nova jobs
CREATE INDEX IF NOT EXISTS idx_nova_jobs_status ON nova_jobs(status);
CREATE INDEX IF NOT EXISTS idx_nova_jobs_completed_at ON nova_jobs(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_nova_jobs_analysis_job_id ON nova_jobs(analysis_job_id);

-- Transcripts (already has idx_transcripts_status, idx_transcripts_model_name, idx_transcripts_file_name)
CREATE INDEX IF NOT EXISTS idx_transcripts_completed_at ON transcripts(completed_at DESC);

-- Face collections (already indexed on collection_id UNIQUE)
CREATE INDEX IF NOT EXISTS idx_collections_created_at ON face_collections(created_at DESC);
```

---

### API Endpoint Design

#### Primary Search Endpoint

**Endpoint**: `GET /api/search`

**Query Parameters**:
```python
{
    "q": str,                    # Search query (required, min 2 chars)
    "sources": List[str],        # Filter by source: ['file', 'transcript', 'rekognition', 'nova', 'collection']
    "file_type": str,            # 'video' or 'image' (for file/analysis results)
    "from_date": str,            # ISO date (YYYY-MM-DD)
    "to_date": str,              # ISO date (YYYY-MM-DD)
    "status": str,               # 'COMPLETED', 'FAILED', etc.
    "analysis_type": str,        # Rekognition analysis type filter
    "model": str,                # Nova model or Whisper model filter
    "sort_by": str,              # 'relevance', 'date', 'name' (default: 'relevance')
    "sort_order": str,           # 'asc', 'desc' (default: 'desc')
    "page": int,                 # Page number (default: 1)
    "per_page": int              # Results per page (default: 50, max: 200)
}
```

**Response Format**:
```json
{
    "query": "pool equipment",
    "total_results": 145,
    "results_by_source": {
        "file": 23,
        "transcript": 67,
        "rekognition": 34,
        "nova": 19,
        "collection": 2
    },
    "results": [
        {
            "id": "transcript_1234",
            "source_type": "transcript",
            "source_id": 1234,
            "title": "pool_installation_2023.mp4",
            "category": "Transcript (medium)",
            "timestamp": "2024-12-15T10:30:00Z",
            "match_field": "transcript",
            "preview": "...discussing the pool equipment installation process...",
            "metadata": {
                "file_id": 456,
                "model_name": "medium",
                "language": "en",
                "duration_seconds": 1800,
                "word_count": 5234
            },
            "actions": {
                "view": "/files?id=456",
                "view_transcript": "/transcriptions?id=1234",
                "download": "/transcriptions/api/transcript/1234/download?format=txt"
            }
        },
        {
            "id": "nova_789",
            "source_type": "nova",
            "source_id": 789,
            "title": "pool_showcase.mp4 - Nova lite",
            "category": "Nova Analysis",
            "timestamp": "2024-12-14T14:22:00Z",
            "match_field": "chapters",
            "preview": "...Chapter 2: Pool Equipment Overview - Showcasing the filtration system...",
            "metadata": {
                "file_id": 789,
                "model": "lite",
                "analysis_types": ["summary", "chapters"],
                "estimated_cost": 0.05
            },
            "actions": {
                "view": "/files?id=789",
                "view_analysis": "/api/nova/results/789"
            }
        }
    ],
    "pagination": {
        "page": 1,
        "per_page": 50,
        "total": 145,
        "pages": 3
    },
    "search_time_ms": 127
}
```

#### Supplementary Endpoints

**Get Search Suggestions**: `GET /api/search/suggestions?q={query}`
- Returns common search terms, recent searches
- Response: `{ "suggestions": ["pool equipment", "pool maintenance", ...] }`

**Get Search Filters**: `GET /api/search/filters`
- Returns available filter options (models, analysis types, etc.)
- Response: `{ "analysis_types": [...], "models": [...], "languages": [...] }`

---

## 4. Implementation Phases

### Phase 1: Foundation & Infrastructure (Week 1)
**Deliverables**:
- [ ] Database indexes created (7 new indexes)
- [ ] Core search route skeleton (`app/routes/search.py`)
- [ ] Search page template (`app/templates/search.html`)
- [ ] Navigation link added to `base.html`
- [ ] Basic database query function (`db.search_all()`)

**Testing**:
- Verify indexes created successfully
- Test basic route rendering
- Confirm navigation link appears

---

### Phase 2: Core Search Functionality (Week 1-2)
**Deliverables**:
- [ ] Unified search SQL query implementation
- [ ] Search API endpoint with pagination
- [ ] Result parsing and formatting logic
- [ ] Preview text extraction (150 chars with context)
- [ ] Basic frontend search UI (search box + results list)
- [ ] Source type filtering (checkboxes)

**Testing**:
- Search returns results from all sources
- Pagination works correctly
- Preview text highlights search terms
- Filter by source type works

---

### Phase 3: Advanced Features (Week 2)
**Deliverables**:
- [ ] Advanced filters UI (collapsible panel)
  - Date range picker
  - File type filter (video/image)
  - Status filter
  - Analysis type filter
  - Model filter (Whisper/Nova)
- [ ] Sort options (relevance, date, name)
- [ ] Result grouping by source type (tabs or sections)
- [ ] Search result highlighting
- [ ] Quick actions per result type
  - Files: View, Download, Analyze
  - Transcripts: View, Download (TXT/SRT/VTT)
  - Analysis: View Dashboard, Download JSON/Excel
  - Nova: View Results, Cost Details

**Testing**:
- All filters apply correctly
- Sorting produces expected order
- Grouping displays correctly
- Quick actions navigate properly

---

### Phase 4: Performance & Polish (Week 3)
**Deliverables**:
- [ ] Query performance optimization
  - Add query result caching (5 min TTL)
  - Optimize JSON field searches
  - Implement search result pre-loading
- [ ] Search suggestions/autocomplete
- [ ] Recent searches (local storage)
- [ ] Export search results (CSV/JSON)
- [ ] Mobile responsive design
- [ ] Loading states and skeleton screens
- [ ] Empty states and error handling
- [ ] Search analytics (track popular queries)

**Testing**:
- Search completes in <500ms for 10K records
- Autocomplete appears within 200ms
- Export generates valid files
- Mobile layout works on 375px width
- Error states display properly

---

## 5. UI/UX Specification

### Page Layout (Desktop)

```
┌─────────────────────────────────────────────────────────────┐
│ Navigation Bar (base.html)                                  │
│ [Home] [File Mgmt] [Transcriptions] [Upload] [Collections] │
│ [History] [Reports] [Search] 🔍                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 🔍 Unified Search                                           │
└─────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────┬──────────────┐
│ Search Input                                 │              │
│ ┌──────────────────────────────────────────┐ │ [🔍 Search] │
│ │ 🔍 Search files, transcripts, analysis...│ │              │
│ └──────────────────────────────────────────┘ │ [⚙ Filters] │
└──────────────────────────────────────────────┴──────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Advanced Filters (Collapsible)                              │
│                                                              │
│ Source Types: [x] Files  [x] Transcripts  [x] Rekognition  │
│               [x] Nova   [x] Collections                    │
│                                                              │
│ File Type: [ All ▼ ]  Status: [ All ▼ ]  Model: [ All ▼ ] │
│                                                              │
│ Date Range: [From: ____] [To: ____]                        │
│                                                              │
│ Sort By: (•) Relevance  ( ) Date  ( ) Name                 │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Search Results (145 results in 127ms)                       │
│                                                              │
│ Group By: [All Results ▼]                                  │
│           [Files (23)] [Transcripts (67)] [Rekognition...]│
│                                                              │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ 📄 pool_installation_2023.mp4                         │  │
│ │ Transcript (medium) • Dec 15, 2024 10:30 AM          │  │
│ │                                                        │  │
│ │ ...discussing the pool equipment installation         │  │
│ │ process with the new filtration system...            │  │
│ │                                                        │  │
│ │ [View File] [View Transcript] [Download ▼]           │  │
│ └───────────────────────────────────────────────────────┘  │
│                                                              │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ ⭐ pool_showcase.mp4 - Nova lite                      │  │
│ │ Nova Analysis • Dec 14, 2024 2:22 PM                 │  │
│ │                                                        │  │
│ │ Chapter 2: Pool Equipment Overview - Showcasing the   │  │
│ │ filtration system, pump, and heating components...   │  │
│ │                                                        │  │
│ │ [View File] [View Analysis] [Cost: $0.05]            │  │
│ └───────────────────────────────────────────────────────┘  │
│                                                              │
│ ┌───────────────────────────────────────────────────────┐  │
│ │ 🏷️ backyard_pool.jpg - Label Detection                │  │
│ │ Rekognition Analysis • Dec 10, 2024 4:15 PM          │  │
│ │                                                        │  │
│ │ Detected: Swimming Pool (98%), Pool Equipment (94%),  │  │
│ │ Water (92%), Outdoor (89%)                            │  │
│ │                                                        │  │
│ │ [View File] [View Dashboard] [Download ▼]            │  │
│ └───────────────────────────────────────────────────────┘  │
│                                                              │
│ [< Prev] [1] [2] [3] [Next >]                              │
└─────────────────────────────────────────────────────────────┘
```

### Mobile Layout (375px)

```
┌─────────────────────┐
│ ☰ 🔍 Unified Search │
└─────────────────────┘

┌─────────────────────┐
│ 🔍 Search...        │
│ [🔍] [⚙]           │
└─────────────────────┘

┌─────────────────────┐
│ Filters (Expandable)│
└─────────────────────┘

┌─────────────────────┐
│ 145 results         │
│                     │
│ ┌─────────────────┐ │
│ │ 📄 pool_inst... │ │
│ │ Transcript      │ │
│ │ Dec 15, 10:30   │ │
│ │                 │ │
│ │ ...pool equip...│ │
│ │                 │ │
│ │ [View] [Down ▼] │ │
│ └─────────────────┘ │
│                     │
│ [< 1 2 3 >]        │
└─────────────────────┘
```

### Key UI Components

1. **Search Input**
   - Large, prominent search box
   - Placeholder: "Search files, transcripts, analysis results..."
   - Search icon prefix
   - Clear button (X) when text present
   - Keyboard shortcut: Ctrl+K / Cmd+K to focus

2. **Filters Panel**
   - Collapsible accordion (Bootstrap collapse)
   - Source type checkboxes (multi-select)
   - Dropdown filters (file type, status, model)
   - Date range inputs (HTML5 date type)
   - Radio buttons for sort options
   - Apply/Reset buttons

3. **Results List**
   - Card-based layout (Bootstrap cards)
   - Source type icon (📄 file, 📝 transcript, 🔍 rekognition, ⭐ nova, 👤 collection)
   - Title (bold, larger font)
   - Category + timestamp (muted, smaller)
   - Preview text (3 lines max, ellipsis)
   - Highlighted search terms (yellow background)
   - Quick action buttons (context-specific)

4. **Pagination**
   - Bootstrap pagination component
   - Show current page / total pages
   - Prev/Next buttons
   - Direct page number links (max 5 visible)

5. **Empty States**
   - No results: "No results found for '{query}'. Try different keywords or adjust filters."
   - No query: "Enter a search query to find files, transcripts, and analysis results."
   - Error: "Search failed. Please try again or contact support."

6. **Loading States**
   - Search button: Spinner during search
   - Results: Skeleton cards (3 placeholder cards)
   - Filters: Disabled during search

---

## 6. API Specification

### GET /api/search

**Description**: Unified search across all application data.

**Request**:
```http
GET /api/search?q=pool+equipment&sources=transcript,nova&page=1&per_page=50
```

**Query Parameters**:
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | string | Yes | - | Search query (min 2 chars, max 500 chars) |
| `sources` | string[] | No | all | Comma-separated: file,transcript,rekognition,nova,collection |
| `file_type` | string | No | - | Filter: video, image |
| `from_date` | string | No | - | ISO date: YYYY-MM-DD |
| `to_date` | string | No | - | ISO date: YYYY-MM-DD |
| `status` | string | No | - | Filter: COMPLETED, FAILED, etc. |
| `analysis_type` | string | No | - | Rekognition type filter |
| `model` | string | No | - | Model filter (whisper models or nova models) |
| `sort_by` | string | No | relevance | Options: relevance, date, name |
| `sort_order` | string | No | desc | Options: asc, desc |
| `page` | integer | No | 1 | Page number (min: 1) |
| `per_page` | integer | No | 50 | Results per page (min: 10, max: 200) |

**Success Response** (200 OK):
```json
{
    "query": "pool equipment",
    "total_results": 145,
    "results_by_source": {
        "file": 23,
        "transcript": 67,
        "rekognition": 34,
        "nova": 19,
        "collection": 2
    },
    "results": [
        {
            "id": "transcript_1234",
            "source_type": "transcript",
            "source_id": 1234,
            "title": "pool_installation_2023.mp4",
            "category": "Transcript (medium)",
            "timestamp": "2024-12-15T10:30:00Z",
            "match_field": "transcript",
            "preview": "...discussing the pool equipment installation process...",
            "metadata": {
                "file_id": 456,
                "model_name": "medium",
                "language": "en",
                "duration_seconds": 1800,
                "word_count": 5234
            },
            "actions": {
                "view": "/files?id=456",
                "view_transcript": "/transcriptions?id=1234",
                "download": "/transcriptions/api/transcript/1234/download?format=txt"
            }
        }
    ],
    "pagination": {
        "page": 1,
        "per_page": 50,
        "total": 145,
        "pages": 3
    },
    "filters_applied": {
        "sources": ["transcript", "nova"],
        "file_type": null,
        "from_date": null,
        "to_date": null,
        "status": null,
        "analysis_type": null,
        "model": null
    },
    "search_time_ms": 127
}
```

**Error Responses**:

400 Bad Request:
```json
{
    "error": "Search query required",
    "details": "Parameter 'q' must be provided and at least 2 characters"
}
```

500 Internal Server Error:
```json
{
    "error": "Search failed",
    "details": "An error occurred while searching"
}
```

---

### GET /api/search/filters

**Description**: Get available filter options for search.

**Request**:
```http
GET /api/search/filters
```

**Success Response** (200 OK):
```json
{
    "analysis_types": [
        "label_detection",
        "face_detection",
        "celebrity_recognition",
        "content_moderation",
        "text_detection",
        "person_tracking",
        "face_search",
        "shot_segmentation",
        "ppe_detection",
        "face_comparison"
    ],
    "models": {
        "whisper": ["tiny", "base", "small", "medium", "large-v2", "large-v3"],
        "nova": ["micro", "lite", "pro", "premier"],
        "nova_sonic": ["nova-2-sonic"]
    },
    "languages": ["en", "es", "fr", "de", "ja", "zh"],
    "statuses": ["PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "SUBMITTED", "SUCCEEDED"],
    "file_types": ["video", "image"]
}
```

---

### GET /api/search/suggestions

**Description**: Get search query suggestions (autocomplete).

**Request**:
```http
GET /api/search/suggestions?q=pool
```

**Query Parameters**:
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | Yes | Partial search query (min 2 chars) |

**Success Response** (200 OK):
```json
{
    "query": "pool",
    "suggestions": [
        "pool equipment",
        "pool maintenance",
        "pool installation",
        "pool showcase",
        "swimming pool"
    ]
}
```

**Note**: Initial implementation returns static suggestions. Future enhancement: Track popular searches in database.

---

## 7. Database Changes

### New Indexes

Execute via migration or manual SQL:

```sql
-- Files table
CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename);
CREATE INDEX IF NOT EXISTS idx_files_local_path ON files(local_path);

-- Analysis jobs
CREATE INDEX IF NOT EXISTS idx_jobs_analysis_type ON analysis_jobs(analysis_type);
CREATE INDEX IF NOT EXISTS idx_jobs_completed_at ON analysis_jobs(completed_at DESC);

-- Nova jobs (table may need creation if not exists)
CREATE TABLE IF NOT EXISTS nova_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_job_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    analysis_types TEXT NOT NULL,
    user_options TEXT,
    status TEXT NOT NULL DEFAULT 'SUBMITTED',
    summary_result TEXT,
    chapters_result TEXT,
    elements_result TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    progress_percent INTEGER DEFAULT 0,
    current_chunk INTEGER,
    total_chunks INTEGER,
    estimated_cost REAL,
    actual_cost REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    processing_time REAL,
    error_message TEXT,
    FOREIGN KEY (analysis_job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_nova_jobs_status ON nova_jobs(status);
CREATE INDEX IF NOT EXISTS idx_nova_jobs_completed_at ON nova_jobs(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_nova_jobs_analysis_job_id ON nova_jobs(analysis_job_id);

-- Transcripts
CREATE INDEX IF NOT EXISTS idx_transcripts_completed_at ON transcripts(completed_at DESC);

-- Face collections
CREATE INDEX IF NOT EXISTS idx_collections_created_at ON face_collections(created_at DESC);
```

### Database Methods

Add to `app/database.py`:

```python
def search_all(
    self,
    query: str,
    sources: Optional[List[str]] = None,
    file_type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    status: Optional[str] = None,
    analysis_type: Optional[str] = None,
    model: Optional[str] = None,
    sort_by: str = 'relevance',
    sort_order: str = 'desc',
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Unified search across all data sources.

    Returns list of search result dictionaries with:
    - source_type: 'file', 'transcript', 'rekognition', 'nova', 'collection'
    - source_id: Primary key from source table
    - title: Display title
    - category: Result category
    - timestamp: Relevant date/time
    - match_field: Which field matched
    - preview: Preview text (150 chars)
    - metadata: Type-specific metadata
    """
    # Implementation uses UNION query shown in section 3
    pass

def count_search_results(
    self,
    query: str,
    sources: Optional[List[str]] = None,
    # ... same filters as search_all ...
) -> Dict[str, int]:
    """
    Count search results by source type.

    Returns: {
        'total': 145,
        'file': 23,
        'transcript': 67,
        'rekognition': 34,
        'nova': 19,
        'collection': 2
    }
    """
    pass

def get_search_filters(self) -> Dict[str, List[str]]:
    """
    Get available filter options from database.

    Queries distinct values for:
    - analysis_types
    - models (whisper + nova)
    - languages
    - statuses
    """
    pass
```

---

## 8. File Changes Summary

### New Files

1. **`app/routes/search.py`** (~400 lines)
   - Blueprint definition
   - GET `/` - Render search page template
   - GET `/api/search` - Unified search endpoint
   - GET `/api/search/filters` - Filter options endpoint
   - GET `/api/search/suggestions` - Search suggestions endpoint
   - Helper functions for result parsing, preview generation

2. **`app/templates/search.html`** (~500 lines)
   - Extends `base.html`
   - Search input with icon and clear button
   - Advanced filters panel (collapsible)
   - Results display area with cards
   - Pagination controls
   - Empty states (no results, no query, error)
   - Loading states (skeleton cards)

3. **`app/static/js/search.js`** (~600 lines)
   - Search input debouncing (300ms)
   - Filter state management
   - API calls to search endpoint
   - Result rendering with highlighting
   - Pagination handling
   - URL state management (update URL params)
   - Local storage for recent searches
   - Keyboard shortcuts (Ctrl+K focus, Escape clear)

4. **`app/static/css/search.css`** (~200 lines)
   - Search page specific styles
   - Result card styling
   - Highlight styling (yellow background)
   - Filter panel styling
   - Mobile responsive breakpoints

### Modified Files

1. **`app/templates/base.html`** (~5 lines changed)
   - Add navigation link: `<a class="nav-link" href="/search">🔍 Search</a>`
   - Position: After "Reports", before end of navbar

2. **`app/__init__.py`** (~3 lines added)
   - Import search blueprint: `from app.routes import search`
   - Register blueprint: `app.register_blueprint(search.bp)`

3. **`app/database.py`** (~200 lines added)
   - Add `search_all()` method (150 lines)
   - Add `count_search_results()` method (30 lines)
   - Add `get_search_filters()` method (20 lines)
   - Add indexes in `_init_db()` method (10 lines)

4. **`app/static/css/style.css`** (~10 lines added)
   - Global search highlight class
   - Search icon styling

---

## 9. Testing Strategy

### Unit Tests

**File**: `tests/test_search.py`

1. **Database Tests**
   - `test_search_all_files()` - Search returns file results
   - `test_search_all_transcripts()` - Search returns transcript results
   - `test_search_all_rekognition()` - Search returns Rekognition results
   - `test_search_all_nova()` - Search returns Nova results
   - `test_search_all_collections()` - Search returns collection results
   - `test_search_with_filters()` - Filters apply correctly
   - `test_search_pagination()` - Pagination works
   - `test_count_search_results()` - Count by source correct
   - `test_get_search_filters()` - Filter options returned

2. **API Tests**
   - `test_search_endpoint_valid()` - Valid search returns 200
   - `test_search_endpoint_no_query()` - Missing query returns 400
   - `test_search_endpoint_short_query()` - Short query (<2 chars) returns 400
   - `test_search_endpoint_pagination()` - Pagination params work
   - `test_search_endpoint_filters()` - Filter params work
   - `test_filters_endpoint()` - Filters endpoint returns data
   - `test_suggestions_endpoint()` - Suggestions endpoint works

3. **Preview Generation Tests**
   - `test_preview_extraction_short()` - Short text returns full text
   - `test_preview_extraction_long()` - Long text truncates at 150 chars
   - `test_preview_extraction_with_match()` - Match term appears in preview

### Integration Tests

**File**: `tests/integration/test_search_integration.py`

1. **End-to-End Search**
   - `test_search_workflow()` - Full search from query to results display
   - `test_search_multiple_sources()` - Results from multiple sources combined
   - `test_search_with_all_filters()` - All filters applied simultaneously

2. **Performance Tests**
   - `test_search_performance_10k_records()` - Search completes <500ms with 10K records
   - `test_search_performance_large_json()` - JSON field search performs well
   - `test_pagination_performance()` - Pagination doesn't degrade with large datasets

3. **Data Integrity Tests**
   - `test_search_result_links()` - All action links are valid URLs
   - `test_search_result_metadata()` - Metadata matches source records
   - `test_search_result_preview()` - Preview text matches source content

### Edge Cases

1. **Empty/Null Data**
   - Search with no results
   - Search with NULL JSON fields
   - Search with empty transcript text
   - Search with files missing metadata

2. **Special Characters**
   - Search with quotes: `"pool equipment"`
   - Search with SQL special chars: `pool's equipment`
   - Search with Unicode: `пулу екуіпмент`
   - Search with HTML: `<pool> equipment`

3. **Boundary Conditions**
   - Query exactly 2 characters (minimum)
   - Query 500 characters (maximum)
   - Page number 0 (invalid)
   - Page number beyond total pages
   - Per-page 201 (exceeds max)

4. **Concurrent Access**
   - Multiple users searching simultaneously
   - Search during database writes
   - Search during analysis job updates

5. **Large Dataset**
   - 10,000+ files
   - 10,000+ transcripts
   - 100,000+ analysis results
   - JSON fields >1MB

### Stress Tests

1. **Load Testing**
   - 100 concurrent search requests
   - 1,000 searches/minute
   - Search with 50 simultaneous filters

2. **Data Volume**
   - Search across 50,000 total records
   - Search with 10,000 matching results
   - Paginate through 1,000 pages

3. **Complex Queries**
   - Search with all filters enabled
   - Search with 50-character query
   - Search across all 5 source types

---

## 10. Considerations & Trade-offs

### Alternative Approaches Considered

#### 1. SQLite FTS5 (Full-Text Search Extension)
**Pros**:
- Built-in ranking and relevance scoring
- Optimized for text search
- Faster for very large datasets (100K+ records)

**Cons**:
- Requires maintaining shadow tables
- Complex trigger setup for sync
- JSON fields require extraction to separate columns
- Added complexity for marginal benefit at current scale

**Decision**: Not using FTS5 initially. Can migrate later if dataset grows >50K records.

#### 2. Elasticsearch / OpenSearch
**Pros**:
- Industry-standard full-text search
- Advanced features (fuzzy matching, autocomplete)
- Scales to millions of records

**Cons**:
- External dependency (requires separate service)
- Operational complexity (deployment, monitoring)
- Overkill for current dataset size
- Data synchronization challenges

**Decision**: Not using. SQLite is sufficient for current needs.

#### 3. Separate Search Table (Denormalized)
**Pros**:
- Single table for all searchable content
- Faster queries (no JOINs)
- Easier to add full-text indexes

**Cons**:
- Data duplication
- Synchronization complexity (triggers)
- Storage overhead
- Potential for stale data

**Decision**: Not using. UNION query approach maintains single source of truth.

---

### Performance vs Complexity Trade-offs

#### Chosen Approach: UNION Query with LIKE
**Performance**:
- **Good** for <10,000 records: <500ms response time
- **Acceptable** for 10,000-50,000 records: <1s response time
- **Degradation** beyond 50,000 records: May need FTS5 migration

**Complexity**:
- **Low** implementation complexity
- **Moderate** query complexity (5 UNION subqueries)
- **Low** maintenance burden

**Scalability Path**:
1. **Phase 1** (current): LIKE queries with indexes
2. **Phase 2** (if >50K records): Migrate to FTS5
3. **Phase 3** (if >500K records): Consider Elasticsearch

#### Relevance Ranking

**Simple Approach** (Phase 1):
- Order by timestamp DESC (most recent first)
- User can manually sort by name/date

**Advanced Approach** (Future):
- Calculate relevance score:
  - Filename match: +10 points
  - Exact phrase match: +5 points
  - Partial match: +1 point
  - Match in transcript: +3 points
  - Match in title vs body: Different weights
- Order by relevance score DESC

**Decision**: Start simple (timestamp), add scoring in Phase 4 if users request it.

---

### Future Enhancement Possibilities

1. **Advanced Search Operators**
   - Quoted phrases: `"exact phrase"`
   - Boolean operators: `pool AND equipment`, `pool OR spa`
   - Exclusion: `pool -maintenance`
   - Field-specific: `filename:pool`, `transcript:equipment`

2. **Search Analytics**
   - Track popular search queries
   - Track zero-result queries (UX improvement opportunities)
   - Track click-through rates per result type
   - Search performance monitoring

3. **Saved Searches**
   - Save frequently used searches
   - Email/notification alerts for new matching content
   - Share searches with team members

4. **Visual Search** (Future Phase 5)
   - Search by uploading a reference image
   - Find similar videos based on visual content
   - Leverage Rekognition comparison features

5. **Semantic Search** (Future Phase 6)
   - Use Nova embeddings for semantic similarity
   - "Find videos about X" instead of keyword matching
   - Leverage `nova_embeddings` table (already in schema)

6. **Search Export**
   - Export search results to CSV/Excel
   - Include metadata and preview text
   - Bulk download matched files

7. **Search History**
   - Store recent searches (last 10)
   - Quick re-run of previous searches
   - Clear history option

8. **Autocomplete Improvements**
   - Suggest field names: `filename:`, `transcript:`
   - Suggest common search patterns
   - Learn from user's search history

---

### Data Privacy & Security

**Considerations**:
1. **Search Query Logging**
   - Store search queries for analytics (optional)
   - Anonymize user identifiers
   - Retention policy: 90 days

2. **Access Control**
   - Current implementation: No auth (single-user app)
   - Future: Filter results by user permissions
   - Future: Role-based search scopes

3. **Sensitive Content**
   - Search results may include sensitive file names
   - Consider redaction options for certain fields
   - Audit log for searches on sensitive content

---

## Verification Checklist

- [x] Complete inventory of all searchable data types
- [x] Clear database schema changes documented
- [x] API endpoints fully specified with examples
- [x] UI wireframe/description provided
- [x] Implementation phases with clear deliverables
- [x] Performance considerations addressed (targeting <500ms)
- [x] All affected files listed with change descriptions
- [x] Testing strategy includes unit, integration, edge cases, and stress tests
- [x] Alternative approaches evaluated
- [x] Future enhancements identified

---

## Success Criteria

The Search page implementation is complete when:

1. ✅ Users can search across all 5 data types (files, transcripts, Rekognition, Nova, collections) from a single input
2. ✅ Search returns relevant results in <500ms for datasets up to 10,000 records
3. ✅ Advanced filters work correctly (source type, date range, file type, status, analysis type, model)
4. ✅ Results display with proper formatting, preview text, and quick action buttons
5. ✅ Pagination handles large result sets (1000+ results)
6. ✅ Mobile responsive design works on 375px width screens
7. ✅ Search suggestions/autocomplete provides helpful query assistance
8. ✅ All unit tests pass (minimum 15 tests)
9. ✅ Integration tests verify end-to-end workflows
10. ✅ Performance tests confirm <500ms response time target met

---

## Appendix A: Sample Search Queries

**Query 1: Simple keyword search**
```
Input: "pool equipment"
Expected: Matches in filenames, transcript text, Nova summaries, detected labels
Results: Files named "pool_equipment.mp4", transcripts containing "pool equipment",
         Nova chapters about pool equipment, Rekognition labels "Pool Equipment"
```

**Query 2: Technical term search**
```
Input: "H.264"
Expected: Matches in codec_video fields, transcript tech discussions
Results: Files with H.264 video codec, transcripts mentioning H.264 encoding
```

**Query 3: Celebrity name search**
```
Input: "Jeff Bezos"
Expected: Matches in celebrity_recognition analysis results
Results: Rekognition jobs that detected Jeff Bezos in videos/images
```

**Query 4: OCR text search**
```
Input: "WARNING SIGN"
Expected: Matches in text_detection analysis results
Results: Videos/images where text "WARNING SIGN" was detected
```

**Query 5: Date-specific search**
```
Input: "installation"
Filters: from_date=2024-01-01, to_date=2024-12-31, sources=transcript
Expected: Transcripts from 2024 containing "installation"
Results: Filtered to specific date range and source type
```

---

## Appendix B: Database Query Performance Benchmarks

**Test Environment**:
- SQLite 3.x
- Windows 10
- 10,000 total records (3,000 files, 3,000 transcripts, 2,500 analysis jobs, 1,500 nova jobs)

**Benchmark Results** (estimated):

| Query Type | Records Matched | Response Time | Notes |
|------------|----------------|---------------|-------|
| Simple keyword (1 word) | 150 | 120ms | Acceptable |
| Multi-word phrase | 75 | 180ms | Good |
| Search all sources | 500 | 320ms | Within target |
| Search with 3 filters | 50 | 210ms | Excellent |
| JSON field search | 200 | 450ms | At limit |
| Pagination (page 50) | 50 | 140ms | No degradation |

**Conclusion**: Performance targets achievable with proper indexing.

---

## Appendix C: UI Component Library

**Bootstrap 5 Components Used**:
- Cards (`.card`, `.card-body`, `.card-header`)
- Forms (`.form-control`, `.form-select`, `.form-check`)
- Buttons (`.btn`, `.btn-primary`, `.btn-outline-secondary`)
- Input groups (`.input-group`)
- Pagination (`.pagination`)
- Collapse (`.collapse`, `data-bs-toggle="collapse"`)
- Badges (`.badge`)
- Alerts (`.alert`, `.alert-info`)

**Bootstrap Icons**:
- `bi-search` - Search icon
- `bi-funnel` - Filter icon
- `bi-x` - Clear icon
- `bi-file-earmark-text` - File icon
- `bi-card-text` - Transcript icon
- `bi-eye` - Rekognition icon
- `bi-stars` - Nova icon
- `bi-people` - Collection icon

---

## End of Implementation Plan

**Plan Version**: 1.0
**Created**: 2025-12-20
**Author**: Claude Code (Sonnet 4.5)
**Status**: Ready for Implementation
**Estimated Effort**: 3 weeks (1 developer)
**Risk Level**: Low
**Dependencies**: None (uses existing infrastructure)

**Next Steps**:
1. Review plan with stakeholders
2. Approve database schema changes
3. Begin Phase 1 implementation
4. Setup testing environment
5. Track progress via TodoWrite tool
