# Project-Specific Instructions for Claude Code

## Project Overview
AWS Video & Image Analysis Application - Flask-based web application for analyzing videos and images using Amazon Rekognition. Supports 8 video analysis types, 8 image analysis types, face collection management, and comprehensive file upload/history tracking.

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
5. **Analysis API** (app/routes/analysis.py) - Multi-select analysis endpoint (supports arrays of analysis types)

### Frontend Components
**Templates** (app/templates/):
- index.html - Landing page with feature overview
- upload.html - File upload with real-time progress tracking (XMLHttpRequest) and presigned URL support
- video_analysis.html - Multi-select analysis types (checkboxes) with job status tracking
- image_analysis.html - Multi-select analysis types (checkboxes) with aggregated results display
- collections.html - Face collection management interface
- history.html - Job history with auto-load and download buttons for completed jobs
- base.html - Base template with navigation and common layout

**Static Assets**:
- app/static/css/style.css - Application-wide styling with Bootstrap 5 integration
- app/static/js/utils.js - Shared JavaScript utilities for AJAX and API interactions

**Key Features**:
- Multi-select analysis: Users can select 1-8 analysis types simultaneously (checkboxes replace radio buttons)
- Real-time upload progress: XMLHttpRequest provides smooth 0-100% progress updates
- Automatic timezone conversion: All timestamps display in Eastern Time (ET) with zoneinfo/tzdata
- Download results: Excel (.xlsx) or JSON download for completed jobs with dropdown buttons
- Auto-polling: History page automatically polls running jobs every 15 seconds until completion
- Excel export: Professional formatted Excel files with Summary and Data sheets using openpyxl

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

## Important Constraints
- Video files: Max 10GB, formats: MP4, MOV, AVI, MKV
- Image files: Max 15MB, formats: JPEG, PNG
- Rekognition available in us-east-1 region
- CORS configured for localhost:5700 and 127.0.0.1:5700 (update for production)
- Timezone display: Eastern Time (requires tzdata package on Windows)
