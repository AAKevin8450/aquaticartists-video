# Comprehensive Testing Plan for Video & Image Analysis Application
**Date:** 2025-12-17
**Application:** AWS Video & Image Analysis Flask Application
**Environment:** localhost:5700

---

## Overview

This testing plan provides automated test procedures for all features of the video and image analysis application. Tests are designed to be executed sequentially by an AI agent without user interaction.

### Test Files
- **Image:** `tests/Robinson.jpg`
- **Video:** `tests/Two_puppet_friends_202507101845.mp4`

### Base URL
```
http://localhost:5700
```

### Prerequisites
1. Application is running on port 5700
2. AWS credentials are configured in `.env`
3. S3 bucket `video-analysis-app-676206912644` is accessible
4. Test files exist in `./tests/` directory

---

## Test Execution Order

Execute tests in the following order to ensure dependencies are met:

1. Health Check & Server Verification
2. File Upload Tests (creates file records needed for analysis)
3. Image Analysis Tests (all 7 types - custom labels excluded)
4. Video Analysis Tests (all 8 types)
5. Face Collection Management Tests
6. History & Job Tracking Tests
7. Cleanup Tests

---

## Phase 1: Health Check & Server Verification

### Test 1.1: Application Health Check
**Endpoint:** `GET /health`

**Command:**
```bash
curl -s http://localhost:5700/health
```

**Expected Response:**
```json
{
  "status": "healthy"
}
```

**Pass Criteria:** HTTP 200, status is "healthy"

---

### Test 1.2: Main Page Load
**Endpoint:** `GET /`

**Command:**
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5700/
```

**Expected:** HTTP 200

---

### Test 1.3: All Page Routes Accessible
Test each page route returns HTTP 200:

| Page | Endpoint |
|------|----------|
| Upload | `GET /upload` |
| Video Analysis | `GET /video-analysis` |
| Image Analysis | `GET /image-analysis` |
| Collections | `GET /collections` |
| History | `GET /history` |

**Command (for each):**
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5700/upload
curl -s -o /dev/null -w "%{http_code}" http://localhost:5700/video-analysis
curl -s -o /dev/null -w "%{http_code}" http://localhost:5700/image-analysis
curl -s -o /dev/null -w "%{http_code}" http://localhost:5700/collections
curl -s -o /dev/null -w "%{http_code}" http://localhost:5700/history
```

**Pass Criteria:** All return HTTP 200

---

## Phase 2: File Upload Tests

### Test 2.1: Upload Test Image via Direct Upload
**Endpoint:** `POST /api/upload/file`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/upload/file \
  -F "file=@tests/Robinson.jpg"
```

**Expected Response:**
```json
{
  "file_id": <integer>,
  "message": "File uploaded successfully",
  "s3_key": "<uuid>/Robinson.jpg"
}
```

**Pass Criteria:**
- HTTP 200/201
- Response contains `file_id` (integer)
- Response contains `s3_key` (string)

**Action:** Store returned `file_id` as `IMAGE_FILE_ID` for subsequent tests

---

### Test 2.2: Upload Test Video via Direct Upload
**Endpoint:** `POST /api/upload/file`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/upload/file \
  -F "file=@tests/Two_puppet_friends_202507101845.mp4"
```

**Expected Response:**
```json
{
  "file_id": <integer>,
  "message": "File uploaded successfully",
  "s3_key": "<uuid>/Two_puppet_friends_202507101845.mp4"
}
```

**Pass Criteria:**
- HTTP 200/201
- Response contains `file_id` (integer)
- Response contains `s3_key` (string)

**Action:** Store returned `file_id` as `VIDEO_FILE_ID` for subsequent tests

---

### Test 2.3: List Uploaded Files
**Endpoint:** `GET /api/upload/files`

**Command:**
```bash
curl -s "http://localhost:5700/api/upload/files"
```

**Expected Response:**
```json
{
  "files": [
    {
      "id": <integer>,
      "filename": "<string>",
      "s3_key": "<string>",
      "file_type": "image|video",
      "size_bytes": <integer>,
      "content_type": "<string>",
      "uploaded_at": "<timestamp>"
    }
  ],
  "total": <integer>
}
```

**Pass Criteria:**
- HTTP 200
- `files` array contains at least 2 items
- Both test files are present

---

### Test 2.4: List Files by Type (Images Only)
**Endpoint:** `GET /api/upload/files?type=image`

**Command:**
```bash
curl -s "http://localhost:5700/api/upload/files?type=image"
```

**Pass Criteria:**
- HTTP 200
- All returned files have `file_type: "image"`

---

### Test 2.5: List Files by Type (Videos Only)
**Endpoint:** `GET /api/upload/files?type=video`

**Command:**
```bash
curl -s "http://localhost:5700/api/upload/files?type=video"
```

**Pass Criteria:**
- HTTP 200
- All returned files have `file_type: "video"`

---

### Test 2.6: Get File Details
**Endpoint:** `GET /api/upload/files/<file_id>`

**Command (use IMAGE_FILE_ID from Test 2.1):**
```bash
curl -s "http://localhost:5700/api/upload/files/${IMAGE_FILE_ID}"
```

**Expected Response:**
```json
{
  "id": <integer>,
  "filename": "Robinson.jpg",
  "s3_key": "<string>",
  "file_type": "image",
  "size_bytes": <integer>,
  "content_type": "image/jpeg",
  "presigned_url": "<url string>"
}
```

**Pass Criteria:**
- HTTP 200
- Contains `presigned_url` for file access

---

### Test 2.7: Generate Presigned URL for Upload
**Endpoint:** `POST /api/upload/presigned-url`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/upload/presigned-url \
  -H "Content-Type: application/json" \
  -d '{"filename": "test_presigned.jpg", "content_type": "image/jpeg", "size_bytes": 1024}'
```

**Expected Response:**
```json
{
  "url": "<s3 presigned url>",
  "fields": {
    "key": "<string>",
    "AWSAccessKeyId": "<string>",
    "policy": "<string>",
    "signature": "<string>"
  },
  "s3_key": "<string>"
}
```

**Pass Criteria:**
- HTTP 200
- Contains `url`, `fields`, and `s3_key`

---

## Phase 3: Image Analysis Tests

All image analysis tests use `IMAGE_FILE_ID` from Test 2.1.

### Test 3.1: Image Label Detection
**Endpoint:** `POST /api/image/labels`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/labels \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}'}'
```

**Expected Response:**
```json
{
  "job_id": <integer>,
  "status": "SUCCEEDED",
  "results": {
    "labels": [
      {
        "Name": "<string>",
        "Confidence": <float>,
        "Instances": [],
        "Parents": [],
        "Categories": []
      }
    ],
    "label_model_version": "<string>"
  }
}
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- `results.labels` is a non-empty array
- Each label has `Name` and `Confidence` fields

---

### Test 3.2: Image Label Detection with Parameters
**Endpoint:** `POST /api/image/labels`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/labels \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}', "max_labels": 5, "min_confidence": 80.0}'
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Number of labels returned is <= 5
- All labels have Confidence >= 80.0

---

### Test 3.3: Image Face Detection
**Endpoint:** `POST /api/image/faces`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/faces \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}'}'
```

**Expected Response:**
```json
{
  "job_id": <integer>,
  "status": "SUCCEEDED",
  "results": {
    "faces": [
      {
        "BoundingBox": {
          "Width": <float>,
          "Height": <float>,
          "Left": <float>,
          "Top": <float>
        },
        "AgeRange": {"Low": <int>, "High": <int>},
        "Smile": {"Value": <bool>, "Confidence": <float>},
        "Eyeglasses": {"Value": <bool>, "Confidence": <float>},
        "Sunglasses": {"Value": <bool>, "Confidence": <float>},
        "Gender": {"Value": "<string>", "Confidence": <float>},
        "Beard": {"Value": <bool>, "Confidence": <float>},
        "Mustache": {"Value": <bool>, "Confidence": <float>},
        "EyesOpen": {"Value": <bool>, "Confidence": <float>},
        "MouthOpen": {"Value": <bool>, "Confidence": <float>},
        "Emotions": [],
        "Landmarks": [],
        "Pose": {},
        "Quality": {},
        "Confidence": <float>
      }
    ],
    "face_count": <integer>
  }
}
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- `results.faces` is an array (may be empty if no faces in image)
- `results.face_count` is an integer >= 0

---

### Test 3.4: Image Face Detection with DEFAULT Attributes
**Endpoint:** `POST /api/image/faces`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/faces \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}', "attributes": ["DEFAULT"]}'
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Results contain face detection data with basic attributes only

---

### Test 3.5: Image Celebrity Recognition
**Endpoint:** `POST /api/image/celebrities`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/celebrities \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}'}'
```

**Expected Response:**
```json
{
  "job_id": <integer>,
  "status": "SUCCEEDED",
  "results": {
    "celebrities": [],
    "unrecognized_faces": [],
    "celebrity_count": <integer>
  }
}
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Response contains `celebrities` array (may be empty)
- Response contains `celebrity_count` integer

---

### Test 3.6: Image Content Moderation
**Endpoint:** `POST /api/image/moderation`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/moderation \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}'}'
```

**Expected Response:**
```json
{
  "job_id": <integer>,
  "status": "SUCCEEDED",
  "results": {
    "moderation_labels": [],
    "moderation_model_version": "<string>",
    "flagged_content": <boolean>
  }
}
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Response contains `moderation_labels` array
- Response contains `flagged_content` boolean

---

### Test 3.7: Image Content Moderation with Custom Confidence
**Endpoint:** `POST /api/image/moderation`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/moderation \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}', "min_confidence": 90.0}'
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Any returned moderation labels have Confidence >= 90.0

---

### Test 3.8: Image Text Detection (OCR)
**Endpoint:** `POST /api/image/text`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/text \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}'}'
```

**Expected Response:**
```json
{
  "job_id": <integer>,
  "status": "SUCCEEDED",
  "results": {
    "text_detections": [],
    "lines": [],
    "words": [],
    "full_text": "<string>",
    "text_model_version": "<string>"
  }
}
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Response contains `text_detections` array
- Response contains `full_text` string

---

### Test 3.9: Image PPE Detection
**Endpoint:** `POST /api/image/ppe`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/ppe \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}'}'
```

**Expected Response:**
```json
{
  "job_id": <integer>,
  "status": "SUCCEEDED",
  "results": {
    "persons": [],
    "person_count": <integer>,
    "ppe_model_version": "<string>"
  }
}
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Response contains `persons` array
- Response contains `person_count` integer

---

### Test 3.10: Upload Second Image for Face Comparison
**Purpose:** Upload a second image to enable face comparison testing

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/upload/file \
  -F "file=@tests/Robinson.jpg"
```

**Action:** Store returned `file_id` as `IMAGE_FILE_ID_2`

---

### Test 3.11: Image Face Comparison
**Endpoint:** `POST /api/image/face-compare`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/face-compare \
  -H "Content-Type: application/json" \
  -d '{"source_file_id": '${IMAGE_FILE_ID}', "target_file_id": '${IMAGE_FILE_ID_2}'}'
```

**Expected Response:**
```json
{
  "job_id": <integer>,
  "status": "SUCCEEDED",
  "results": {
    "face_matches": [],
    "unmatched_faces": [],
    "source_face": {}
  }
}
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Response contains `face_matches` array
- Response contains `source_face` object

---

### Test 3.12: Image Face Comparison with Custom Threshold
**Endpoint:** `POST /api/image/face-compare`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/face-compare \
  -H "Content-Type: application/json" \
  -d '{"source_file_id": '${IMAGE_FILE_ID}', "target_file_id": '${IMAGE_FILE_ID_2}', "similarity_threshold": 95.0, "quality_filter": "HIGH"}'
```

**Pass Criteria:**
- HTTP 200
- Status is "SUCCEEDED"
- Any face matches have similarity >= 95.0

---

## Phase 4: Video Analysis Tests

All video analysis tests use `VIDEO_FILE_ID` from Test 2.2.

**Important:** Video analysis is asynchronous. Each test will:
1. Start the analysis job
2. Poll for job completion
3. Verify the results

### Test 4.1: Video Label Detection

#### Step 4.1.1: Start Job
**Endpoint:** `POST /api/video/labels/start`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/labels/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}'}'
```

**Expected Response:**
```json
{
  "job_id": "<string>",
  "job_db_id": <integer>,
  "status": "SUBMITTED",
  "message": "Video label detection job started"
}
```

**Action:** Store `job_id` as `LABEL_JOB_ID`

#### Step 4.1.2: Poll for Completion
**Endpoint:** `GET /api/video/job/<job_id>/status`

**Command (poll every 5 seconds until SUCCEEDED or FAILED):**
```bash
curl -s "http://localhost:5700/api/video/job/${LABEL_JOB_ID}/status"
```

**Expected Status Progression:** SUBMITTED -> IN_PROGRESS -> SUCCEEDED

#### Step 4.1.3: Verify Results
**Pass Criteria when SUCCEEDED:**
```json
{
  "status": "SUCCEEDED",
  "results": {
    "Labels": [
      {
        "Label": {
          "Name": "<string>",
          "Confidence": <float>
        },
        "Timestamp": <integer>
      }
    ],
    "VideoMetadata": {
      "Codec": "<string>",
      "DurationMillis": <integer>,
      "Format": "<string>",
      "FrameHeight": <integer>,
      "FrameWidth": <integer>,
      "FrameRate": <float>
    }
  }
}
```

---

### Test 4.2: Video Label Detection with Parameters

#### Step 4.2.1: Start Job
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/labels/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}', "min_confidence": 80.0, "max_labels": 10}'
```

**Action:** Store `job_id` and poll until completion

**Pass Criteria:**
- All returned labels have Confidence >= 80.0

---

### Test 4.3: Video Face Detection

#### Step 4.3.1: Start Job
**Endpoint:** `POST /api/video/faces/start`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/faces/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}'}'
```

**Action:** Store `job_id` as `FACE_JOB_ID` and poll until completion

**Expected Results Structure:**
```json
{
  "status": "SUCCEEDED",
  "results": {
    "Faces": [
      {
        "Timestamp": <integer>,
        "Face": {
          "BoundingBox": {},
          "AgeRange": {},
          "Gender": {},
          "Emotions": [],
          "Confidence": <float>
        }
      }
    ],
    "VideoMetadata": {}
  }
}
```

**Pass Criteria:**
- Status is "SUCCEEDED"
- Results contain `Faces` array
- Results contain `VideoMetadata` object

---

### Test 4.4: Video Face Detection with DEFAULT Attributes
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/faces/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}', "attributes": "DEFAULT"}'
```

**Pass Criteria:**
- Status is "SUCCEEDED" after polling
- Results contain basic face detection data

---

### Test 4.5: Video Celebrity Recognition

#### Step 4.5.1: Start Job
**Endpoint:** `POST /api/video/celebrities/start`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/celebrities/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}'}'
```

**Action:** Store `job_id` and poll until completion

**Expected Results Structure:**
```json
{
  "status": "SUCCEEDED",
  "results": {
    "Celebrities": [],
    "VideoMetadata": {}
  }
}
```

**Pass Criteria:**
- Status is "SUCCEEDED"
- Results contain `Celebrities` array (may be empty)

---

### Test 4.6: Video Content Moderation

#### Step 4.6.1: Start Job
**Endpoint:** `POST /api/video/moderation/start`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/moderation/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}'}'
```

**Action:** Store `job_id` and poll until completion

**Expected Results Structure:**
```json
{
  "status": "SUCCEEDED",
  "results": {
    "ModerationLabels": [],
    "VideoMetadata": {}
  }
}
```

**Pass Criteria:**
- Status is "SUCCEEDED"
- Results contain `ModerationLabels` array

---

### Test 4.7: Video Content Moderation with Custom Confidence
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/moderation/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}', "min_confidence": 75.0}'
```

**Pass Criteria:**
- Status is "SUCCEEDED" after polling
- Any moderation labels have Confidence >= 75.0

---

### Test 4.8: Video Text Detection (OCR)

#### Step 4.8.1: Start Job
**Endpoint:** `POST /api/video/text/start`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/text/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}'}'
```

**Action:** Store `job_id` and poll until completion

**Expected Results Structure:**
```json
{
  "status": "SUCCEEDED",
  "results": {
    "TextDetections": [],
    "VideoMetadata": {}
  }
}
```

**Pass Criteria:**
- Status is "SUCCEEDED"
- Results contain `TextDetections` array

---

### Test 4.9: Video Segment Detection

#### Step 4.9.1: Start Job
**Endpoint:** `POST /api/video/segments/start`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/segments/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}'}'
```

**Action:** Store `job_id` and poll until completion

**Expected Results Structure:**
```json
{
  "status": "SUCCEEDED",
  "results": {
    "Segments": [],
    "AudioMetadata": [],
    "VideoMetadata": {}
  }
}
```

**Pass Criteria:**
- Status is "SUCCEEDED"
- Results contain `Segments` array

---

### Test 4.10: Video Segment Detection with Specific Types
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/segments/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}', "segment_types": ["SHOT"]}'
```

**Pass Criteria:**
- Status is "SUCCEEDED" after polling
- Results contain shot segment data

---

### Test 4.11: Video Person Tracking

#### Step 4.11.1: Start Job
**Endpoint:** `POST /api/video/persons/start`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/persons/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}'}'
```

**Action:** Store `job_id` and poll until completion

**Expected Results Structure:**
```json
{
  "status": "SUCCEEDED",
  "results": {
    "Persons": [
      {
        "Timestamp": <integer>,
        "Person": {
          "Index": <integer>,
          "BoundingBox": {}
        }
      }
    ],
    "VideoMetadata": {}
  }
}
```

**Pass Criteria:**
- Status is "SUCCEEDED"
- Results contain `Persons` array
- Each person has unique `Index` for tracking

---

## Phase 5: Face Collection Management Tests

### Test 5.1: List Collections (Initial State)
**Endpoint:** `GET /api/collections/`

**Command:**
```bash
curl -s "http://localhost:5700/api/collections/"
```

**Expected Response:**
```json
{
  "collections": []
}
```

**Pass Criteria:**
- HTTP 200
- Response contains `collections` array

---

### Test 5.2: Create New Collection
**Endpoint:** `POST /api/collections/`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/collections/ \
  -H "Content-Type: application/json" \
  -d '{"collection_id": "test-collection-2025"}'
```

**Expected Response:**
```json
{
  "collection_id": "test-collection-2025",
  "collection_arn": "arn:aws:rekognition:us-east-1:...",
  "message": "Collection created successfully"
}
```

**Pass Criteria:**
- HTTP 200/201
- Response contains `collection_id`
- Response contains `collection_arn`

---

### Test 5.3: Create Duplicate Collection (Error Case)
**Endpoint:** `POST /api/collections/`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/collections/ \
  -H "Content-Type: application/json" \
  -d '{"collection_id": "test-collection-2025"}'
```

**Pass Criteria:**
- HTTP 400 or appropriate error code
- Error message indicates collection already exists

---

### Test 5.4: List Collections (After Creation)
**Endpoint:** `GET /api/collections/`

**Command:**
```bash
curl -s "http://localhost:5700/api/collections/"
```

**Pass Criteria:**
- HTTP 200
- `collections` array contains "test-collection-2025"

---

### Test 5.5: List Faces in Empty Collection
**Endpoint:** `GET /api/collections/<collection_id>/faces`

**Command:**
```bash
curl -s "http://localhost:5700/api/collections/test-collection-2025/faces"
```

**Expected Response:**
```json
{
  "faces": [],
  "face_count": 0,
  "face_model_version": "<string>"
}
```

**Pass Criteria:**
- HTTP 200
- `face_count` is 0
- `faces` is empty array

---

### Test 5.6: Index Face to Collection
**Endpoint:** `POST /api/collections/<collection_id>/faces`

**Command:**
```bash
curl -s -X POST "http://localhost:5700/api/collections/test-collection-2025/faces" \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}', "external_image_id": "test-person-1"}'
```

**Expected Response:**
```json
{
  "face_records": [
    {
      "Face": {
        "FaceId": "<uuid>",
        "BoundingBox": {},
        "ImageId": "<uuid>",
        "ExternalImageId": "test-person-1",
        "Confidence": <float>
      },
      "FaceDetail": {}
    }
  ],
  "unindexed_faces": [],
  "indexed_count": <integer>,
  "unindexed_count": 0
}
```

**Action:** Store first `FaceId` as `INDEXED_FACE_ID`

**Pass Criteria:**
- HTTP 200
- `face_records` is non-empty (if image contains faces)
- `indexed_count` >= 1

---

### Test 5.7: Index Face with Quality Filter
**Command:**
```bash
curl -s -X POST "http://localhost:5700/api/collections/test-collection-2025/faces" \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}', "external_image_id": "test-person-2", "quality_filter": "HIGH", "max_faces": 1}'
```

**Pass Criteria:**
- HTTP 200
- Only high-quality faces indexed

---

### Test 5.8: List Faces in Collection (After Indexing)
**Endpoint:** `GET /api/collections/<collection_id>/faces`

**Command:**
```bash
curl -s "http://localhost:5700/api/collections/test-collection-2025/faces"
```

**Pass Criteria:**
- HTTP 200
- `face_count` >= 1
- `faces` array contains indexed faces

---

### Test 5.9: Search Faces by Image
**Endpoint:** `POST /api/collections/<collection_id>/search`

**Command:**
```bash
curl -s -X POST "http://localhost:5700/api/collections/test-collection-2025/search" \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}'}'
```

**Expected Response:**
```json
{
  "face_matches": [
    {
      "Similarity": <float>,
      "Face": {
        "FaceId": "<uuid>",
        "ExternalImageId": "<string>",
        "Confidence": <float>
      }
    }
  ],
  "match_count": <integer>,
  "searched_face_confidence": <float>
}
```

**Pass Criteria:**
- HTTP 200
- `face_matches` contains matching faces (should find the indexed face)
- Each match has `Similarity` score

---

### Test 5.10: Search Faces with Custom Threshold
**Command:**
```bash
curl -s -X POST "http://localhost:5700/api/collections/test-collection-2025/search" \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${IMAGE_FILE_ID}', "face_match_threshold": 99.0, "max_faces": 5}'
```

**Pass Criteria:**
- HTTP 200
- Any matches have Similarity >= 99.0

---

### Test 5.11: Video Face Search in Collection
**Endpoint:** `POST /api/video/face-search/start`

**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/face-search/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}', "collection_id": "test-collection-2025"}'
```

**Action:** Store `job_id` and poll until completion

**Pass Criteria:**
- Status is "SUCCEEDED" after polling
- Results contain face match data from video

---

### Test 5.12: Video Face Search with Custom Threshold
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/face-search/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}', "collection_id": "test-collection-2025", "face_match_threshold": 90.0}'
```

**Pass Criteria:**
- Status is "SUCCEEDED" after polling

---

### Test 5.13: Delete Face from Collection
**Endpoint:** `DELETE /api/collections/<collection_id>/faces/<face_id>`

**Command (use INDEXED_FACE_ID from Test 5.6):**
```bash
curl -s -X DELETE "http://localhost:5700/api/collections/test-collection-2025/faces/${INDEXED_FACE_ID}"
```

**Expected Response:**
```json
{
  "deleted_faces": ["<face_id>"],
  "deleted_count": 1
}
```

**Pass Criteria:**
- HTTP 200
- `deleted_count` is 1

---

### Test 5.14: Delete Non-Existent Face (Error Case)
**Command:**
```bash
curl -s -X DELETE "http://localhost:5700/api/collections/test-collection-2025/faces/non-existent-face-id"
```

**Pass Criteria:**
- HTTP 400 or 404
- Appropriate error message

---

### Test 5.15: Delete Collection
**Endpoint:** `DELETE /api/collections/<collection_id>`

**Command:**
```bash
curl -s -X DELETE "http://localhost:5700/api/collections/test-collection-2025"
```

**Expected Response:**
```json
{
  "message": "Collection deleted successfully"
}
```

**Pass Criteria:**
- HTTP 200
- Collection is deleted

---

### Test 5.16: Delete Non-Existent Collection (Error Case)
**Command:**
```bash
curl -s -X DELETE "http://localhost:5700/api/collections/non-existent-collection"
```

**Pass Criteria:**
- HTTP 400 or 404
- Appropriate error message

---

## Phase 6: History & Job Tracking Tests

### Test 6.1: List All Jobs
**Endpoint:** `GET /api/history/`

**Command:**
```bash
curl -s "http://localhost:5700/api/history/"
```

**Expected Response:**
```json
{
  "jobs": [
    {
      "id": <integer>,
      "job_id": "<string>",
      "file_id": <integer>,
      "analysis_type": "<string>",
      "status": "<string>",
      "started_at": "<timestamp>",
      "completed_at": "<timestamp>"
    }
  ],
  "total": <integer>
}
```

**Pass Criteria:**
- HTTP 200
- `jobs` array contains jobs from previous tests
- `total` reflects actual job count

---

### Test 6.2: List Jobs by Status
**Endpoint:** `GET /api/history/?status=SUCCEEDED`

**Command:**
```bash
curl -s "http://localhost:5700/api/history/?status=SUCCEEDED"
```

**Pass Criteria:**
- HTTP 200
- All returned jobs have `status: "SUCCEEDED"`

---

### Test 6.3: List Jobs by File ID
**Endpoint:** `GET /api/history/?file_id=<id>`

**Command:**
```bash
curl -s "http://localhost:5700/api/history/?file_id=${IMAGE_FILE_ID}"
```

**Pass Criteria:**
- HTTP 200
- All returned jobs have matching `file_id`

---

### Test 6.4: List Jobs with Pagination
**Endpoint:** `GET /api/history/?limit=5&offset=0`

**Command:**
```bash
curl -s "http://localhost:5700/api/history/?limit=5&offset=0"
```

**Pass Criteria:**
- HTTP 200
- Number of jobs returned <= 5

---

### Test 6.5: Get Single Job Details
**Endpoint:** `GET /api/history/<job_id>`

**Note:** Use a job_id from Test 6.1 results

**Command:**
```bash
curl -s "http://localhost:5700/api/history/${SOME_JOB_ID}"
```

**Expected Response:**
```json
{
  "id": <integer>,
  "job_id": "<string>",
  "file_id": <integer>,
  "analysis_type": "<string>",
  "status": "<string>",
  "parameters": {},
  "results": {},
  "started_at": "<timestamp>",
  "completed_at": "<timestamp>",
  "error_message": null
}
```

**Pass Criteria:**
- HTTP 200
- Response contains full job details including `results`

---

### Test 6.6: Get Non-Existent Job (Error Case)
**Command:**
```bash
curl -s "http://localhost:5700/api/history/non-existent-job-id"
```

**Pass Criteria:**
- HTTP 404
- Appropriate error message

---

### Test 6.7: Delete Job from History
**Endpoint:** `DELETE /api/history/<job_id>`

**Note:** Use a job_id that won't affect other tests

**Command:**
```bash
curl -s -X DELETE "http://localhost:5700/api/history/${SOME_JOB_ID}"
```

**Expected Response:**
```json
{
  "message": "Job deleted successfully"
}
```

**Pass Criteria:**
- HTTP 200
- Job is removed from history

---

## Phase 7: Error Handling Tests

### Test 7.1: Invalid File ID for Image Analysis
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/labels \
  -H "Content-Type: application/json" \
  -d '{"file_id": 999999}'
```

**Pass Criteria:**
- HTTP 404 or 400
- Error message indicates file not found

---

### Test 7.2: Invalid File ID for Video Analysis
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/labels/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": 999999}'
```

**Pass Criteria:**
- HTTP 404 or 400
- Error message indicates file not found

---

### Test 7.3: Missing Required Parameter
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/image/labels \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Pass Criteria:**
- HTTP 400
- Error message indicates missing `file_id`

---

### Test 7.4: Invalid Collection ID for Face Search
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/video/face-search/start \
  -H "Content-Type: application/json" \
  -d '{"file_id": '${VIDEO_FILE_ID}', "collection_id": "non-existent-collection"}'
```

**Pass Criteria:**
- HTTP 400 or 404
- Error message indicates collection not found

---

### Test 7.5: Invalid Content Type for Upload
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/upload/presigned-url \
  -H "Content-Type: application/json" \
  -d '{"filename": "test.exe", "content_type": "application/x-executable", "size_bytes": 1024}'
```

**Pass Criteria:**
- HTTP 400
- Error message indicates invalid file type

---

### Test 7.6: File Too Large
**Command:**
```bash
curl -s -X POST http://localhost:5700/api/upload/presigned-url \
  -H "Content-Type: application/json" \
  -d '{"filename": "huge.mp4", "content_type": "video/mp4", "size_bytes": 20000000000}'
```

**Pass Criteria:**
- HTTP 400
- Error message indicates file too large

---

## Phase 8: Cleanup Tests

### Test 8.1: Delete Uploaded Image File
**Endpoint:** `DELETE /api/upload/files/<file_id>`

**Command:**
```bash
curl -s -X DELETE "http://localhost:5700/api/upload/files/${IMAGE_FILE_ID}"
```

**Pass Criteria:**
- HTTP 200
- File deleted from S3 and database

---

### Test 8.2: Delete Uploaded Video File
**Command:**
```bash
curl -s -X DELETE "http://localhost:5700/api/upload/files/${VIDEO_FILE_ID}"
```

**Pass Criteria:**
- HTTP 200
- File deleted from S3 and database

---

### Test 8.3: Delete Second Image File
**Command:**
```bash
curl -s -X DELETE "http://localhost:5700/api/upload/files/${IMAGE_FILE_ID_2}"
```

**Pass Criteria:**
- HTTP 200

---

### Test 8.4: Verify Files Deleted
**Command:**
```bash
curl -s "http://localhost:5700/api/upload/files"
```

**Pass Criteria:**
- Test files no longer in list

---

## Appendix A: Test Execution Script Template

```python
#!/usr/bin/env python3
"""
Automated Test Execution Script for Video & Image Analysis Application
"""
import requests
import time
import json
import sys

BASE_URL = "http://localhost:5700"
TEST_IMAGE = "tests/Robinson.jpg"
TEST_VIDEO = "tests/Two_puppet_friends_202507101845.mp4"

# Store IDs from uploads
stored_ids = {}

def log_result(test_name, passed, details=""):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {test_name}")
    if details:
        print(f"       {details}")

def poll_job_status(job_id, max_wait=300, interval=5):
    """Poll video job until completion or timeout"""
    start_time = time.time()
    while time.time() - start_time < max_wait:
        response = requests.get(f"{BASE_URL}/api/video/job/{job_id}/status")
        data = response.json()
        status = data.get("status")
        if status in ["SUCCEEDED", "FAILED"]:
            return data
        time.sleep(interval)
    return {"status": "TIMEOUT"}

def run_tests():
    results = {"passed": 0, "failed": 0, "tests": []}

    # Phase 1: Health Check
    try:
        r = requests.get(f"{BASE_URL}/health")
        passed = r.status_code == 200 and r.json().get("status") == "healthy"
        log_result("1.1 Health Check", passed)
        results["passed" if passed else "failed"] += 1
    except Exception as e:
        log_result("1.1 Health Check", False, str(e))
        results["failed"] += 1

    # Phase 2: Upload Tests
    try:
        with open(TEST_IMAGE, "rb") as f:
            r = requests.post(f"{BASE_URL}/api/upload/file", files={"file": f})
        passed = r.status_code in [200, 201] and "file_id" in r.json()
        if passed:
            stored_ids["IMAGE_FILE_ID"] = r.json()["file_id"]
        log_result("2.1 Upload Test Image", passed, f"file_id: {stored_ids.get('IMAGE_FILE_ID')}")
        results["passed" if passed else "failed"] += 1
    except Exception as e:
        log_result("2.1 Upload Test Image", False, str(e))
        results["failed"] += 1

    # Continue with remaining tests...
    # (Implementation continues for all phases)

    print(f"\n{'='*50}")
    print(f"Test Results: {results['passed']} passed, {results['failed']} failed")
    return results

if __name__ == "__main__":
    run_tests()
```

---

## Appendix B: Expected Test Duration

| Phase | Estimated Duration | Notes |
|-------|-------------------|-------|
| Phase 1: Health Check | < 5 seconds | Synchronous |
| Phase 2: File Upload | < 30 seconds | Depends on file size |
| Phase 3: Image Analysis | 1-2 minutes | All synchronous |
| Phase 4: Video Analysis | 5-15 minutes | Async jobs, polling required |
| Phase 5: Face Collections | 2-3 minutes | Mix of sync operations |
| Phase 6: History | < 30 seconds | Database queries |
| Phase 7: Error Handling | < 30 seconds | Quick validation |
| Phase 8: Cleanup | < 30 seconds | Deletion operations |

**Total Estimated Duration:** 10-20 minutes (primarily video analysis)

---

## Appendix C: Required Environment Variables

Ensure these are set in `.env` before testing:

```
AWS_ACCESS_KEY_ID=<your-access-key>
AWS_SECRET_ACCESS_KEY=<your-secret-key>
AWS_REGION=us-east-1
S3_BUCKET_NAME=video-analysis-app-676206912644
FLASK_SECRET_KEY=<generated-key>
DATABASE_PATH=data/app.db
```

---

## Appendix D: Common Failure Scenarios and Troubleshooting

| Issue | Possible Cause | Resolution |
|-------|---------------|------------|
| Connection refused | App not running | Run `python run.py` |
| 403 on S3 operations | Invalid AWS credentials | Check `.env` credentials |
| Rekognition errors | IAM policy missing permissions | Update VideoAnalysisAppPolicy |
| Video job timeout | Large video or slow processing | Increase poll timeout |
| Face not detected | Image quality too low | Use higher quality test image |
| Collection not found | Collection deleted or never created | Create collection first |

---

## Test Completion Checklist

- [ ] Phase 1: All health checks pass
- [ ] Phase 2: Both image and video uploaded successfully
- [ ] Phase 3: All 7 image analysis types tested (excluding custom labels)
- [ ] Phase 4: All 8 video analysis types tested
- [ ] Phase 5: Face collection CRUD operations verified
- [ ] Phase 6: History queries and filtering work
- [ ] Phase 7: Error handling returns appropriate responses
- [ ] Phase 8: All test data cleaned up
