# AWS Video & Image Analysis Application

A Flask-based web application for analyzing videos and images using **Amazon Rekognition**. Supports 8 video analysis types, 8 image analysis types, face collection management, and comprehensive file upload/history tracking.

## Features

### Video Analysis (Async)
- Label Detection - Detect objects, activities, and scenes
- Face Detection - Detect faces with detailed attributes
- Celebrity Recognition - Identify celebrities
- Content Moderation - Detect unsafe content
- Text Detection (OCR) - Extract text from video
- Segment Detection - Detect shots and technical cues
- Person Tracking - Track people throughout video
- Face Search - Search for known faces in collections

### Image Analysis (Sync)
- Label Detection - Detect objects and scenes
- Face Detection - Detect faces with attributes
- Face Comparison - Compare faces between images
- Celebrity Recognition - Identify celebrities
- Content Moderation - Detect unsafe content
- Text Detection (OCR) - Extract text from images
- PPE Detection - Detect protective equipment
- Custom Labels - Use custom-trained models

### Additional Features
- Direct browser-to-S3 uploads via presigned POST URLs
- Face collection management (create, delete, search)
- Job history with status tracking
- Real-time job polling with exponential backoff
- SQLite database for metadata storage

## Installation

### Prerequisites
- Python 3.12+ (tested with 3.12.10)
- AWS account with Rekognition and S3 access
- S3 bucket configured
- IAM credentials with proper permissions

### Setup Instructions

1. **Clone and navigate to the project**:
   ```bash
   cd E:\coding\video
   ```

2. **Activate virtual environment** (already exists):
   ```bash
   .\.venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure AWS credentials**:
   Edit `.env` file and add your AWS credentials:
   ```
   AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
   AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   AWS_REGION=us-east-1
   S3_BUCKET_NAME=your-video-analysis-bucket
   FLASK_SECRET_KEY=your-secret-key-here
   ```

5. **Configure S3 bucket CORS** (for browser uploads):
   Add this CORS configuration to your S3 bucket:
   ```json
   [
     {
       "AllowedHeaders": ["*"],
       "AllowedMethods": ["GET", "POST", "PUT"],
       "AllowedOrigins": ["http://localhost:5700"],
       "ExposeHeaders": ["ETag"]
     }
   ]
   ```

6. **Run the application**:
   ```bash
   python run.py
   ```

7. **Access the application**:
   Open your browser to http://localhost:5700

## Project Structure

```
video/
├── app/
│   ├── routes/           # API endpoints and page routes
│   ├── services/         # AWS service integrations
│   ├── utils/            # Validators and formatters
│   ├── templates/        # HTML templates
│   ├── static/           # CSS, JS, uploads
│   ├── config.py         # Configuration management
│   ├── database.py       # SQLite database layer
│   └── models.py         # Data models
├── data/                 # SQLite database storage
├── tests/                # Unit and integration tests
├── .env                  # Environment variables (NOT in git)
├── run.py                # Application entry point
└── requirements.txt      # Python dependencies
```

## Usage

### Uploading Files
1. Navigate to Upload page
2. Drag-and-drop files or click to select
3. Files upload directly to S3 via presigned URLs
4. View uploaded files in the file list

### Analyzing Videos
1. Go to Video Analysis page
2. Select a video from the dropdown
3. Choose analysis type (Labels, Faces, etc.)
4. Configure options (min confidence, etc.)
5. Click "Start Analysis"
6. Monitor job status with automatic polling
7. View results when complete

### Analyzing Images
1. Go to Image Analysis page
2. Select an image from the dropdown
3. Choose analysis type
4. Configure options
5. Click "Analyze"
6. View immediate results

### Managing Face Collections
1. Go to Face Collections page
2. Create a new collection
3. Add faces from uploaded images
4. Search for faces in videos/images
5. Manage collection members

### Viewing History
1. Go to History page
2. View all past analysis jobs
3. Filter by status or file
4. View detailed results
5. Re-analyze or delete jobs

## AWS Configuration

### Required IAM Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket-name",
        "arn:aws:s3:::your-bucket-name/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["rekognition:*"],
      "Resource": "*"
    }
  ]
}
```

## API Endpoints

See `docs/API.md` for complete API documentation.

### Upload Endpoints
- `POST /api/upload/presigned-url` - Get presigned POST URL
- `POST /api/upload/complete` - Complete upload
- `GET /api/files` - List files
- `DELETE /api/files/<id>` - Delete file

### Video Analysis Endpoints
- `POST /api/video/labels/start` - Start label detection
- `POST /api/video/faces/start` - Start face detection
- `GET /api/video/job/<job_id>/status` - Check job status

### Image Analysis Endpoints
- `POST /api/image/labels` - Detect labels
- `POST /api/image/faces` - Detect faces
- `POST /api/image/face-compare` - Compare faces

See documentation for all endpoints.

## Development

### Running Tests
```bash
pytest
```

### Adding New Analysis Types
See `docs/DEVELOPMENT.md` for guidelines.

## Troubleshooting

### AWS Credentials Not Found
- Verify `.env` file exists and contains valid credentials
- Check environment variables are loaded

### S3 Upload Fails
- Verify S3 bucket CORS configuration
- Check IAM permissions for S3
- Ensure bucket exists and is accessible

### Rekognition Errors
- Verify IAM permissions for Rekognition
- Check supported file formats (MP4, MOV for video; JPEG, PNG for images)
- Ensure files don't exceed size limits (video: 10GB, image: 15MB)

### Database Errors
- Check `data/` directory exists and is writable
- Delete `data/app.db` to reset database
- Check SQLite version (3.8.3+)

## License

This project is provided as-is for educational and commercial use.

## Support

For issues and questions:
- Check `docs/AWS_SETUP.md` for AWS configuration help
- Review `docs/DEVELOPMENT.md` for development guidelines
- Check application logs for error details
