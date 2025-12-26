# Project-Specific Instructions for Claude Code

## Project Overview
AWS Video & Image Analysis Application - Flask web app (port 5700) using Amazon Rekognition, Bedrock Nova, faster-whisper transcription, and semantic search (Nova Embeddings).

## Quick Start
```bash
cd E:\coding\video && .\.venv\Scripts\activate && python run.py
```

## AWS Configuration
- **S3 Bucket**: video-analysis-app-676206912644 (us-east-1)
- **IAM Policy**: VideoAnalysisAppPolicy v3 (31 Rekognition + 4 Bedrock actions)

### Environment Variables (.env)
```
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION=us-east-1
S3_BUCKET_NAME, FLASK_SECRET_KEY, DATABASE_PATH=data/app.db
SQLITE_VEC_PATH=path\to\vec0.dll, NOVA_EMBED_DIMENSION=1024
```

## Architecture

### Stack
- **Database**: SQLite (data/app.db), foreign keys enabled, LEFT JOIN optimized
- **Storage**: AWS S3 (presigned URLs)
- **Proxy**: NVENC GPU encoding, stored in proxy_video/{name}_{source_file_id}_720p15.{ext}

### Key Services (app/services/)
| Service | Purpose |
|---------|---------|
| s3_service.py | File upload/download |
| rekognition_video.py | Async video analysis (8 types) |
| rekognition_image.py | Sync image analysis (8 types) |
| transcription_service.py | Local faster-whisper (6 models) |
| nova_service.py | Bedrock video analysis (summary/chapters/elements/waterfall) |
| nova_transcript_summary_service.py | Nova 2 Lite transcript summaries (<=1000 chars) |
| nova_embeddings_service.py | Semantic search vectors (1024 dim) |
| face_collection_service.py | Face collection management |
| rescan_service.py | Folder rescan with fingerprint matching |

### Key Routes (app/routes/)
| Route | Key Endpoints |
|-------|---------------|
| nova_analysis.py | /api/nova/analyze, /status, /results, /models |
| file_management.py | /api/files, /api/batch/*, /api/files/rescan |
| search.py | /api/search?semantic=true |
| transcription.py | /api/scan, /api/start-batch |

### Frontend
- **Primary UI**: file_management.html (unified file browser with batch operations)
- **JS**: file_management.js, search.js, dashboard.js (Chart.js)

## Key Features

### Batch Operations
- Fetch all filtered files (500/request), real-time progress with ETA
- Action types: proxy, transcribe, transcript-summary, nova, rekognition

### Folder Rescan
- Fingerprint matching (filename + size + mtime) preserves analysis data for moved files
- Two-step: scan → review → apply
- Endpoints: POST /api/files/rescan, /api/files/rescan/apply, /api/files/system-browse

### Search
- **Keyword**: UNION across files, transcripts, Rekognition, Nova (summary/chapters/elements/waterfall/search_metadata), collections
- **Semantic**: Nova Embeddings with sqlite-vec KNN (sub-500ms)
- **Optimized for**: Customer/project names, location (city/state/site), waterfall type/family/tier, product names, video type (tutorial/demo/review), building techniques, job codes

### Nova Analysis
- 4 types: summary, chapters, elements, waterfall_classification
- 3 models: Lite ($0.06/1K), Pro ($0.80/1K), Premier ($2.00/1K)
- Videos < 30 min supported
- Context-aware: Uses filename, path, transcript summary to enhance analysis accuracy
- Returns search_metadata (project/location/customer/content type/entities/keywords) for discovery

## Database Tables
- **files**: S3-uploaded files with metadata
- **transcripts**: Text, segments, transcript_summary, video metadata
- **analysis_jobs/nova_jobs**: Job tracking with cost
- **nova_jobs**: summary_result, chapters_result, elements_result, waterfall_classification_result, search_metadata
- **nova_embeddings**: sqlite-vec vectors

## Constraints
- Video: Max 10GB (MP4, MOV, AVI, MKV) | Image: Max 15MB (JPEG, PNG)
- Region: us-east-1 only
- FFmpeg required (NVENC for GPU proxy)

## Known Issues
- Rekognition Person Tracking: AccessDeniedException (AWS account restriction)

## Debug Commands
```bash
python -m scripts.backfill_embeddings --force --limit 100
python -m scripts.backfill_transcript_summaries --dry-run
python -m scripts.reconcile_proxies --no-dry-run --delete-orphans --yes
```
