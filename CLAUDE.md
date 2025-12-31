# Project-Specific Instructions for Claude Code

## Project Overview
AWS Video & Image Analysis Application - Flask web app (port 5700) using Bedrock Nova for video/image analysis, faster-whisper transcription, and semantic search (Nova Embeddings).

## Quick Start
```bash
cd E:\coding\video && .\.venv\Scripts\activate && python run.py
```

## AWS Configuration
- **S3 Bucket**: video-analysis-app-676206912644 (us-east-1)
- **IAM Policy**: VideoAnalysisAppPolicy v3 (Bedrock + S3 actions)

### Environment Variables (.env)
```
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION=us-east-1
S3_BUCKET_NAME, FLASK_SECRET_KEY, DATABASE_PATH=data/app.db
SQLITE_VEC_PATH=path\to\vec0.dll, NOVA_EMBED_DIMENSION=1024
BILLING_BUCKET_NAME, BILLING_CUR_PREFIX=/hourly_reports/ (optional)
```

## Architecture

### Stack
- **Database**: SQLite (data/app.db), foreign keys enabled
- **Storage**: AWS S3 (presigned URLs)
- **Proxy**:
  - Video: NVENC GPU encoding → proxy_video/{name}_{source_file_id}_720p15.{ext}
  - Image: Pillow/Lanczos resize → proxy_image/{name}_{source_file_id}_nova.{ext} (896px shorter side for Nova 2 Lite)

### Key Services (app/services/)
| Service | Purpose |
|---------|---------|
| s3_service.py | File upload/download |
| image_proxy_service.py | Image proxy creation for Nova 2 Lite (896px) |
| transcription_service.py | Local faster-whisper (6 models) |
| nova_service.py | Bedrock video analysis (summary/chapters/elements/waterfall) |
| nova_image_service.py | Bedrock image analysis with EXIF extraction (description/elements/waterfall/metadata) |
| nova_embeddings_service.py | Semantic search vectors (1024 dim) |
| billing_service.py | AWS CUR Parquet parsing, cost aggregation |

### Key Routes (app/routes/)
| Route | Key Endpoints |
|-------|---------------|
| nova_analysis.py | /api/nova/analyze, /status, /results, /models (video) |
| nova_image_analysis.py | /api/nova/image/analyze, /status, /results, /models (image) |
| file_management/ | /api/files, /api/batch/*, /api/files/rescan, /api/files/import-directory |
| search.py | /api/search?semantic=true |
| reports.py | /reports/api/summary, /api/billing/summary |

### Frontend
- **Primary UI**: file_management.html (unified file browser with batch operations)
- **JS**: file_management.js, search.js, dashboard.js, reports.js
- **Reports**: reports.html (Nova costs + AWS billing breakdown)

## Key Features

### Batch Operations
- Fetch all filtered files (500/request), real-time progress with ETA
- Action types: proxy, image-proxy, transcribe, transcript-summary, nova, embeddings

### Folder Rescan & Directory Import
- Async operations with progress tracking, ETA, cancellation
- Fingerprint matching preserves analysis data for moved files
- Endpoints: POST → job_id, GET /status, POST /cancel, POST /apply

### Search
- **Keyword**: UNION across files, transcripts, Nova results, collections
- **Semantic**: Nova Embeddings with sqlite-vec KNN (sub-500ms)

### Nova Analysis
- **Video**: 4 types (summary, chapters, elements, waterfall_classification)
  - 3 models: Lite, Pro, Premier | Videos < 30 min
  - Extended timeout: 600s read with 3 retries for large videos
  - Metadata extraction from file paths, filenames, transcripts, visual content
- **Image**: 4 types (description, elements, waterfall_classification, metadata)
  - 3 models: Lite ($0.00006/image), Pro, Premier
  - EXIF metadata extraction (GPS, capture date, camera info)
  - Single combined API call for all analysis types (cost-efficient)
  - Processing time: 5-15s typical
- **Source attribution**: All extracted metadata includes source (path/filename/transcript/visual/exif) and confidence scores

### AWS Billing Reports
- Real-time CUR data with expandable operation-level detail
- Model-specific Bedrock breakdowns (input/output tokens)
- Dual filter toggles: "Hide $0 cost" / "Hide 0 usage"
- **Note**: CUR is cumulative month-to-date; uses latest date only. Token units stored in thousands (× 1000 for display)

## Database Tables
- **files**: Metadata (duration, resolution, codec, bitrate)
- **transcripts**: Text, segments, transcript_summary
- **nova_jobs**: Results (summary/chapters/elements/waterfall/description), search_metadata, raw_response, content_type (video/image)
- **nova_embeddings**: sqlite-vec vectors
- **billing_cache/billing_cache_details**: Cost aggregation by service/operation/date
- **rescan_jobs/import_jobs**: Async job tracking

## Constraints
- Video: Max 10GB (MP4, MOV, AVI, MKV) | Image: Max 15MB (JPEG, PNG)
- Region: us-east-1 only | FFmpeg required (NVENC for GPU proxy)

## Debug Commands
```bash
python -m scripts.backfill_embeddings --force --limit 100
python -m scripts.backfill_transcript_summaries --dry-run
python -m scripts.reconcile_proxies --no-dry-run --delete-orphans --yes
python -m scripts.create_image_proxies --no-dry-run --limit 100
python -m scripts.analyze_nova_failures
```
