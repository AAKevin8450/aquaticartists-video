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
| batch_splitter_service.py | Split batches by count (150) and size (4.5GB) |
| batch_s3_manager.py | Copy files with sanitized names, cleanup folders |

### Key Routes (app/routes/)
| Route | Key Endpoints |
|-------|---------------|
| nova_analysis.py | /api/nova/analyze, /status, /results, /models, /batch/pending (video) |
| nova_image_analysis.py | /api/nova/image/analyze, /status, /results, /models (image) |
| file_management/ | /api/files, /api/batch/*, /api/files/rescan, /api/files/import-directory |
| search.py | /api/search?semantic=true |
| reports.py | /reports/api/summary, /api/billing/summary, /api/storage/batch, /api/storage/batch/cleanup |

### Frontend
- **Primary UI**: file_management.html (unified file browser with batch operations)
- **JS**: file_management.js, search.js, dashboard.js, nova-dashboard.js, reports.js
- **Dashboards**:
  - dashboard.html routes to nova-dashboard.js for 'nova' and 'nova_image' analysis types
  - nova-dashboard.js handles both video (summary/chapters) and image (description/metadata) rendering
- **Reports**: reports.html (Nova costs + AWS billing + batch storage management)

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
- **Nova filtering**: Only counts analysis_jobs with status='COMPLETED' (filters out pending/failed batch jobs)

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
- **bedrock_batch_jobs**: Aggregated batch submission tracking (batch_job_arn, status, model, nova_job_ids, timestamps, parent_batch_id, chunk_index, total_chunks, s3_folder, cleanup_completed_at)
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
python -m scripts.cleanup_batch_folders --no-dry-run  # Clean completed batch job S3 folders
```

## Critical Implementation Notes

### Bedrock Batch Processing Infrastructure
**Production-ready multi-chunk batch processing with filename sanitization:**

1. **Multi-Chunk Architecture** (app/services/batch_splitter_service.py, batch_s3_manager.py):
   - Splits batches by count (MAX_FILES_PER_BATCH=150) OR size (4.5GB effective limit)
   - Copies proxy files to isolated S3 folders with sanitized filenames
   - Folder structure: `nova_batch/job_YYYYMMDD_HHMMSS_NNN/files/` + `manifest.jsonl`
   - Output: `nova/batch/output/nova_batch/job_YYYYMMDD_HHMMSS_NNN/`
   - **Why not URL encoding**: Bedrock looks for literal keys, encoded keys don't exist in S3

2. **Filename Sanitization** (app/utils/filename_sanitizer.py):
   - sanitize_filename(): Removes spaces→underscores, commas, parentheses, special chars
   - Example: "Video Nov 14 2025, 10 02 14 AM.mov" → "Video_Nov_14_2025_10_02_14_AM.mov"
   - Only sanitizes during batch copy, preserves original filenames in S3

3. **Batch Job Tracking** (app/database/batch_jobs.py):
   - `bedrock_batch_jobs` table tracks aggregated batch submissions
   - **Multi-job fields**: parent_batch_id, chunk_index, total_chunks, s3_folder
   - Links batch_job_arn to array of nova_job_ids for result distribution
   - cleanup_completed_at tracks S3 folder cleanup status

4. **Background Batch Poller** (app/services/batch_poller_service.py):
   - **Automatic polling**: Background thread checks pending Bedrock jobs every 60s
   - **Auto result fetching**: When jobs complete, results are fetched and stored automatically
     - ⚠️ **Critical**: NovaVideoService initialized with bucket_name and region from env vars
     - Calls fetch_batch_results() with correct signature: (s3_prefix, model, analysis_types, options, record_prefix)
     - Parses analysis_types/user_options with type checking (handles both string JSON and parsed values)
     - Stores all result fields: summary/chapters/elements/waterfall_classification/search_metadata
     - Updates both nova_jobs (raw results) and analysis_jobs (compiled results) to COMPLETED
   - **Auto cleanup**: S3 proxy files deleted after successful result storage
   - **Crash recovery**: On startup, checks for orphaned jobs that completed while app was down
   - **Configuration**: Environment variables in .env
     - `BATCH_POLLER_ENABLED=true` - Enable/disable poller
     - `BATCH_POLLER_INTERVAL=60` - Seconds between poll cycles
     - `BATCH_CHECK_INTERVAL=30` - Seconds before rechecking same job
     - `BATCH_AUTO_CLEANUP=true` - Enable automatic S3 cleanup
     - `BATCH_RESULT_FETCH_MAX_RETRIES=3` - Max retries for result fetching
   - **Admin API endpoints** (app/routes/nova_analysis.py):
     - `GET /api/nova/batch/poller/status` - Get poller status and stats
     - `POST /api/nova/batch/poller/start` - Manually start poller
     - `POST /api/nova/batch/poller/stop` - Manually stop poller
     - `POST /api/nova/batch/poller/process-completed` - Manually trigger processing
   - **Database tracking**: New columns in bedrock_batch_jobs
     - `results_fetched_at` - When results were successfully fetched
     - `results_fetch_attempts` - Retry counter for failed fetches
     - `last_error` - Last error message for debugging

5. **Status Caching** (app/routes/file_management/batch.py, nova_analysis.py):
   - get_batch_status() checks Bedrock job completion with intelligent caching
   - ⚠️ **Critical**: Only updates status to IN_PROGRESS or FAILED, never COMPLETED
     - COMPLETED status reserved for batch poller after results are fetched
     - Checks results_fetched_at to determine if job can be marked complete
     - Prevents premature COMPLETED status that would bypass result fetching
   - Bedrock status cache: 30s for in-progress, permanent for completed/failed
   - Reduces Bedrock GetBatchJob API calls by ~95%

6. **Batch Result Parsing** (app/services/nova_service.py):
   - fetch_batch_results() accepts .jsonl.out extension (AWS Bedrock batch output format)
   - Must parse search_metadata from batch outputs for semantic search
   - Stored in nova_jobs.search_metadata as JSON

7. **S3 Cleanup Service** (app/services/batch_cleanup_service.py, batch_s3_manager.py):
   - **Automatic cleanup**: Background poller triggers cleanup after successful result fetch
   - cleanup_completed_batch_jobs(): Cleans s3_folder-based jobs after completion
   - Legacy cleanup_old_batch_files(): For old batch_input_*.jsonl files
   - **UI Access**: Reports page → "Batch Processing Storage" section
   - **CLI**: `python -m scripts.cleanup_batch_folders --no-dry-run`

8. **Retry Logic** (app/routes/nova_analysis.py, batch_poller_service.py):
   - Exponential backoff for S3 result fetching (max 3 retries, 2-10s delay)
   - Updates job status to RESULT_FETCH_FAILED if exhausted
   - Transient errors (throttling, service unavailable) trigger automatic retry
   - Permanent errors (resource not found, access denied) fail job immediately

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
