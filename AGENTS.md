# AGENTS

Last Updated: 2025-12-19 21:43:06

Nova batch processing
- Enable async batch mode by setting `BEDROCK_BATCH_ROLE_ARN`, `NOVA_BATCH_INPUT_PREFIX`, `NOVA_BATCH_OUTPUT_PREFIX` in `.env`.
- Batch submissions use Bedrock batch jobs; results are finalized when `/api/nova/status/<nova_job_id>` is polled.
- Batch cost estimates apply a 50% discount and are surfaced in the Nova UI.

Nova transcription & embeddings
- Transcription supports `whisper` (local) and `nova_sonic` (Bedrock) providers; Nova Sonic requires S3 access.
- Configure Nova Sonic with `NOVA_SONIC_MODEL_ID`, `NOVA_SONIC_RUNTIME_ID`, and `NOVA_SONIC_MAX_TOKENS`.
- Embeddings are generated via `/api/nova/embeddings/generate` and stored in sqlite-vec tables.
- Configure embeddings with `NOVA_EMBED_MODEL_ID`, `NOVA_EMBED_DIMENSION`, `NOVA_EMBED_REQUEST_FORMAT`, and optional `SQLITE_VEC_PATH`; run `migrations/006_add_nova_embeddings.sql`.

Nova model keys
- Preview models are exposed as `pro_2_preview` (Nova 2 Pro) and `omni_2_preview` (Nova 2 Omni).
- Nova 2 Lite runtime calls require the inference profile `us.amazon.nova-2-lite-v1:0` while reporting uses `amazon.nova-2-lite-v1:0`.
- Nova pricing estimates are aligned to the latest published per-1K token rates in `NovaVideoService.MODEL_CONFIG`.

Database
- Run `migrations/003_add_nova_batch_fields.sql` to add batch metadata fields to `nova_jobs`.

Local-first file handling
- Uploads are stored locally in `./uploads` with a flat naming scheme: `originalname_<file_id>.ext`.
- Video uploads create local proxies in `proxy_video` named `originalname_<source_file_id>_<proxy_spec>.ext`; `proxy_spec` is stored in proxy file metadata.
- Direct S3 uploads are disabled; files may have `s3_key` set to NULL for local-only records.
- File Management supports directory import via `/api/files/import-directory`, scanning recursively without moving source files.
- File Management batch actions use a modal with configurable options; Nova models can be pulled from `/api/nova/models`.

Runtime & operations
- Flask dev server runs on port 5700; database is SQLite at `data/app.db`.
- Local transcription requires FFmpeg available in PATH (GPU optional for speed).
- Rekognition Person Tracking may fail with AccessDenied despite correct IAM permissions (AWS account-level restriction).
- Batch proxy processing runs inside the Flask app context for background workers.
