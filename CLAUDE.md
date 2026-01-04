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
| batch_cleanup_service.py | S3 cleanup for old batch input/output files |

### Key Routes (app/routes/)
| Route | Key Endpoints |
|-------|---------------|
| nova_analysis.py | /api/nova/analyze, /status, /results, /models, /batch/pending (video) |
| nova_image_analysis.py | /api/nova/image/analyze, /status, /results, /models (image) |
| file_management/ | /api/files, /api/batch/*, /api/files/rescan, /api/files/import-directory |
| search.py | /api/search?semantic=true |
| reports.py | /reports/api/summary, /api/billing/summary |

### Frontend
- **Primary UI**: file_management.html (unified file browser with batch operations)
- **JS**: file_management.js, search.js, dashboard.js, nova-dashboard.js, reports.js
- **Dashboards**:
  - dashboard.html routes to nova-dashboard.js for 'nova' and 'nova_image' analysis types
  - nova-dashboard.js handles both video (summary/chapters) and image (description/metadata) rendering
- **Reports**: reports.html (Nova costs + AWS billing breakdown)

## Key Features

### Batch Operations
- Fetch all filtered files (500/request), real-time progress with ETA
- Action types: proxy (unified for videos+images), transcribe, transcript-summary, nova, embeddings
- **Unified Proxy Generation**: Single "Generate Proxies" button handles both videos (720p/15fps FFmpeg) and images (896px Pillow)
  - Mixed batch support with file type routing
  - Separate progress tracking for videos vs images (completed/failed counts, sizes)
  - Dynamic progress modal title adapts to batch composition

### Folder Rescan & Directory Import
- Async operations with progress tracking, ETA, cancellation
- Fingerprint matching preserves analysis data for moved files
- Rescan can import new files directly (select files → Apply Changes)
- Endpoints: POST → job_id, GET /status, POST /cancel, POST /apply

### Search
- **Keyword**: UNION across files, transcripts, Nova results
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
- **analysis_jobs**: Job tracking (job_id, status, **results** - compiled for dashboard display)
- **nova_jobs**: Raw results (summary/chapters/elements/waterfall/description), search_metadata, raw_response, content_type (video/image)
  - ⚠️ **Important**: Image analysis must populate BOTH nova_jobs (raw) AND analysis_jobs.results (compiled) for dashboard display
  - **Batch fields**: batch_mode, batch_job_arn, batch_status, batch_input_s3_key, batch_output_s3_prefix
- **bedrock_batch_jobs**: Aggregated batch submission tracking (batch_job_arn, status, model, nova_job_ids, timestamps)
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
python -m scripts.backfill_image_analysis_results --no-dry-run  # Fix image jobs missing analysis_jobs.results
python -m scripts.backfill_video_thumbnails --no-dry-run  # Generate thumbnails for existing video proxies
python -m scripts.cleanup_batch_files --no-dry-run --retention-days 7  # Clean old S3 batch files
```

## Critical Implementation Notes

### Bedrock Batch Processing Infrastructure
**Production-ready batch processing with tracking, caching, and cleanup:**

1. **Batch Job Tracking** (app/database/batch_jobs.py):
   - `bedrock_batch_jobs` table tracks aggregated batch submissions
   - Links batch_job_arn to array of nova_job_ids for result distribution
   - Stores I/O S3 paths (input_s3_key, output_s3_prefix) for cleanup
   - Tracks submission, completion, last_checked timestamps

2. **Intelligent Status Polling** (app/routes/nova_analysis.py:617-717):
   - 30-second cache for in-progress jobs (`should_check_bedrock_batch_status()`)
   - Permanent cache for completed/failed jobs (never re-check AWS)
   - Reduces Bedrock GetBatchJob API calls by ~95%
   - Cache invalidation via `mark_bedrock_batch_checked()`

3. **Search Metadata Parsing** (app/services/nova_service.py:746-763):
   - **Critical**: `fetch_batch_results()` must parse search_metadata from batch outputs
   - Structure: {project, location, content, keywords, dates}
   - Enables semantic search for batch-analyzed videos
   - Stored in nova_jobs.search_metadata as JSON

4. **S3 Cleanup Service** (app/services/batch_cleanup_service.py):
   - Automated cleanup of old batch JSONL input/output files
   - Default retention: 7 days (completed), 30 days (active jobs)
   - Dry-run mode with size/cost reporting
   - CLI: `python -m scripts.cleanup_batch_files --no-dry-run`

5. **Retry Logic** (app/routes/nova_analysis.py:24-40):
   - Exponential backoff for S3 result fetching (max 3 retries, 2-10s delay)
   - Handles transient S3 failures during batch result retrieval
   - Updates job status to RESULT_FETCH_FAILED if exhausted

6. **Pending Jobs Endpoint** (GET /api/nova/batch/pending):
   - Returns all in-progress Bedrock batch jobs
   - Auto-refreshes stale statuses (>60s since last check)
   - Useful for monitoring large batch submissions

### Nova Image Analysis Results Storage
**Must populate both tables for dashboard display:**

1. **nova_jobs table** (raw storage):
   - description_result, elements_result, waterfall_classification_result, search_metadata
   - Stored as JSON strings

2. **analysis_jobs.results** (compiled for dashboard):
   ```python
   compiled_results = {
       'content_type': 'image',
       'model': model,
       'analysis_types': analysis_types,
       'totals': {'tokens_total', 'cost_total_usd', 'processing_time_seconds'},
       'description': {...},
       'elements': {...},
       'waterfall_classification': {...},
       'metadata': {...}
   }
   db.update_analysis_job(analysis_job_id, status='COMPLETED', results=compiled_results)
   ```

**Dashboard routing** (app/templates/dashboard.html):
- Uses `analysisType.startsWith('nova')` to handle both 'nova' and 'nova_image'
- Routes to nova-dashboard.js which detects `content_type` field to render appropriately

### Thumbnail Preview in Nova Dashboard
**Automatic thumbnail generation for visual preview:**

1. **Video Proxies** (app/routes/upload.py:132-158,579-596):
   - `_extract_thumbnail_from_proxy()` extracts middle frame using FFmpeg
   - Saved as `proxy_video/{name}_{file_id}_thumbnail.jpg` (320px wide JPEG)
   - Stored in `proxy.metadata.thumbnail_path`
   - Auto-generated during proxy creation

2. **Image Proxies** (app/routes/upload.py:761):
   - Uses existing proxy image as thumbnail (896px Nova-optimized version)
   - `metadata.thumbnail_path = proxy_local_path`

3. **Dashboard Display** (app/templates/dashboard.html:374-422, app/static/js/nova-dashboard.js:84-113):
   - Fetches thumbnail via `/api/files/{file_id}` endpoint
   - Shows in responsive col-lg-3 card with stats beside it
   - Clickable to open full proxy in new tab
   - Auto-hides if no thumbnail available
