# AWS Video & Image Analysis Application - Detailed Plan

## Overview

A Flask-based web application that enables users to upload videos and images to AWS S3, process them using Amazon Rekognition, and view analysis results through an intuitive frontend interface.

**Tech Stack:**
- Backend: Python 3.x + Flask (port 5700)
- Frontend: HTML5, CSS3 (Bootstrap 5), JavaScript
- Cloud Services: AWS S3, Amazon Rekognition, (optional) SNS for notifications
- Virtual Environment: `./.venv`

---

## Project Structure

```
video/
├── .venv/                      # Python virtual environment
├── app/
│   ├── __init__.py            # Flask app factory
│   ├── config.py              # Configuration management
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── main.py            # Main routes (index, dashboard)
│   │   ├── upload.py          # Upload handling routes
│   │   ├── video_analysis.py  # Video analysis routes
│   │   └── image_analysis.py  # Image analysis routes
│   ├── services/
│   │   ├── __init__.py
│   │   ├── s3_service.py      # S3 upload/management
│   │   ├── rekognition_video.py   # Video analysis service
│   │   └── rekognition_image.py   # Image analysis service
│   ├── static/
│   │   ├── css/
│   │   │   └── style.css      # Custom styles
│   │   └── js/
│   │       ├── upload.js      # Upload handling
│   │       ├── video.js       # Video analysis UI
│   │       └── image.js       # Image analysis UI
│   └── templates/
│       ├── base.html          # Base template with navigation
│       ├── index.html         # Home/Dashboard
│       ├── upload.html        # Upload interface
│       ├── video_analysis.html    # Video analysis options & results
│       ├── image_analysis.html    # Image analysis options & results
│       └── results/
│           ├── labels.html        # Label detection results
│           ├── faces.html         # Face analysis results
│           ├── celebrities.html   # Celebrity recognition results
│           ├── moderation.html    # Content moderation results
│           ├── text.html          # Text detection results
│           └── segments.html      # Video segment results
├── uploads/                   # Temporary local uploads (before S3)
├── .env                       # Environment variables (AWS credentials)
├── .gitignore
├── requirements.txt           # Python dependencies
├── run.py                     # Application entry point
└── program_plan.md           # This file
```

---

## Dependencies (requirements.txt)

```
flask>=3.0.0
boto3>=1.34.0
python-dotenv>=1.0.0
werkzeug>=3.0.0
gunicorn>=21.0.0
```

---

## AWS Configuration

### Required AWS Services
1. **S3 Bucket** - Store uploaded videos and images
2. **Amazon Rekognition** - Video and image analysis
3. **IAM Role/User** - With permissions for S3 and Rekognition
4. **(Optional) SNS Topic** - For async job completion notifications

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
            "Action": [
                "rekognition:*"
            ],
            "Resource": "*"
        }
    ]
}
```

### Environment Variables (.env)
```
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
S3_BUCKET_NAME=your-video-analysis-bucket
SNS_TOPIC_ARN=arn:aws:sns:region:account:topic (optional)
REKOGNITION_ROLE_ARN=arn:aws:iam::account:role/rekognition-role (optional, for SNS)
FLASK_SECRET_KEY=your_secret_key_here
```

---

## Feature Specifications

### 1. File Upload System

#### Frontend Features
- Drag-and-drop upload zone
- File type validation (video: mp4, mov, avi, mkv; image: jpg, jpeg, png, gif)
- File size display and validation (max 10GB for video, 15MB for image)
- Upload progress bar with percentage
- Multiple file upload support
- Preview thumbnails for images
- Cancel upload option

#### Backend Implementation
- Chunked upload support for large files
- Direct-to-S3 upload using presigned URLs (recommended for large files)
- Temporary local storage option for smaller files
- File metadata extraction
- Duplicate detection (optional)

#### API Endpoints
```
POST /api/upload/presigned-url    # Get presigned URL for direct S3 upload
POST /api/upload/file             # Upload file through server
GET  /api/files                   # List uploaded files
DELETE /api/files/<file_id>       # Delete a file
```

---

### 2. Video Analysis Features

Amazon Rekognition Video provides asynchronous analysis. Each operation starts a job and returns a `JobId` for status polling.

#### 2.1 Label Detection
**Purpose:** Detect objects, activities, and scenes in video

**Options to expose:**
- `MinConfidence` (0-100, default 50) - Minimum confidence threshold
- `MaxLabels` - Maximum number of labels to return
- Feature filters (categories to include/exclude)

**Results display:**
- Timeline visualization of detected labels
- Confidence scores
- Bounding boxes for objects (when available)
- Parent/child label hierarchy
- Timestamp-based navigation

#### 2.2 Face Detection & Analysis
**Purpose:** Detect faces and analyze attributes

**Options to expose:**
- Face attributes to analyze:
  - Age range
  - Gender
  - Emotions (Happy, Sad, Angry, Confused, Disgusted, Surprised, Calm, Fear)
  - Smile detection
  - Eyeglasses/Sunglasses
  - Eyes open/closed
  - Mouth open/closed
  - Beard/Mustache
  - Face quality (brightness, sharpness)
  - Pose (pitch, roll, yaw)

**Results display:**
- Face thumbnails with timestamps
- Attribute cards for each face
- Emotion charts/graphs
- Face tracking timeline
- Bounding box visualization on video frames

#### 2.3 Face Search (Collection-based)
**Purpose:** Search for known faces in video against a face collection

**Options to expose:**
- Face collection selection (dropdown of existing collections)
- Create new collection option
- `FaceMatchThreshold` (0-100, default 80)
- `MaxFaces` - Maximum faces to return per detection

**Prerequisites:**
- Face collection management interface
- Add faces to collection from images
- Collection CRUD operations

**Results display:**
- Matched faces with similarity scores
- External image ID associations
- Timeline of appearances

#### 2.4 Person Tracking
**Purpose:** Track people throughout the video

**Results display:**
- Person index assignments
- Tracking paths visualization
- Entry/exit timestamps
- Bounding box sequences

#### 2.5 Celebrity Recognition
**Purpose:** Identify celebrities in video

**Options to expose:**
- No specific options (uses default settings)

**Results display:**
- Celebrity names with confidence
- URLs to additional information
- Known for/profession details
- Appearance timeline
- Face bounding boxes

#### 2.6 Content Moderation
**Purpose:** Detect unsafe or inappropriate content

**Options to expose:**
- `MinConfidence` (0-100, default 50)
- Categories to check:
  - Explicit Nudity
  - Suggestive
  - Violence
  - Visually Disturbing
  - Rude Gestures
  - Drugs
  - Tobacco
  - Alcohol
  - Gambling
  - Hate Symbols

**Results display:**
- Flagged segments with timestamps
- Category and confidence levels
- Parent/child label hierarchy
- Timeline markers for problematic content
- Export report option

#### 2.7 Text Detection (OCR)
**Purpose:** Detect and extract text from video frames

**Options to expose:**
- `Filters.WordFilter.MinConfidence`
- `Filters.WordFilter.MinBoundingBoxWidth`
- `Filters.WordFilter.MinBoundingBoxHeight`
- Region of interest filters

**Results display:**
- Detected text strings
- Timestamps and duration
- Bounding box visualization
- Text type (LINE vs WORD)
- Confidence scores

#### 2.8 Segment Detection
**Purpose:** Detect technical cues and shot boundaries

**Options to expose:**
- Segment types to detect:
  - `TECHNICAL_CUE` (black frames, color bars, end credits, opening credits, studio logo, slate)
  - `SHOT` (shot change detection)
- `MinSegmentConfidence`

**Results display:**
- Shot boundary timeline
- Technical cue markers
- Segment duration information
- Start/end frame thumbnails
- Color bar detection
- Credits detection

---

### 3. Image Analysis Features

Amazon Rekognition Image provides synchronous analysis (immediate results).

#### 3.1 Label Detection
**Purpose:** Detect objects and scenes in images

**Options to expose:**
- `MaxLabels` (1-1000)
- `MinConfidence` (0-100)
- Feature settings:
  - General labels
  - Image properties (dominant colors, quality, etc.)

**Results display:**
- Label list with confidence bars
- Bounding boxes overlay on image
- Label hierarchy (parent categories)
- Instance segmentation (when available)
- Dominant colors visualization

#### 3.2 Face Detection & Analysis
**Same attributes as video but synchronous**

**Additional image-specific features:**
- Higher resolution face crops
- Quality metrics for enrollment decisions

#### 3.3 Face Comparison
**Purpose:** Compare faces between two images

**Options to expose:**
- `SimilarityThreshold` (0-100, default 80)
- `QualityFilter` (NONE, AUTO, LOW, MEDIUM, HIGH)

**Results display:**
- Side-by-side comparison
- Similarity percentage
- Matched/unmatched indicator
- Face quality scores

#### 3.4 Celebrity Recognition
**Same as video but synchronous**

#### 3.5 Content Moderation
**Same categories as video but synchronous**

#### 3.6 Text Detection (OCR)
**Purpose:** Extract text from images

**Options to expose:**
- Word filter confidence
- Region of interest

**Results display:**
- Extracted text with formatting
- Bounding boxes
- Line vs word detection
- Confidence scores
- Copy to clipboard option

#### 3.7 PPE Detection (Personal Protective Equipment)
**Purpose:** Detect safety equipment on people

**Options to expose:**
- Equipment types to detect:
  - Face cover (mask)
  - Hand cover (gloves)
  - Head cover (helmet/hard hat)
- `MinConfidence`

**Results display:**
- Person-by-person breakdown
- Equipment presence/absence
- Coverage indicators (covers body part or not)
- Compliance summary
- Bounding boxes

#### 3.8 Custom Labels (Advanced)
**Purpose:** Use custom-trained models

**Prerequisites:**
- Trained custom labels project
- Project version ARN

**Options to expose:**
- Project version selection
- `MinConfidence`
- `MaxResults`

---

### 4. Face Collection Management

#### Features
- Create new collection
- List all collections
- Delete collection
- Add faces from images
- List faces in collection
- Delete faces from collection
- Search faces by image

#### UI Components
- Collection browser/selector
- Face gallery view
- External image ID management
- Batch face addition

---

### 5. Results & History Management

#### Features
- Job history with status tracking
- Results caching (store in local DB or files)
- Export results (JSON, CSV, PDF report)
- Re-analyze with different options
- Compare results between analyses

#### Storage Options
- SQLite for job metadata and results
- JSON files for detailed results
- Optional: DynamoDB for cloud storage

---

## UI/UX Design

### Navigation Structure
```
Home (Dashboard)
├── Upload
│   ├── Video Upload
│   └── Image Upload
├── Video Analysis
│   ├── Select Video (from S3 list)
│   ├── Analysis Options
│   │   ├── Label Detection
│   │   ├── Face Detection
│   │   ├── Face Search
│   │   ├── Person Tracking
│   │   ├── Celebrity Recognition
│   │   ├── Content Moderation
│   │   ├── Text Detection
│   │   └── Segment Detection
│   └── Results Viewer
├── Image Analysis
│   ├── Select Image (from S3 list)
│   ├── Analysis Options
│   │   ├── Label Detection
│   │   ├── Face Detection
│   │   ├── Face Comparison
│   │   ├── Celebrity Recognition
│   │   ├── Content Moderation
│   │   ├── Text Detection
│   │   ├── PPE Detection
│   │   └── Custom Labels
│   └── Results Viewer
├── Face Collections
│   ├── Manage Collections
│   └── Face Search
├── History
│   └── Past Analysis Jobs
└── Settings
    ├── AWS Configuration
    └── Default Options
```

### Dashboard Components
1. **Quick Stats** - Total files, recent analyses, storage used
2. **Recent Uploads** - Last 5 uploaded files with thumbnails
3. **Active Jobs** - Currently processing analyses with progress
4. **Recent Results** - Quick access to recent analysis results
5. **Quick Actions** - Upload, New Analysis buttons

### Analysis Workflow UI
1. **File Selection** - Browse S3 bucket or recent uploads
2. **Analysis Type Selection** - Cards/tiles for each analysis type
3. **Options Configuration** - Collapsible panels with sliders/inputs
4. **Job Submission** - Start analysis with loading indicator
5. **Progress Tracking** - Status updates, estimated time
6. **Results Display** - Formatted results with visualizations

---

## API Endpoints Summary

### Upload
```
POST   /api/upload/presigned-url     # Get presigned URL
POST   /api/upload/file              # Direct upload
GET    /api/files                    # List files
GET    /api/files/<id>               # Get file details
DELETE /api/files/<id>               # Delete file
```

### Video Analysis
```
POST   /api/video/labels/start       # Start label detection
GET    /api/video/labels/<job_id>    # Get label results
POST   /api/video/faces/start        # Start face detection
GET    /api/video/faces/<job_id>     # Get face results
POST   /api/video/face-search/start  # Start face search
GET    /api/video/face-search/<job_id>
POST   /api/video/persons/start      # Start person tracking
GET    /api/video/persons/<job_id>
POST   /api/video/celebrities/start  # Start celebrity recognition
GET    /api/video/celebrities/<job_id>
POST   /api/video/moderation/start   # Start content moderation
GET    /api/video/moderation/<job_id>
POST   /api/video/text/start         # Start text detection
GET    /api/video/text/<job_id>
POST   /api/video/segments/start     # Start segment detection
GET    /api/video/segments/<job_id>
GET    /api/video/job/<job_id>/status # Check job status
```

### Image Analysis
```
POST   /api/image/labels             # Detect labels
POST   /api/image/faces              # Detect faces
POST   /api/image/face-compare       # Compare faces
POST   /api/image/celebrities        # Recognize celebrities
POST   /api/image/moderation         # Content moderation
POST   /api/image/text               # Detect text
POST   /api/image/ppe                # PPE detection
POST   /api/image/custom-labels      # Custom labels
```

### Face Collections
```
GET    /api/collections              # List collections
POST   /api/collections              # Create collection
DELETE /api/collections/<id>         # Delete collection
GET    /api/collections/<id>/faces   # List faces
POST   /api/collections/<id>/faces   # Add face
DELETE /api/collections/<id>/faces/<face_id>  # Remove face
POST   /api/collections/<id>/search  # Search by image
```

### History & Settings
```
GET    /api/history                  # List past jobs
GET    /api/history/<job_id>         # Get job details
GET    /api/settings                 # Get settings
PUT    /api/settings                 # Update settings
```

---

## Implementation Phases

### Phase 1: Foundation
1. Set up Flask application structure
2. Configure AWS SDK (boto3)
3. Implement S3 upload service
4. Create base templates and navigation
5. Basic file upload UI

### Phase 2: Video Analysis Core
1. Implement video label detection
2. Implement video face detection
3. Create job status polling mechanism
4. Build results display templates
5. Add progress indicators

### Phase 3: Video Analysis Extended
1. Celebrity recognition
2. Content moderation
3. Text detection
4. Segment detection
5. Person tracking
6. Face search (requires Phase 4)

### Phase 4: Face Collections
1. Collection CRUD operations
2. Face indexing from images
3. Collection browser UI
4. Face search integration

### Phase 5: Image Analysis
1. All image analysis endpoints
2. Image-specific UI components
3. Face comparison feature
4. PPE detection

### Phase 6: Polish & Advanced Features
1. Results history and caching
2. Export functionality
3. Dashboard statistics
4. Settings management
5. Error handling improvements
6. Performance optimization

---

## Error Handling

### AWS Errors to Handle
- `InvalidS3ObjectException` - File not found or inaccessible
- `InvalidParameterException` - Invalid analysis parameters
- `AccessDeniedException` - Permission issues
- `ThrottlingException` - Rate limiting
- `VideoTooLargeException` - Video exceeds size limits
- `InvalidImageFormatException` - Unsupported image format
- `ImageTooLargeException` - Image exceeds limits
- `ProvisionedThroughputExceededException` - Throughput exceeded

### User-Friendly Error Messages
- Display clear error descriptions
- Suggest corrective actions
- Provide retry options where appropriate

---

## Security Considerations

1. **AWS Credentials** - Never expose in frontend; use environment variables
2. **File Validation** - Validate file types and sizes server-side
3. **CSRF Protection** - Enable Flask-WTF CSRF protection
4. **Input Sanitization** - Sanitize all user inputs
5. **Presigned URLs** - Use short expiration times
6. **S3 Bucket Policy** - Restrict public access
7. **Rate Limiting** - Implement request rate limiting

---

## Performance Optimization

1. **Presigned URLs** - Direct browser-to-S3 uploads for large files
2. **Pagination** - Paginate large result sets
3. **Caching** - Cache analysis results locally
4. **Async Processing** - Background job processing for video analysis
5. **Lazy Loading** - Load thumbnails and results on demand
6. **Compression** - Enable gzip compression for responses

---

## Testing Strategy

### Unit Tests
- Service layer functions
- Utility functions
- Input validation

### Integration Tests
- AWS service connectivity
- API endpoint responses
- File upload flow

### Manual Testing
- UI/UX validation
- Cross-browser testing
- Large file handling

---

## Deployment Notes

### Local Development
```bash
cd E:\coding\video
.\.venv\Scripts\activate
pip install -r requirements.txt
python run.py
# Access at http://localhost:5700
```

### Production Considerations
- Use gunicorn/waitress as WSGI server
- Configure proper logging
- Set up monitoring
- Use HTTPS
- Consider containerization (Docker)

---

## Estimated File Count

| Category | Files |
|----------|-------|
| Python Backend | ~15 files |
| HTML Templates | ~12 files |
| CSS | ~2 files |
| JavaScript | ~5 files |
| Configuration | ~4 files |
| **Total** | **~38 files** |

---

## Additional Future Enhancements

1. **Real-time Processing** - WebSocket updates for job progress
2. **Batch Processing** - Analyze multiple files at once
3. **Webhooks** - SNS integration for job completion
4. **User Authentication** - Multi-user support
5. **API Documentation** - Swagger/OpenAPI spec
6. **Mobile Responsive** - Full mobile UI support
7. **Video Player Integration** - Sync results with video playback
8. **Annotation Export** - Export to common annotation formats
