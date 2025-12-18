# Project-Specific Instructions for Claude Code

## Project Overview
AWS Video & Image Analysis Application - Flask-based web application for analyzing videos and images using Amazon Rekognition. Supports 8 video analysis types, 8 image analysis types, face collection management, local video transcription, and comprehensive file upload/history tracking.

## AWS Configuration

### Current Setup
- **S3 Bucket**: video-analysis-app-676206912644 (us-east-1)
- **IAM Policy**: VideoAnalysisAppPolicy (v2 - explicit permissions)
- **CORS**: Configured for localhost:5700 browser uploads
- **Services**: S3, Amazon Rekognition

### Environment Variables (.env)
Critical environment variables are stored in .env file (not in git):
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_REGION=us-east-1
- S3_BUCKET_NAME=video-analysis-app-676206912644
- FLASK_SECRET_KEY (generated)
- DATABASE_PATH=data/app.db

## Development Guidelines

### Application Architecture
- Port: 5700 (Flask development server)
- Virtual Environment: .venv (already configured)
- Database: SQLite (data/app.db)
- File Storage: AWS S3 (direct browser uploads via presigned URLs)
- Analysis Engine: Amazon Rekognition (async for video, sync for images)

### Key Services
1. **S3 Service** (app/services/s3_service.py) - Handles file upload/download
2. **Rekognition Video** (app/services/rekognition_video.py) - Async video analysis
3. **Rekognition Image** (app/services/rekognition_image.py) - Sync image analysis
4. **Face Collections** (app/services/face_collection_service.py) - Face management
5. **Transcription Service** (app/services/transcription_service.py) - Local video transcription using faster-whisper
6. **Analysis API** (app/routes/analysis.py) - Multi-select analysis endpoint (supports arrays of analysis types)

### Frontend Components
**Templates** (app/templates/):
- index.html - Landing page with feature overview
- upload.html - File upload with real-time progress tracking (XMLHttpRequest) and presigned URL support
- video_analysis.html - Multi-select analysis types (checkboxes) with job status tracking
- image_analysis.html - Multi-select analysis types (checkboxes) with aggregated results display
- collections.html - Face collection management interface
- transcription.html - Local video transcription interface with directory scanning and batch processing
- history.html - Job history with auto-load and download buttons for completed jobs
- dashboard.html - Visual analytics dashboard with charts and insights for video analysis results
- base.html - Base template with navigation and common layout

**Static Assets**:
- app/static/css/style.css - Application-wide styling with Bootstrap 5 integration
- app/static/js/utils.js - Shared JavaScript utilities for AJAX and API interactions
- app/static/js/dashboard.js - Dashboard functionality with Chart.js visualizations and data processors

**Key Features**:
- Multi-select analysis: Users can select 1-8 analysis types simultaneously (checkboxes replace radio buttons)
- Real-time upload progress: XMLHttpRequest provides smooth 0-100% progress updates
- Automatic timezone conversion: All timestamps display in Eastern Time (ET) with zoneinfo/tzdata
- Download results: Excel (.xlsx) or JSON download for completed jobs with dropdown buttons
- Auto-polling: History page automatically polls running jobs every 15 seconds until completion
- Excel export: Professional formatted Excel files with Summary and Data sheets using openpyxl
- Visual dashboard: Interactive charts, graphs, and insights for video analysis results (accessible via /dashboard/<job_id>)

### Running the Application
```bash
cd E:\coding\video
.\.venv\Scripts\activate
python run.py
# Access at http://localhost:5700
```

### Testing AWS Configuration
- S3 bucket access via AWS CLI
- Rekognition API connectivity
- CORS configuration for browser uploads

## Security Notes
- Never commit .env file to git
- S3 bucket has no public access
- Use presigned URLs with short expiration for uploads
- IAM policy v2 uses explicit permissions (31 specific Rekognition actions) instead of wildcard
- Policy follows principle of least privilege with granular action permissions
- S3 CORS updated to support all headers (*) and methods (GET, POST, PUT, DELETE, HEAD) for localhost:5700 and 127.0.0.1:5700

## Known Issues
- **Amazon Rekognition Person Tracking**: Returns AccessDeniedException despite correct IAM permissions. This appears to be an AWS account-level restriction requiring AWS Support enablement. All other video analysis types (labels, faces, celebrities, moderation, text, segments, face search) work correctly.

## Recent Bug Fixes (2025-12-17)
- **Segment Detection VideoMetadata Bug**: Fixed critical bug where Amazon Rekognition returns VideoMetadata as a list for segment detection (instead of dict like other analysis types). Added type checking to handle both formats safely.
- **Collections Page JavaScript Error**: Fixed undefined collections.length error by properly extracting data.collections array from API response wrapper.
- **History Auto-Refresh**: Added automatic 15-second polling for running jobs (IN_PROGRESS/SUBMITTED status) with automatic start/stop based on job states.
- **Excel Export**: Implemented professional Excel export functionality with openpyxl library, supporting all analysis types with custom formatting per type.

## Local Video Transcription Feature

### Overview
Completely local video transcription system using faster-whisper (CTranslate2-based Whisper implementation). No data is sent to cloud services. Designed for processing large video libraries (~10TB+) with efficient batch processing and deduplication.

### System Requirements
- **FFmpeg**: Must be installed and accessible in PATH (required for audio extraction)
- **Python Dependencies**: faster-whisper>=1.0.0, ffmpeg-python>=0.2.0
- **Optional**: CUDA-capable GPU for 4x faster processing (auto-detected)

### Key Features
1. **Directory Scanning**: Recursively scan directories for video files with deduplication
2. **Batch Processing**: Process multiple files with progress tracking, resumable operations, and real-time statistics
3. **Multi-Model Support**: Store multiple transcripts per video (same file transcribed with different Whisper models)
4. **Smart Deduplication**: Filesystem metadata (path + size + modified time + model) for instant identification
5. **Model Selection**: 6 model sizes (tiny, base, small, medium, large-v2, large-v3)
6. **GPU Acceleration**: Automatic CUDA detection and utilization when available
7. **Multiple Export Formats**: TXT, JSON, SRT (SubRip), VTT (WebVTT)
8. **Database Storage**: Full transcripts with word-level timestamps stored in SQLite
9. **Language Support**: Auto-detection or specify language (100+ languages supported)
10. **Search & Filter**: Full-text search across transcripts with filters by model, status, language, date range
11. **Enhanced Progress UI**: Solid completion bar, real-time statistics (dual avg size metrics, avg time, ETA, success rate)
12. **Transcript Metrics**: Duration tracking, character/word counts, processing speed (Xrealtime), words per minute

### Database Schema (Redesigned 2025-12-18)
**transcripts** table (19 fields, no legacy fields):
- **Identity**: file_path, file_name, file_size, modified_time, model_name
- **Transcript Data**: language, transcript_text, segments (JSON), word_timestamps (JSON)
- **Content Metrics**: character_count, word_count, duration_seconds (all nullable, NULL for videos without speech)
- **Quality Metrics**: confidence_score, processing_time
- **Status Tracking**: status, error_message, created_at, completed_at
- **Unique Constraint**: (file_path, file_size, modified_time, model_name) - allows multi-model storage
- **Indexes**: model_name, language, file_name (for search/filter performance)

### Architecture
- **Service Layer** (app/services/transcription_service.py): Core transcription logic with model caching
- **Routes** (app/routes/transcription.py): RESTful API endpoints for scanning, batch processing, status tracking
- **UI** (app/templates/transcription.html): Bootstrap 5 interface with real-time progress updates
- **Database** (app/database.py): CRUD operations for transcript records with JSON field handling

### API Endpoints
- POST `/transcription/api/scan` - Scan directory for videos
- POST `/transcription/api/transcribe-single` - Transcribe single file
- POST `/transcription/api/start-batch` - Start batch transcription job
- GET `/transcription/api/batch-status/<job_id>` - Get batch progress
- POST `/transcription/api/batch-cancel/<job_id>` - Cancel running batch
- GET `/transcription/api/transcripts` - List transcripts (supports search/filter/sort/pagination)
  - Query params: ?search, ?status, ?model, ?language, ?from_date, ?to_date, ?sort_by, ?sort_order, ?page, ?per_page
- GET `/transcription/api/transcript/<id>` - Get single transcript
- DELETE `/transcription/api/transcript/<id>` - Delete transcript
- GET `/transcription/api/transcript/<id>/download?format=txt|json|srt|vtt` - Download transcript

### Performance Considerations
- **Model Loading**: Model loaded once and cached in memory for batch operations
- **Audio Extraction**: Temporary WAV files (16kHz mono) auto-cleaned after processing
- **Concurrent Processing**: Single-threaded batch processing (safer for large models)
- **Memory Usage**: Depends on model size (tiny: ~1GB RAM, large-v3: ~10GB VRAM/RAM)
- **Processing Speed**:
  - GPU (CUDA): ~5-10x realtime (1 hour video = 6-12 minutes)
  - CPU: ~1-2x realtime (1 hour video = 30-60 minutes)

### Best Practices
1. **Model Selection**: Use 'medium' for balanced quality/speed, 'large-v3' for best accuracy
2. **Multi-Model Comparison**: Transcribe same video with different models to compare accuracy vs speed tradeoffs
3. **GPU Usage**: Ensure CUDA toolkit installed for GPU acceleration
4. **Batch Size**: Process 10-50 files per batch for optimal progress tracking
5. **Force Reprocess**: Use sparingly - system automatically skips transcribed files per model
6. **Search & Filter**: Use search for finding specific content, filters for narrowing by model/status/language
7. **Error Handling**: Check batch errors list for failed files and reasons
8. **Network Performance**: Optimized for network shares - uses instant filesystem metadata (no file reading during scan)

### Workflow Example
```python
# 1. Scan directory
POST /transcription/api/scan
{
  "directory_path": "E:\\videos",
  "recursive": true
}

# 2. Start batch transcription
POST /transcription/api/start-batch
{
  "file_paths": ["E:\\videos\\movie1.mp4", "E:\\videos\\movie2.mp4"],
  "language": "en",  # optional
  "force": false
}

# 3. Poll status every 2-5 seconds
GET /transcription/api/batch-status/<job_id>

# 4. Download completed transcripts
GET /transcription/api/transcript/1/download?format=srt
```

### Troubleshooting
- **FFmpeg not found**: Install FFmpeg and add to PATH, or specify path in system environment
- **CUDA not available**: Install NVIDIA CUDA Toolkit (11.x or 12.x) for GPU support
- **Out of memory**: Use smaller model size (medium or small) or CPU device
- **Slow processing**: Ensure GPU acceleration is working (check logs for device: cuda)
- **Files skipped**: System prevents reprocessing same video with same model (use different model or force flag)
- **Database errors**: Database was recreated 2025-12-18 - old data/app.db deleted, fresh schema created

## Video Analysis Dashboard Feature

### Overview
Visual analytics dashboard that transforms raw AWS Rekognition JSON results into interactive charts, graphs, and insights. Provides professional presentation of video analysis results with analysis-type-specific visualizations.

### Access
- **URL Pattern**: `/dashboard/<job_id>`
- **Navigation**: Click "View" button (graph icon) next to completed jobs in history page
- **Raw JSON Access**: Click "JSON" button (code icon) to view raw JSON in modal

### Dashboard Components

**1. Statistics Cards**
- Total Detections: Count of all detected items
- Average Confidence: Mean confidence score across all detections
- Video Duration: Extracted from VideoMetadata (handles dict/list formats)
- Processing Time: Analysis job duration

**2. Top Detected Items**
- Analysis-type-specific top 10 items
- Visual confidence bars with percentages
- Color-coded by confidence level

**3. Interactive Charts (Chart.js 4.4.0)**
- **Distribution Chart** (Bar): Frequency of detected items by category
- **Confidence Chart** (Doughnut): Confidence ranges or category breakdown
- **Timeline Chart** (Line): Detection frequency over video duration with bucketing

**4. Detailed Results Table**
- Dynamic columns based on analysis type
- Search functionality across all fields
- Sort by confidence (descending) or timestamp (ascending)
- Shows "Displaying X of Y results" count

**5. Export Options**
- Excel (.xlsx): Professional formatted spreadsheet
- JSON: Raw analysis results

### Analysis Type Support

| Analysis Type | Dashboard Features |
|--------------|-------------------|
| Label Detection | Top labels by count, category aggregation, temporal distribution |
| Face Detection | Emotion distribution, age groups (0-100), gender statistics |
| Celebrity Recognition | Celebrity names with Wikipedia URLs and confidence scores |
| Text Detection | OCR text categorized by type (LINE/WORD) |
| Content Moderation | Flagged content grouped by parent category |
| Person Tracking | Person indices with appearance counts |
| Segment Detection | Scene/shot breakdown with timestamps and durations |
| Face Search | Face matches with similarity percentages |

### Technical Architecture

**Backend**:
- Route: `app/routes/dashboard.py`
- Blueprint: Renders dashboard template with job data
- API: Reuses existing `/api/history/<job_id>` endpoint

**Frontend**:
- Template: `app/templates/dashboard.html` (416 lines)
- JavaScript: `app/static/js/dashboard.js` (927 lines, ES6 modules)
- Charts: Chart.js 4.4.0 via CDN
- No jQuery dependency (vanilla JavaScript)

**Data Processing**:
- Client-side processing with modular processor functions
- 9 data processors (one per analysis type + generic fallback)
- Timeline bucketing: Divides video into 20 time segments for smooth visualization
- XSS prevention with escapeHtml() function

**Design**:
- Purple gradient header (#667eea to #764ba2)
- Bootstrap 5 responsive grid layout
- Desktop: Multi-column layout
- Tablet: 2-column layout
- Mobile: Single-column with collapsible sections

### Best Practices
1. **Use dashboard for presentations**: Professional charts suitable for reports
2. **Use JSON view for debugging**: Raw data access for technical troubleshooting
3. **Search table for specific items**: Find particular detections quickly
4. **Export to Excel for analysis**: Further analysis in spreadsheet software
5. **Timeline chart shows patterns**: Identify when events occur in video

## Important Constraints
- Video files: Max 10GB, formats: MP4, MOV, AVI, MKV
- Image files: Max 15MB, formats: JPEG, PNG
- Rekognition available in us-east-1 region
- CORS configured for localhost:5700 and 127.0.0.1:5700 (update for production)
- Timezone display: Eastern Time (requires tzdata package on Windows)
- **Transcription**: Requires FFmpeg installed on system, GPU optional but recommended for large batches
