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
BILLING_BUCKET_NAME=aquaticartists-billing-reports (optional)
BILLING_CUR_PREFIX=/hourly_reports/ (optional)
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
| billing_service.py | AWS CUR Parquet parsing, cost aggregation by service/date |
| face_collection_service.py | Face collection management |
| rescan_service.py | Async folder rescan with progress tracking |
| import_service.py | Async directory import with progress tracking |

### Key Routes (app/routes/)
| Route | Key Endpoints |
|-------|---------------|
| nova_analysis.py | /api/nova/analyze, /status, /results, /models |
| file_management.py | /api/files, /api/batch/*, /api/files/rescan, /api/files/import-directory |
| search.py | /api/search?semantic=true |
| transcription.py | /api/scan, /api/start-batch |
| reports.py | /reports/api/summary, /api/billing/summary |

### Frontend
- **Primary UI**: file_management.html (unified file browser with batch operations)
- **JS**: file_management.js, search.js, dashboard.js (Chart.js), reports.js
- **Reports**: reports.html (Nova costs + AWS billing breakdown)

## Key Features

### Batch Operations
- Fetch all filtered files (500/request), real-time progress with ETA
- Action types: proxy, transcribe, transcript-summary, nova, rekognition

### Folder Rescan (Async with Progress)
- Fingerprint matching (filename + size + mtime) preserves analysis data for moved files
- Real-time progress: "Scanning filesystem... (234 / 1,247 files) - ~45s remaining"
- Two-step: async scan → review → apply
- Endpoints: POST /api/files/rescan → job_id, GET /status, POST /cancel, POST /apply

### Directory Import (Async with Progress)
- Import local files without S3 upload, preserving metadata
- Real-time stats: "Importing... (180 imported, 40 existing, 14 unsupported)"
- Progress bar with ETA, cancellation support
- Endpoints: POST /api/files/import-directory → job_id, GET /status, POST /cancel

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

### AWS Billing Reports
- Real-time cost data from AWS CUR Parquet files in S3
- Service breakdown with 4-decimal precision ($4.0100)
- Daily cost chart with labels, grid lines, and date markers
- Cached for fast queries (<50ms), manual refresh from S3
- Only uses latest CUR file per month (cumulative data, avoids 7x duplicate counting bug)

## Database Tables
- **files**: S3-uploaded files with metadata
- **transcripts**: Text, segments, transcript_summary, video metadata (indexed on file_path for performance)
- **analysis_jobs/nova_jobs**: Job tracking with cost
- **nova_jobs**: summary_result, chapters_result, elements_result, waterfall_classification_result, search_metadata, raw_response (full API responses)
- **nova_embeddings**: sqlite-vec vectors
- **billing_cache**: Pre-aggregated costs by service + date, unique index on (service_code, usage_date)
- **billing_sync_log**: S3 sync tracking (status, records_processed, error_message)
- **rescan_jobs**: Async folder rescan tracking (status, progress, files_scanned, results)
- **import_jobs**: Async directory import tracking (status, progress, imported/skipped counts, errors)

## Constraints
- Video: Max 10GB (MP4, MOV, AVI, MKV) | Image: Max 15MB (JPEG, PNG)
- Region: us-east-1 only
- FFmpeg required (NVENC for GPU proxy)

## Known Issues
- Rekognition Person Tracking: AccessDeniedException (AWS account restriction)
- **FIXED (2025-12-27)**: Nova batch failures with Windows paths - regex pattern bug in escape sequence fixing logic caused 14% failure rate. Fixed by changing regex replacement strings from raw to regular strings in `nova_service.py:1078-1089`.

## Debug Commands
```bash
python -m scripts.backfill_embeddings --force --limit 100
python -m scripts.backfill_transcript_summaries --dry-run
python -m scripts.reconcile_proxies --no-dry-run --delete-orphans --yes
python -m scripts.analyze_nova_failures  # Analyze failed Nova jobs using raw responses
python -m scripts.estimate_chunked_response_size  # Estimate DB size impact of raw storage
```
