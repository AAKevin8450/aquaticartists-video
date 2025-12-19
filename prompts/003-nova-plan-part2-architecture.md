# AWS Nova Integration Plan - Part 2: Technical Architecture & Implementation

<objective>
Continue building the AWS Nova integration plan by designing the technical architecture, implementation details, and cost/performance considerations. This part adds sections 4-6 to the existing plan document.

This is Part 2 of 3. You will APPEND to the existing `./20251218NovaImplementation.md` file.
</objective>

<context>
Part 1 has been completed with:
- Executive Summary
- Section 1: AWS Nova Service Overview
- Section 2: Feature Design Specifications
- Section 3: Long Video Handling Strategy (to be added in Part 2)

Read the existing plan:
- @20251218NovaImplementation.md - Review what's already documented

Review the application architecture:
- @app/services/rekognition_video.py - Current async video analysis pattern
- @app/routes/analysis.py - API endpoint structure
- @app/database.py - Database operations and schema
- @requirements.txt - Current dependencies
</context>

<research_tasks>
Research the following technical areas:

## Long Video Chunking
- AWS Nova context window limits for each model
- Best practices for video chunking strategies
- Overlap recommendations to preserve context
- Result aggregation techniques

Search queries:
- "AWS Bedrock Nova context window limits"
- "Video chunking strategies for LLM analysis"

## Implementation Patterns
- Async vs sync processing with Nova
- Error handling for Bedrock API
- boto3 bedrock-runtime best practices

Search queries:
- "AWS Bedrock async processing patterns"
- "boto3 bedrock-runtime error handling"
</research_tasks>

<deliverable>
APPEND the following sections to `./20251218NovaImplementation.md`:

```markdown

## 3. Long Video Handling Strategy

### 3.1 Context Window Analysis

**Nova Model Token Limits**:
- Nova Micro: [X tokens] ≈ [Y minutes of video]
- Nova Lite: [X tokens] ≈ [Y minutes of video]
- Nova Pro: [X tokens] ≈ [Y minutes of video]

[Explain how video content translates to tokens: frames sampled + audio transcription + metadata]

**Chunking Necessity**:
Videos longer than the context window must be split into chunks. For example:
- 2-hour video with Nova Lite → Requires ~[N] chunks
- Each chunk needs overlap to preserve context

### 3.2 Chunking Architecture

**Recommended Chunk Sizes**:

| Model | Max Context | Recommended Chunk | Overlap | Effective Content |
|-------|-------------|-------------------|---------|-------------------|
| Nova Micro | [tokens] | [duration] | [duration] | [duration] |
| Nova Lite | [tokens] | [duration] | [duration] | [duration] |
| Nova Pro | [tokens] | [duration] | [duration] | [duration] |

**Overlap Strategy**:
- Use 10-15% overlap between chunks
- Preserves context across boundaries
- Helps with chapter detection spanning chunks
- Example: 10-minute chunks with 1-minute overlap

**Processing Approach**:
- **Sequential**: Process chunks one after another, maintain context via prompt
- **Parallel**: Process chunks simultaneously, merge results afterward
- **Recommendation**: Sequential for chapter detection, parallel for independent summaries

### 3.3 Result Aggregation Algorithm

**Pseudocode**:
```python
def analyze_long_video(video_path, model, analysis_type):
    """
    Analyze a long video by chunking and aggregating results.

    Args:
        video_path: S3 path to video file
        model: 'micro', 'lite', or 'pro'
        analysis_type: 'summary', 'chapters', 'elements'

    Returns:
        Aggregated analysis results
    """
    # Step 1: Determine video duration
    duration = get_video_duration(video_path)

    # Step 2: Calculate chunk parameters
    chunk_size = get_chunk_size(model)  # e.g., 10 minutes
    overlap = chunk_size * 0.1  # 10% overlap

    # Step 3: Generate chunk boundaries
    chunks = []
    start = 0
    while start < duration:
        end = min(start + chunk_size, duration)
        chunks.append({
            'start': start,
            'end': end,
            'overlap_start': max(0, start - overlap),
            'overlap_end': min(duration, end + overlap)
        })
        start = end

    # Step 4: Process each chunk
    chunk_results = []
    previous_context = None

    for i, chunk in enumerate(chunks):
        # Extract chunk from video
        chunk_video = extract_video_segment(
            video_path,
            chunk['overlap_start'],
            chunk['overlap_end']
        )

        # Build prompt with context from previous chunk
        prompt = build_chunk_prompt(
            analysis_type,
            chunk_index=i,
            total_chunks=len(chunks),
            previous_summary=previous_context
        )

        # Analyze chunk
        result = invoke_nova(
            model=model,
            video=chunk_video,
            prompt=prompt
        )

        chunk_results.append({
            'chunk': i,
            'time_range': (chunk['start'], chunk['end']),
            'result': result
        })

        # Save context for next chunk
        previous_context = extract_context_summary(result)

    # Step 5: Aggregate results
    if analysis_type == 'summary':
        return aggregate_summaries(chunk_results)
    elif analysis_type == 'chapters':
        return merge_chapters(chunk_results, overlap)
    elif analysis_type == 'elements':
        return combine_elements(chunk_results)

def aggregate_summaries(chunk_results):
    """Merge multiple chunk summaries into coherent whole."""
    # Combine all chunk summaries
    combined_text = "\n\n".join([
        f"Part {r['chunk']+1}: {r['result']['summary']}"
        for r in chunk_results
    ])

    # Use Nova to create final unified summary
    final_prompt = f"""
    Here are summaries of different parts of a video:

    {combined_text}

    Create a single coherent summary of the entire video,
    integrating all parts into a unified narrative.
    """

    final_summary = invoke_nova(model='lite', prompt=final_prompt)
    return final_summary

def merge_chapters(chunk_results, overlap):
    """Merge chapters from overlapping chunks."""
    all_chapters = []
    seen_timestamps = set()

    for result in chunk_results:
        for chapter in result['result']['chapters']:
            # Adjust timestamps to absolute video time
            absolute_start = result['time_range'][0] + chapter['start_time']

            # Deduplicate chapters in overlap regions
            timestamp_key = round(absolute_start)
            if timestamp_key not in seen_timestamps:
                chapter['start_time'] = absolute_start
                chapter['end_time'] = result['time_range'][0] + chapter['end_time']
                all_chapters.append(chapter)
                seen_timestamps.add(timestamp_key)

    return sorted(all_chapters, key=lambda x: x['start_time'])

def combine_elements(chunk_results):
    """Combine identified elements from all chunks."""
    elements = {
        'equipment': [],
        'objects': [],
        'topics_discussed': []
    }

    for result in chunk_results:
        # Merge equipment detections
        for equipment in result['result']['equipment']:
            # Adjust time ranges to absolute video time
            adjust_time_ranges(equipment, result['time_range'][0])

            # Merge with existing detection or add new
            merge_or_add(elements['equipment'], equipment)

    return elements
```

**Context Preservation Techniques**:
1. **Carry-forward summaries**: Include brief summary of previous chunks in next chunk's prompt
2. **Overlap analysis**: Compare detections in overlap regions to ensure consistency
3. **Global context**: Maintain running list of detected elements across all chunks
4. **Temporal coherence**: Ensure chapter boundaries align logically across chunk boundaries

## 4. Technical Implementation Plan

### 4.1 Service Layer (`app/services/nova_service.py`)

**Core Functions**:

```python
# Function signatures and descriptions

def analyze_video_with_nova(
    s3_key: str,
    model: str,  # 'micro', 'lite', or 'pro'
    analysis_types: List[str],  # ['summary', 'chapters', 'elements']
    options: dict = None
) -> dict:
    """
    Main entry point for Nova video analysis.
    Handles chunking automatically for long videos.
    """
    pass

def invoke_nova_model(
    model_id: str,
    video_bytes: bytes,
    prompt: str,
    max_tokens: int = 4096
) -> dict:
    """
    Low-level function to invoke Nova via Bedrock API.
    Handles retries and error handling.
    """
    pass

def chunk_video(
    video_path: str,
    chunk_duration: int,
    overlap: int
) -> List[dict]:
    """
    Split video into chunks with overlap.
    Returns list of chunk metadata.
    """
    pass

def extract_video_segment(
    s3_key: str,
    start_time: float,
    end_time: float
) -> bytes:
    """
    Extract video segment using FFmpeg.
    Returns video bytes for Nova processing.
    """
    pass

def aggregate_chunk_results(
    chunk_results: List[dict],
    analysis_type: str
) -> dict:
    """
    Aggregate results from multiple chunks.
    Uses strategies from section 3.3.
    """
    pass

def build_prompt(
    analysis_type: str,
    options: dict,
    context: dict = None
) -> str:
    """
    Build optimized prompt for Nova based on analysis type.
    Includes context from previous chunks if provided.
    """
    pass
```

**Model Selection Logic**:
```python
def select_optimal_model(video_duration: int, quality: str = 'balanced') -> str:
    """
    Recommend Nova model based on video duration and quality preference.

    Args:
        video_duration: Video length in seconds
        quality: 'fast', 'balanced', or 'best'

    Returns:
        Model name: 'micro', 'lite', or 'pro'
    """
    if quality == 'fast':
        return 'micro'
    elif quality == 'best':
        return 'pro'
    else:  # balanced
        if video_duration < 300:  # < 5 minutes
            return 'lite'
        elif video_duration < 1800:  # < 30 minutes
            return 'lite'
        else:
            return 'pro'  # Long videos benefit from larger context
```

**Error Handling**:
- `ThrottlingException`: Implement exponential backoff
- `ModelNotReadyException`: Wait and retry
- `ValidationException`: Return clear error to user
- `AccessDeniedException`: Check IAM permissions
- Network errors: Retry with exponential backoff (max 3 retries)

### 4.2 Database Schema Updates

**Option A: Extend Existing `jobs` Table**

Add columns:
```sql
ALTER TABLE jobs ADD COLUMN service VARCHAR(20) DEFAULT 'rekognition';
-- Values: 'rekognition', 'nova', 'both'

ALTER TABLE jobs ADD COLUMN nova_model VARCHAR(20);
-- Values: 'micro', 'lite', 'pro', NULL

ALTER TABLE jobs ADD COLUMN nova_results TEXT;
-- JSON string containing Nova analysis results

ALTER TABLE jobs ADD COLUMN chunk_count INTEGER DEFAULT 0;
-- Number of chunks processed (0 for non-chunked videos)
```

**Option B: Create Separate `nova_jobs` Table** (Recommended)

```sql
CREATE TABLE nova_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,  -- FK to jobs table
    model VARCHAR(20) NOT NULL,  -- 'micro', 'lite', 'pro'
    analysis_types TEXT NOT NULL,  -- JSON array: ["summary", "chapters", "elements"]

    -- Chunking info
    chunk_count INTEGER DEFAULT 0,
    chunk_size INTEGER,  -- Duration in seconds

    -- Results
    summary TEXT,  -- Video summary
    chapters TEXT,  -- JSON array of chapters
    identified_elements TEXT,  -- JSON object of elements

    -- Metadata
    tokens_used INTEGER,
    processing_time FLOAT,
    cost_estimate FLOAT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,

    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX idx_nova_jobs_job_id ON nova_jobs(job_id);
CREATE INDEX idx_nova_jobs_model ON nova_jobs(model);
```

**Migration Notes**:
- Create new table with migration script
- Existing jobs table remains unchanged
- Nova results linked via job_id foreign key
- Allows one video to have both Rekognition and Nova results

### 4.3 API Endpoints (`app/routes/nova_analysis.py`)

**New Blueprint**: Create `nova_bp` blueprint

**Endpoint 1: Start Nova Analysis**
```
POST /nova/analyze
```

Request:
```json
{
  "s3_key": "videos/example.mp4",
  "model": "lite",  // 'micro', 'lite', 'pro', or 'auto'
  "analysis_types": ["summary", "chapters", "elements"],
  "options": {
    "summary_depth": "standard",  // 'brief', 'standard', 'detailed'
    "detect_equipment": true,
    "detect_topics": true,
    "language": "auto"  // or specific language code
  }
}
```

Response:
```json
{
  "job_id": 123,
  "nova_job_id": 45,
  "status": "SUBMITTED",
  "model": "lite",
  "estimated_chunks": 3,
  "estimated_time": "5-7 minutes"
}
```

**Endpoint 2: Check Status**
```
GET /nova/job-status/<nova_job_id>
```

Response:
```json
{
  "nova_job_id": 45,
  "job_id": 123,
  "status": "IN_PROGRESS",
  "progress": {
    "chunks_completed": 2,
    "chunks_total": 3,
    "percent": 67,
    "current_stage": "Processing chunk 3/3"
  }
}
```

**Endpoint 3: Get Results**
```
GET /nova/results/<nova_job_id>
```

Response:
```json
{
  "nova_job_id": 45,
  "model": "lite",
  "summary": {
    "text": "...",
    "depth": "standard",
    "word_count": 150
  },
  "chapters": [...],
  "identified_elements": {...},
  "metadata": {
    "tokens_used": 15000,
    "processing_time": 342.5,
    "cost_estimate": 0.045,
    "chunk_count": 3
  }
}
```

**Endpoint 4: Combined Analysis** (Rekognition + Nova)
```
POST /analysis/combined
```

Starts both Rekognition and Nova analysis for same video.

### 4.4 UI/UX Integration

**Template: `video_analysis.html`**

Add Nova options section:
```html
<!-- After existing Rekognition checkboxes -->

<div class="analysis-service-section mt-4">
    <h5>AI-Powered Analysis (AWS Nova)</h5>

    <div class="form-check">
        <input type="checkbox" id="useNova" class="form-check-input">
        <label for="useNova" class="form-check-label">
            Enable Nova AI Analysis
            <small class="text-muted">(Summaries, chapters, intelligent insights)</small>
        </label>
    </div>

    <div id="novaOptions" class="mt-3 ms-4" style="display: none;">
        <!-- Model Selection -->
        <div class="mb-3">
            <label class="form-label">Model Quality</label>
            <select id="novaModel" class="form-select">
                <option value="auto">Auto (Recommended)</option>
                <option value="micro">Micro - Fastest, lowest cost</option>
                <option value="lite">Lite - Balanced quality and speed</option>
                <option value="pro">Pro - Highest quality</option>
            </select>
        </div>

        <!-- Analysis Types -->
        <div class="mb-3">
            <label class="form-label">Analysis Types</label>
            <div class="form-check">
                <input type="checkbox" id="novaSummary" class="form-check-input" checked>
                <label for="novaSummary">Video Summary</label>
            </div>
            <div class="form-check">
                <input type="checkbox" id="novaChapters" class="form-check-input" checked>
                <label for="novaChapters">Chapter Detection</label>
            </div>
            <div class="form-check">
                <input type="checkbox" id="novaElements" class="form-check-input">
                <label for="novaElements">Identify Equipment & Topics</label>
            </div>
        </div>

        <!-- Summary Depth -->
        <div class="mb-3">
            <label class="form-label">Summary Detail Level</label>
            <select id="summaryDepth" class="form-select">
                <option value="brief">Brief (2-3 sentences)</option>
                <option value="standard" selected>Standard (1-2 paragraphs)</option>
                <option value="detailed">Detailed (3-5 paragraphs)</option>
            </select>
        </div>
    </div>
</div>

<script>
// Show/hide Nova options
document.getElementById('useNova').addEventListener('change', function(e) {
    document.getElementById('novaOptions').style.display =
        e.target.checked ? 'block' : 'none';
});
</script>
```

**Template: `dashboard.html`**

Add Nova results visualization:
```html
<!-- Nova Summary Card -->
<div class="card mb-4" id="novaSummaryCard" style="display: none;">
    <div class="card-header bg-primary text-white">
        <h5><i class="bi bi-stars"></i> AI Summary (Nova)</h5>
    </div>
    <div class="card-body">
        <p id="novaSummaryText" class="lead"></p>
        <div class="mt-3">
            <span class="badge bg-info">Model: <span id="novaModel"></span></span>
            <span class="badge bg-secondary">Tokens: <span id="novaTokens"></span></span>
        </div>
    </div>
</div>

<!-- Nova Chapters Timeline -->
<div class="card mb-4" id="novaChaptersCard" style="display: none;">
    <div class="card-header bg-success text-white">
        <h5><i class="bi bi-list-ol"></i> Video Chapters</h5>
    </div>
    <div class="card-body">
        <div id="chaptersTimeline" class="chapters-timeline">
            <!-- Dynamically populated with JavaScript -->
        </div>
    </div>
</div>

<!-- Identified Elements Table -->
<div class="card mb-4" id="novaElementsCard" style="display: none;">
    <div class="card-header bg-warning">
        <h5><i class="bi bi-gear"></i> Identified Elements</h5>
    </div>
    <div class="card-body">
        <ul class="nav nav-tabs" role="tablist">
            <li class="nav-item">
                <a class="nav-link active" data-bs-toggle="tab" href="#equipmentTab">Equipment</a>
            </li>
            <li class="nav-item">
                <a class="nav-link" data-bs-toggle="tab" href="#topicsTab">Topics</a>
            </li>
        </ul>
        <div class="tab-content mt-3">
            <div id="equipmentTab" class="tab-pane active">
                <table class="table" id="equipmentTable"></table>
            </div>
            <div id="topicsTab" class="tab-pane">
                <table class="table" id="topicsTable"></table>
            </div>
        </div>
    </div>
</div>
```

**Template: `history.html`**

Add Nova status column:
```html
<table class="table">
    <thead>
        <tr>
            <th>Job ID</th>
            <th>Filename</th>
            <th>Rekognition</th>
            <th>Nova</th>  <!-- New column -->
            <th>Status</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>123</td>
            <td>example.mp4</td>
            <td><span class="badge bg-success">Labels, Faces</span></td>
            <td><span class="badge bg-primary">Summary, Chapters</span></td>
            <td>COMPLETED</td>
            <td>
                <button class="btn btn-sm btn-primary">View Results</button>
            </td>
        </tr>
    </tbody>
</table>
```

### 4.5 Export Format Updates

**Excel Export - New Sheets**:

*Sheet: "Nova Summary"*
| Field | Value |
|-------|-------|
| Model | lite |
| Summary | [full text] |
| Word Count | 150 |
| Tokens Used | 15000 |
| Processing Time | 342.5s |
| Cost | $0.045 |

*Sheet: "Chapters"*
| # | Title | Start | End | Duration | Summary |
|---|-------|-------|-----|----------|---------|
| 1 | Introduction | 0:00 | 0:45 | 0:45 | ... |
| 2 | Main Content | 0:45 | 5:30 | 4:45 | ... |

*Sheet: "Identified Elements"*
| Type | Name | Category | First Seen | Last Seen | Discussed |
|------|------|----------|------------|-----------|-----------|
| Equipment | DSLR Camera | Photography | 0:30 | 5:00 | Yes |
| Topic | Portrait Photography | Discussion | 1:00 | 4:30 | - |

**JSON Export - Updated Schema**:
```json
{
  "job_id": 123,
  "rekognition_results": {...},
  "nova_results": {
    "model": "lite",
    "summary": {...},
    "chapters": [...],
    "identified_elements": {...},
    "metadata": {...}
  }
}
```

## 5. Cost & Performance Considerations

### 5.1 Cost Estimates

**Pricing Model** (Based on AWS Bedrock Nova pricing):
- Nova Micro: $[X] per 1000 input tokens, $[Y] per 1000 output tokens
- Nova Lite: $[X] per 1000 input tokens, $[Y] per 1000 output tokens
- Nova Pro: $[X] per 1000 input tokens, $[Y] per 1000 output tokens

**Per-Video Cost Estimates**:

| Video Length | Model | Estimated Tokens | Estimated Cost |
|--------------|-------|------------------|----------------|
| 5 minutes | Micro | ~[X] | $[Y] |
| 5 minutes | Lite | ~[X] | $[Y] |
| 5 minutes | Pro | ~[X] | $[Y] |
| 30 minutes | Micro | ~[X] | $[Y] |
| 30 minutes | Lite | ~[X] | $[Y] |
| 30 minutes | Pro | ~[X] | $[Y] |
| 2 hours | Micro | ~[X] | $[Y] |
| 2 hours | Lite | ~[X] | $[Y] |
| 2 hours | Pro | ~[X] | $[Y] |

**Model Cost Trade-offs**:
- **Micro**: Best for quick previews, batch processing, cost-sensitive applications
- **Lite**: Best for most use cases - balanced quality and cost
- **Pro**: Best for critical content, detailed analysis, professional use

**Optimization Tips**:
1. Use auto model selection based on video duration
2. Cache summaries to avoid reprocessing
3. Process only requested analysis types (don't run all by default)
4. Use Micro for initial preview, upgrade to Pro if needed
5. Batch process multiple short videos together

### 5.2 Performance Expectations

**Processing Times** (Estimated):

| Video Length | Model | Processing Time | Realtime Factor |
|--------------|-------|-----------------|-----------------|
| 5 minutes | Micro | ~[X]s | [Y]x |
| 5 minutes | Lite | ~[X]s | [Y]x |
| 5 minutes | Pro | ~[X]s | [Y]x |
| 30 minutes | Micro | ~[X]s | [Y]x |
| 30 minutes | Lite | ~[X]s | [Y]x |
| 30 minutes | Pro | ~[X]s | [Y]x |

**Async Processing**:
Nova requires async processing similar to Rekognition:
1. Submit job to queue
2. Poll status every 15-30 seconds
3. Retrieve results when complete

**User Expectations**:
- Short videos (< 5 min): Results in 1-2 minutes
- Medium videos (5-30 min): Results in 3-10 minutes
- Long videos (> 30 min): Results in 10-30 minutes
- Display progress bar with chunk completion status
- Show estimated time remaining

## 6. Implementation Phases

### Phase 1: Foundation (Core Nova Integration)
**Goal**: Basic Nova integration with single-chunk videos

**Tasks**:
- Set up IAM permissions for Bedrock access
- Implement `nova_service.py` with basic invoke function
- Add `nova_jobs` table to database
- Create `/nova/analyze` endpoint
- Test with short videos (< 5 minutes)

**Files to Create**:
- `app/services/nova_service.py` (new)
- `app/routes/nova_analysis.py` (new)
- `migrations/add_nova_jobs_table.sql` (new)

**Files to Modify**:
- `app/__init__.py` - Register nova_analysis blueprint
- `app/database.py` - Add nova_jobs CRUD functions
- `requirements.txt` - Add boto3 bedrock dependencies

**Success Criteria**:
- Can analyze videos < 5 minutes with Nova
- Results stored in database
- Basic summary generation works

**Estimated Effort**: [Based on your assessment]

### Phase 2: Chunking & Long Video Support
**Goal**: Handle videos of any length via chunking

**Tasks**:
- Implement video chunking algorithm
- Build result aggregation logic (from section 3.3)
- Add FFmpeg integration for video segmentation
- Test with 30-minute and 2-hour videos
- Implement progress tracking for multi-chunk jobs

**Files to Create**:
- `app/services/video_chunker.py` (new)
- `app/services/nova_aggregator.py` (new)

**Files to Modify**:
- `app/services/nova_service.py` - Add chunking logic
- `app/routes/nova_analysis.py` - Add chunk progress to status endpoint

**Success Criteria**:
- Successfully process 2-hour videos
- Aggregated results are coherent
- Progress tracking shows chunk completion

**Estimated Effort**: [Based on your assessment]

### Phase 3: Chapter Detection & Element Identification
**Goal**: Full feature implementation

**Tasks**:
- Implement chapter detection
- Add equipment/object identification
- Add topic extraction
- Enhance prompt engineering for each feature
- Test accuracy with diverse video types

**Files to Modify**:
- `app/services/nova_service.py` - Add prompt templates
- `app/database.py` - Update schema for chapters and elements

**Success Criteria**:
- Accurate chapter detection
- Relevant equipment identification
- Topic extraction works well

**Estimated Effort**: [Based on your assessment]

### Phase 4: UI/UX Integration
**Goal**: Full user interface integration

**Tasks**:
- Update `video_analysis.html` with Nova options
- Create Nova dashboard visualizations
- Add Nova results to `history.html`
- Implement Excel/JSON export with Nova data
- Add comparison view (Rekognition vs Nova)
- User testing and refinement

**Files to Modify**:
- `app/templates/video_analysis.html`
- `app/templates/dashboard.html`
- `app/templates/history.html`
- `app/static/js/dashboard.js` - Add Nova visualization code
- `app/routes/analysis.py` - Add Excel export for Nova

**Success Criteria**:
- Intuitive UI for selecting Nova options
- Beautiful visualization of results
- Export functionality works

**Estimated Effort**: [Based on your assessment]

### Phase 5: Polish & Optimization
**Goal**: Production-ready implementation

**Tasks**:
- Performance optimization (caching, parallel chunk processing)
- Cost optimization (smart model selection)
- Comprehensive error handling
- Add logging and monitoring
- Documentation (API docs, user guide)
- Security review

**Files to Modify**:
- All service files - Add caching
- All route files - Enhance error handling
- Add logging throughout

**Success Criteria**:
- < 2% error rate in production
- Average cost per video meets targets
- Full documentation complete

**Estimated Effort**: [Based on your assessment]

---

*End of Part 2. Part 3 will cover testing strategy, risks, and appendices (sections 7-10).*
```
</deliverable>

<success_criteria>
Before completing, verify:

1. ✓ Sections 3-6 appended to existing `./20251218NovaImplementation.md`
2. ✓ Chunking algorithm has detailed pseudocode with full implementation
3. ✓ Database schema specifies exact field names, types, and purposes
4. ✓ All function signatures are complete and well-documented
5. ✓ API endpoint schemas show full request/response examples
6. ✓ UI/UX section has actual HTML/JavaScript code snippets
7. ✓ Cost table has specific estimates (research actual pricing)
8. ✓ Each implementation phase lists specific files to create/modify
9. ✓ Part 2 content is 3,000-5,000 words
10. ✓ Clear note at end: "Part 3 will cover testing, risks, appendices"
</success_criteria>

<constraints>
- APPEND to existing file, do not overwrite
- Read existing content first to ensure continuity
- NO CODE IMPLEMENTATION - only update the plan document
- Research actual AWS Bedrock pricing for cost estimates
- Be specific in all technical details
</constraints>

<output>
Append to: `./20251218NovaImplementation.md` (Part 2 sections)
</output>
