# Project-Specific Instructions for Claude Code

## Project Overview
AWS Video & Image Analysis Application - Flask-based web app using Amazon Rekognition (8 video + 8 image analysis types), Amazon Bedrock Nova (summary, chapters, elements), face collections, local transcription (faster-whisper), and semantic search (Nova Embeddings).

## Quick Start
```bash
cd E:\coding\video && .\.venv\Scripts\activate && python run.py
# Access at http://localhost:5700
```

## AWS Configuration
- **S3 Bucket**: video-analysis-app-676206912644 (us-east-1)
- **IAM Policy**: VideoAnalysisAppPolicy v3 (31 Rekognition + 4 Bedrock actions)
- **CORS**: localhost:5700, 127.0.0.1:5700

### Environment Variables (.env)
```
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION=us-east-1
S3_BUCKET_NAME=video-analysis-app-676206912644
FLASK_SECRET_KEY, DATABASE_PATH=data/app.db
SQLITE_VEC_PATH=C:\path\to\vec0.dll  # For semantic search
NOVA_EMBED_MODEL_ID, NOVA_EMBED_DIMENSION=1024
NOVA_SONIC_DEBUG=1  # Debug transcription
```

## Architecture

### Application Stack
- **Port**: 5700 (Flask)
- **Database**: SQLite (data/app.db) with LEFT JOIN optimization (sub-200ms for 10k+ files)
- **Storage**: AWS S3 (presigned URLs)
- **Proxy Encoding**: NVENC GPU (h264_nvenc) for 3-5x faster proxy creation

### Key Services
| Service | File | Purpose |
|---------|------|---------|
| S3 | app/services/s3_service.py | File upload/download |
| Rekognition Video | app/services/rekognition_video.py | Async video analysis |
| Rekognition Image | app/services/rekognition_image.py | Sync image analysis |
| Transcription | app/services/transcription_service.py | Local faster-whisper |
| Nova Analysis | app/services/nova_service.py | Bedrock video analysis (Lite/Pro/Premier) |
| Nova Sonic | app/services/nova_transcription_service.py | Cloud transcription |
| Nova Embeddings | app/services/nova_embeddings_service.py | Semantic search vectors (1024 dim) |
| Face Collections | app/services/face_collection_service.py | Face management |

### Key Routes
| Blueprint | File | Key Endpoints |
|-----------|------|---------------|
| Analysis | app/routes/analysis.py | Multi-select analysis (1-8 types) |
| Nova | app/routes/nova_analysis.py | /api/nova/analyze, /status, /results, /models |
| File Mgmt | app/routes/file_management.py | Batch ops (proxy, transcribe, nova, rekognition) |
| Search | app/routes/search.py | /api/search?semantic=true, /api/search/count, /api/search/filters |
| Transcription | app/routes/transcription.py | /api/scan, /api/start-batch, /api/batch-status |

### Frontend
**Primary UI**: File Management (`file_management.html`) - Unified interface for all processing
**Templates**: index.html (dashboard), search.html, upload.html, history.html, dashboard.html (charts), collections.html
**JavaScript**: utils.js, dashboard.js (Chart.js), file_management.js, search.js

## Key Features

### Batch Operations
- Fetch ALL filtered files across pages (500/request)
- Real-time progress metrics (size, ETA)
- Nova batch requires 100+ files minimum

### Search System
- **Keyword**: UNION query across 5 sources (files, transcripts, Rekognition, Nova, collections)
- **Semantic**: Nova Embeddings with sqlite-vec KNN (sub-500ms)
- 7 database indexes for performance

### Transcription
- **Local**: faster-whisper (6 models: tiny→large-v3), GPU optional
- **Cloud**: Nova Sonic via Bedrock
- Multi-model support per video, word-level timestamps
- Processing: GPU ~5-10x realtime, CPU ~1-2x realtime

### Nova Analysis (Phase 1 Complete)
- 4 analysis types: summary, chapters, elements, waterfall_classification
- 3 models: Lite ($0.06/1K), Pro ($0.80/1K), Premier ($2.00/1K)
- Videos < 30 min supported (chunking in Phase 2)
- Cost tracking per analysis
- **Waterfall Classification**: Uses structured prompt with 4-step decision process (Family→Functional Type→Tier Level→Sub-Type), evidence hierarchy ranking, confidence thresholds, and spec validation. See docs/Nova_Waterfall_Classification_Decision_Tree.md and docs/Nova_Waterfall_Classification_Spec.json

### Video Dashboard
- Chart.js visualizations at /dashboard/<job_id>
- Analysis-type-specific processors (9 total)
- Excel/JSON export

## Database Schema

### Key Tables
- **files**: S3-uploaded files with metadata
- **transcripts**: 25 fields (path, model, text, segments, video metadata)
- **analysis_jobs**: Rekognition job tracking
- **nova_jobs**: Nova analysis with cost tracking
- **nova_embeddings**: sqlite-vec vectors (1024 dim)
- **nova_embedding_metadata**: source_type, source_id, content_hash

### Indexes (7 search-critical)
```sql
idx_files_name, idx_files_created_at
idx_transcripts_text, idx_transcripts_file_name, idx_transcripts_created_at
idx_analysis_jobs_analysis_type, idx_analysis_jobs_created_at
```

## Constraints
- Video: Max 10GB (MP4, MOV, AVI, MKV)
- Image: Max 15MB (JPEG, PNG)
- Region: us-east-1 only
- FFmpeg required (NVENC for GPU proxy)
- Timezone: Eastern Time (tzdata on Windows)

## Known Issues
- **Rekognition Person Tracking**: AccessDeniedException (AWS account restriction)

## Security
- .env not in git
- S3 no public access
- Presigned URLs with short expiration
- IAM least privilege

## Semantic Search Setup
1. Download sqlite-vec from https://github.com/asg017/sqlite-vec/releases
2. Set SQLITE_VEC_PATH in .env
3. Enable nova-2-multimodal-embeddings-v1:0 in Bedrock console
4. Run backfill: `python -m scripts.backfill_embeddings`

## Debug Commands
```bash
# Nova Sonic debug
set NOVA_SONIC_DEBUG=1

# Backfill embeddings
python -m scripts.backfill_embeddings --force --limit 100
```

## Documentation References
- Nova Implementation Plan: 20251218NovaImplementation.md (6,300+ lines)
- NovaVideoIndex Schema v1.1 for pool/landscape video analysis
