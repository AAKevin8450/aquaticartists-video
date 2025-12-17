# Project-Specific Instructions for Claude Code

## Project Overview
AWS Video & Image Analysis Application - Flask-based web application for analyzing videos and images using Amazon Rekognition. Supports 8 video analysis types, 8 image analysis types, face collection management, and comprehensive file upload/history tracking.

## AWS Configuration

### Current Setup
- **S3 Bucket**: video-analysis-app-676206912644 (us-east-1)
- **IAM Policy**: VideoAnalysisAppPolicy
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
- IAM policy follows principle of least privilege

## Important Constraints
- Video files: Max 10GB, formats: MP4, MOV, AVI, MKV
- Image files: Max 15MB, formats: JPEG, PNG
- Rekognition available in us-east-1 region
- CORS configured only for localhost:5700 (update for production)
