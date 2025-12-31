"""
Batch processing endpoints and workers.

Routes:
- POST /api/batch/proxy - Batch proxy creation
- POST /api/batch/transcribe - Batch transcription
- POST /api/batch/transcript-summary - Batch transcript summary
- POST /api/batch/nova - Batch Nova analysis
- POST /api/batch/embeddings - Batch embeddings generation
- GET /api/batch/<job_id>/status - Get batch job status
- POST /api/batch/<job_id>/cancel - Cancel batch job
"""
from flask import Blueprint, request, jsonify, current_app
from app.database import get_db
from pathlib import Path
import threading
import uuid
import time
import os

from app.routes.file_management.shared import (
    BatchJob,
    get_batch_job,
    set_batch_job,
    normalize_transcription_provider,
    select_latest_completed_transcript,
)

bp = Blueprint('batch', __name__)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def _convert_filter_param(value):
    """Convert filter parameter to proper boolean or None."""
    if value is None or value == '' or value == 'null':
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes')
    return bool(value)


# ============================================================================
# BATCH ENDPOINTS
# ============================================================================

@bp.route('/api/batch/proxy', methods=['POST'])
def batch_create_proxy():
    """
    Create proxies for specified files (from currently filtered view).

    Request body:
        {
            "file_ids": [1, 2, 3, ...]  # List of file IDs to process
        }

    Returns:
        {
            "job_id": "batch-xxx",
            "total_files": 10,
            "message": "Batch proxy creation started"
        }
    """
    try:
        data = request.get_json() or {}
        current_app.logger.info(f"Batch proxy request received with data: {data}")

        # Get file IDs from request
        file_ids = data.get('file_ids', [])

        if not file_ids:
            current_app.logger.warning("No file IDs provided")
            return jsonify({'error': 'No file IDs provided'}), 400

        current_app.logger.info(f"Processing batch proxy for {len(file_ids)} file IDs")

        # Validate files exist and are eligible for proxy creation
        db = get_db()
        eligible_file_ids = []

        for file_id in file_ids:
            file = db.get_file(file_id)
            if not file:
                current_app.logger.warning(f"File {file_id} not found, skipping")
                continue

            # Check if it's a video with local path
            if file.get('file_type') != 'video':
                current_app.logger.warning(f"File {file_id} is not a video, skipping")
                continue

            if not file.get('local_path'):
                current_app.logger.warning(f"File {file_id} has no local path, skipping")
                continue

            # Check if proxy already exists
            existing_proxy = db.get_proxy_for_source(file_id)
            if existing_proxy:
                current_app.logger.info(f"File {file_id} already has a proxy, skipping")
                continue

            eligible_file_ids.append(file_id)

        if not eligible_file_ids:
            current_app.logger.warning("No eligible files for proxy creation")
            return jsonify({'error': 'No eligible files for proxy creation (need videos with local paths, without existing proxies)'}), 404

        current_app.logger.info(f"Found {len(eligible_file_ids)} eligible files for proxy creation")

        # Create batch job
        job_id = f"batch-proxy-{uuid.uuid4().hex[:8]}"
        job = BatchJob(job_id, 'proxy', len(eligible_file_ids), eligible_file_ids)

        set_batch_job(job_id, job)

        current_app.logger.info(f"Created batch job {job_id} for {len(eligible_file_ids)} files")

        # Start background thread
        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_batch_proxy, args=(app, job))
        thread.daemon = True
        thread.start()

        current_app.logger.info(f"Started background thread for batch job {job_id}")

        return jsonify({
            'job_id': job_id,
            'total_files': len(eligible_file_ids),
            'message': f'Batch proxy creation started for {len(eligible_file_ids)} file(s)'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Batch proxy error: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return jsonify({'error': f'Batch proxy error: {str(e)}'}), 500


@bp.route('/api/batch/image-proxy', methods=['POST'])
def batch_create_image_proxy():
    """
    Create optimized image proxies for Nova 2 Lite analysis.

    Image proxies are resized to 896px on the shorter side (Nova's minimum threshold),
    reducing S3 storage costs, network transfer time, and API payload sizes.

    Request body:
        {
            "file_ids": [1, 2, 3, ...],
            "force": false  // Recreate even if proxy exists
        }

    Returns:
        {
            "job_id": "batch-image-proxy-xxx",
            "total_files": 10,
            "message": "Batch image proxy creation started"
        }
    """
    try:
        data = request.get_json() or {}
        current_app.logger.info(f"Batch image proxy request received with data: {data}")

        # Get file IDs from request
        file_ids = data.get('file_ids', [])
        force = bool(data.get('force', False))

        if not file_ids:
            current_app.logger.warning("No file IDs provided")
            return jsonify({'error': 'No file IDs provided'}), 400

        current_app.logger.info(f"Processing batch image proxy for {len(file_ids)} file IDs")

        # Validate files exist and are eligible for image proxy creation
        db = get_db()
        eligible_file_ids = []

        for file_id in file_ids:
            file = db.get_file(file_id)
            if not file:
                current_app.logger.warning(f"File {file_id} not found, skipping")
                continue

            # Check if it's an image with local path
            if file.get('file_type') != 'image':
                current_app.logger.warning(f"File {file_id} is not an image, skipping")
                continue

            if not file.get('local_path'):
                current_app.logger.warning(f"File {file_id} has no local path, skipping")
                continue

            # Check if proxy already exists (unless force=True)
            if not force:
                existing_proxy = db.get_proxy_for_source(file_id)
                if existing_proxy:
                    current_app.logger.info(f"File {file_id} already has a proxy, skipping")
                    continue

            eligible_file_ids.append(file_id)

        if not eligible_file_ids:
            current_app.logger.warning("No eligible files for image proxy creation")
            return jsonify({
                'error': 'No eligible files for image proxy creation '
                         '(need images with local paths, without existing proxies unless force=true)'
            }), 404

        current_app.logger.info(f"Found {len(eligible_file_ids)} eligible files for image proxy creation")

        # Create batch job
        job_id = f"batch-image-proxy-{uuid.uuid4().hex[:8]}"
        job = BatchJob(job_id, 'image-proxy', len(eligible_file_ids), eligible_file_ids)
        job.options = {'force': force}

        set_batch_job(job_id, job)

        current_app.logger.info(f"Created batch job {job_id} for {len(eligible_file_ids)} files")

        # Start background thread
        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_batch_image_proxy, args=(app, job))
        thread.daemon = True
        thread.start()

        current_app.logger.info(f"Started background thread for batch job {job_id}")

        return jsonify({
            'job_id': job_id,
            'total_files': len(eligible_file_ids),
            'message': f'Batch image proxy creation started for {len(eligible_file_ids)} file(s)'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Batch image proxy error: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return jsonify({'error': f'Batch image proxy error: {str(e)}'}), 500


@bp.route('/api/batch/transcribe', methods=['POST'])
def batch_transcribe():
    """
    Transcribe specified files (from currently filtered view).

    Request body:
        {
            "file_ids": [1, 2, 3, ...],
            "provider": "whisper",  # whisper or nova_sonic
            "model_size": "medium",
            "language": "en",
            "force": false,
            "device": "auto",
            "compute_type": "default"
        }

    Returns:
        {
            "job_id": "batch-xxx",
            "total_files": 10,
            "message": "Batch transcription started"
        }
    """
    try:
        data = request.get_json() or {}

        # Get file IDs from request
        file_ids = data.get('file_ids', [])

        if not file_ids:
            return jsonify({'error': 'No file IDs provided'}), 400

        # Transcription options
        provider = normalize_transcription_provider(data.get('provider'))
        if provider not in ('whisper', 'nova_sonic'):
            return jsonify({'error': 'Invalid provider. Use whisper or nova_sonic (sonic_2_online).'}), 400

        model_name = data.get('model_size') or data.get('model_name') or current_app.config.get('WHISPER_MODEL_SIZE', 'medium')
        language = data.get('language')
        force = data.get('force', False)
        device = data.get('device') or current_app.config.get('WHISPER_DEVICE', 'auto')
        compute_type = data.get('compute_type') or current_app.config.get('WHISPER_COMPUTE_TYPE', 'default')

        # Validate files exist and are eligible for transcription
        db = get_db()
        eligible_file_ids = []

        for file_id in file_ids:
            file = db.get_file(file_id)
            if not file:
                current_app.logger.warning(f"File {file_id} not found, skipping")
                continue

            # Check if it's a video with local path
            if file.get('file_type') != 'video':
                current_app.logger.warning(f"File {file_id} is not a video, skipping")
                continue

            local_path = file.get('local_path')
            if not local_path or not Path(local_path).exists():
                current_app.logger.warning(f"File {file_id} has no local path, skipping")
                continue

            eligible_file_ids.append(file_id)

        if not eligible_file_ids:
            return jsonify({'error': 'No eligible files for transcription (need videos with local paths)'}), 404

        # Create batch job
        job_id = f"batch-transcribe-{uuid.uuid4().hex[:8]}"
        job = BatchJob(job_id, 'transcribe', len(eligible_file_ids), eligible_file_ids)
        job.options = {
            'provider': provider,
            'model_name': model_name,
            'language': language,
            'force': force,
            'device': device,
            'compute_type': compute_type
        }

        set_batch_job(job_id, job)

        # Start background thread
        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_batch_transcribe, args=(app, job))
        thread.daemon = True
        thread.start()

        return jsonify({
            'job_id': job_id,
            'total_files': len(eligible_file_ids),
            'message': f'Batch transcription started for {len(eligible_file_ids)} file(s)'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Batch transcribe error: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return jsonify({'error': f'Batch transcribe error: {str(e)}'}), 500


@bp.route('/api/batch/transcript-summary', methods=['POST'])
def batch_transcript_summary():
    """
    Generate Nova transcript summaries for specified files.

    Request body:
        {
            "file_ids": [1, 2, 3, ...],
            "force": false  # Overwrite existing transcript summaries
        }
    """
    try:
        data = request.get_json() or {}
        file_ids = data.get('file_ids', [])
        if not file_ids:
            return jsonify({'error': 'No file IDs provided'}), 400

        force = bool(data.get('force', False))

        db = get_db()
        eligible_file_ids = []
        for file_id in file_ids:
            file = db.get_file(file_id)
            if not file:
                current_app.logger.warning(f"File {file_id} not found, skipping")
                continue
            if file.get('file_type') != 'video':
                current_app.logger.warning(f"File {file_id} is not a video, skipping")
                continue

            transcripts = db.get_transcripts_by_file(file_id)
            transcript = select_latest_completed_transcript(transcripts)
            if not transcript:
                current_app.logger.warning(f"File {file_id} has no completed transcript, skipping")
                continue
            if transcript.get('transcript_summary') and not force:
                current_app.logger.info(f"File {file_id} already has transcript summary, skipping")
                continue

            eligible_file_ids.append(file_id)

        if not eligible_file_ids:
            return jsonify({'error': 'No eligible files for transcript summary generation'}), 404

        job_id = f"batch-transcript-summary-{uuid.uuid4().hex[:8]}"
        job = BatchJob(job_id, 'transcript-summary', len(eligible_file_ids), eligible_file_ids)
        job.options = {'force': force}

        set_batch_job(job_id, job)

        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_batch_transcript_summary, args=(app, job))
        thread.daemon = True
        thread.start()

        return jsonify({
            'job_id': job_id,
            'total_files': len(eligible_file_ids),
            'message': f'Batch transcript summary started for {len(eligible_file_ids)} file(s)'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Batch transcript summary error: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return jsonify({'error': f'Batch transcript summary error: {str(e)}'}), 500


@bp.route('/api/batch/nova', methods=['POST'])
def batch_nova():
    """
    Start Nova analysis for specified files (from currently filtered view).

    Request body:
        {
            "file_ids": [1, 2, 3, ...],
            "model": "lite",
            "analysis_types": ["summary", "chapters"],
            "options": {},
            "processing_mode": "realtime"
        }

    Returns:
        {
            "job_id": "batch-xxx",
            "total_files": 10,
            "message": "Batch Nova analysis started"
        }
    """
    try:
        data = request.get_json() or {}

        # Get file IDs from request
        file_ids = data.get('file_ids', [])

        if not file_ids:
            return jsonify({'error': 'No file IDs provided'}), 400

        # Nova options
        model = data.get('model', 'lite')
        analysis_types = data.get('analysis_types', ['summary'])
        options = data.get('options', {})
        processing_mode = data.get('processing_mode', options.get('processing_mode', 'realtime'))
        options['processing_mode'] = processing_mode

        from app.services.nova_service import NovaVideoService
        valid_models = list(NovaVideoService.MODEL_CONFIG.keys())
        if model not in valid_models:
            return jsonify({'error': f'Invalid model: {model}. Choose from: {valid_models}'}), 400

        if processing_mode not in ('realtime', 'batch'):
            return jsonify({'error': 'processing_mode must be "realtime" or "batch"'}), 400

        # Validate files exist (Nova supports both video and image files)
        db = get_db()
        eligible_file_ids = []
        file_types = {}  # Track file types for the batch worker

        for file_id in file_ids:
            file = db.get_file(file_id)
            if not file:
                current_app.logger.warning(f"File {file_id} not found, skipping")
                continue

            file_type = file.get('file_type')
            # Check if it's a video or image
            if file_type not in ('video', 'image'):
                current_app.logger.warning(f"File {file_id} is not a video or image, skipping")
                continue

            local_path = file.get('local_path')
            if not local_path or not Path(local_path).exists():
                current_app.logger.warning(f"File {file_id} has no local path, skipping")
                continue

            eligible_file_ids.append(file_id)
            file_types[file_id] = file_type

        if not eligible_file_ids:
            return jsonify({'error': 'No eligible files for Nova analysis (need videos or images with local paths)'}), 404

        # Create batch job
        job_id = f"batch-nova-{uuid.uuid4().hex[:8]}"
        job = BatchJob(job_id, 'nova', len(eligible_file_ids), eligible_file_ids)
        job.options = {
            'model': model,
            'analysis_types': analysis_types,
            'user_options': options,
            'processing_mode': processing_mode,
            'file_types': file_types  # Track which files are video vs image
        }

        set_batch_job(job_id, job)

        # Start background thread
        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_batch_nova, args=(app, job))
        thread.daemon = True
        thread.start()

        return jsonify({
            'job_id': job_id,
            'total_files': len(eligible_file_ids),
            'message': f'Batch Nova analysis started for {len(eligible_file_ids)} file(s)'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Batch Nova error: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return jsonify({'error': f'Batch Nova error: {str(e)}'}), 500


@bp.route('/api/batch/embeddings', methods=['POST'])
def batch_embeddings():
    """
    Generate Nova Embeddings for specified files (from currently filtered view).

    Request body:
        {
            "file_ids": [1, 2, 3, ...],
            "force": false  # Re-embed even if already exists
        }

    Returns:
        {
            "job_id": "batch-xxx",
            "total_files": 10,
            "message": "Batch embeddings generation started"
        }
    """
    try:
        data = request.get_json() or {}

        # Get file IDs from request
        file_ids = data.get('file_ids', [])

        if not file_ids:
            return jsonify({'error': 'No file IDs provided'}), 400

        # Embeddings options
        force = data.get('force', False)

        # Validate files exist and have transcripts or Nova analysis
        db = get_db()
        eligible_file_ids = []

        for file_id in file_ids:
            file = db.get_file(file_id)
            if not file:
                current_app.logger.warning(f"File {file_id} not found, skipping")
                continue

            # Check if file has transcripts or Nova analysis
            transcripts = db.get_transcripts_by_file(file_id)
            nova_jobs = db.get_nova_jobs_by_file(file_id)

            if not transcripts and not nova_jobs:
                current_app.logger.warning(f"File {file_id} has no transcripts or Nova analysis, skipping")
                continue

            eligible_file_ids.append(file_id)

        if not eligible_file_ids:
            return jsonify({
                'error': 'No eligible files for embeddings (need files with transcripts or Nova analysis)'
            }), 404

        # Create batch job
        job_id = f"batch-embeddings-{uuid.uuid4().hex[:8]}"
        job = BatchJob(job_id, 'embeddings', len(eligible_file_ids), eligible_file_ids)
        job.options = {'force': force}

        set_batch_job(job_id, job)

        # Start background thread
        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_batch_embeddings, args=(app, job))
        thread.daemon = True
        thread.start()

        return jsonify({
            'job_id': job_id,
            'total_files': len(eligible_file_ids),
            'message': f'Batch embeddings generation started for {len(eligible_file_ids)} file(s)'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Batch embeddings error: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return jsonify({'error': f'Batch embeddings error: {str(e)}'}), 500


@bp.route('/api/batch/<job_id>/status', methods=['GET'])
def get_batch_status(job_id: str):
    """
    Get batch job status.

    Returns:
        {
            "job_id": "batch-xxx",
            "status": "RUNNING",
            "progress_percent": 45.5,
            "total_files": 10,
            "completed_files": 4,
            "failed_files": 1,
            "current_file": "video.mp4",
            "elapsed_seconds": 123.4,
            "errors": [...],
            "results": [...]
        }
    """
    try:
        job = get_batch_job(job_id)

        if not job:
            return jsonify({'error': 'Batch job not found'}), 404

        return jsonify(job.to_dict()), 200

    except Exception as e:
        current_app.logger.error(f"Get batch status error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/batch/<job_id>/cancel', methods=['POST'])
def cancel_batch_job(job_id: str):
    """
    Cancel a running batch job.

    Returns:
        {
            "message": "Batch job cancelled"
        }
    """
    try:
        job = get_batch_job(job_id)

        if not job:
            return jsonify({'error': 'Batch job not found'}), 404

        if job.status in ('COMPLETED', 'CANCELLED', 'FAILED'):
            return jsonify({'error': f'Job already {job.status.lower()}'}), 400

        job.status = 'CANCELLED'
        job.end_time = time.time()

        return jsonify({'message': 'Batch job cancelled'}), 200

    except Exception as e:
        current_app.logger.error(f"Cancel batch error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ============================================================================
# BATCH PROCESSING WORKERS
# ============================================================================

def _run_batch_proxy(app, job: BatchJob):
    """Background worker for batch proxy creation."""
    with app.app_context():
        from app.routes.upload import create_proxy_internal
        from pathlib import Path
        import traceback
        import logging

        logger = logging.getLogger('app')
        logger.info(f"Batch proxy worker started for job {job.job_id} with {len(job.file_ids)} files")
        print(f"[BATCH PROXY] Worker started for job {job.job_id} with {len(job.file_ids)} files", flush=True)

        # Calculate total batch size before processing
        db = get_db()
        for file_id in job.file_ids:
            try:
                file = db.get_file(file_id)
                if file and file.get('local_path'):
                    local_path = file['local_path']
                    if Path(local_path).exists():
                        job.total_batch_size += Path(local_path).stat().st_size
            except Exception:
                pass  # Skip files that can't be accessed

        for file_id in job.file_ids:
            if job.status == 'CANCELLED':
                logger.info(f"Batch job {job.job_id} was cancelled")
                print(f"[BATCH PROXY] Job {job.job_id} was cancelled", flush=True)
                break

            try:
                # Get file info
                db = get_db()
                file = db.get_file(file_id)
                if not file:
                    raise Exception(f'File {file_id} not found')

                job.current_file = file['filename']
                logger.info(f"Processing file {file_id}: {file['filename']}")
                print(f"[BATCH PROXY] Processing file {file_id}: {file['filename']}", flush=True)

                # Get source file size for tracking
                source_file_size = 0
                if file.get('local_path') and Path(file['local_path']).exists():
                    source_file_size = Path(file['local_path']).stat().st_size

                # Create proxy (local only, no S3 upload)
                result = create_proxy_internal(file_id, upload_to_s3=False)

                # Track processed source file size
                job.processed_files_sizes.append(source_file_size)

                # Track generated proxy size
                if result.get('size_bytes'):
                    job.total_proxy_size += result['size_bytes']

                job.completed_files += 1
                job.results.append({
                    'file_id': file_id,
                    'filename': file['filename'],
                    'success': True,
                    'result': result
                })
                logger.info(f"Successfully created proxy for file {file_id}: {file['filename']}")
                print(f"[BATCH PROXY] Successfully created proxy for file {file_id}: {file['filename']}", flush=True)

            except Exception as e:
                job.failed_files += 1
                error_msg = str(e)
                tb = traceback.format_exc()
                job.errors.append({
                    'file_id': file_id,
                    'filename': file.get('filename', f'File {file_id}') if file else f'File {file_id}',
                    'error': error_msg
                })

                # Track failed file size too if available
                try:
                    if 'source_file_size' in locals():
                        job.processed_files_sizes.append(source_file_size)
                except Exception:
                    pass

                logger.error(f"Batch proxy error for file {file_id}: {e}", exc_info=True)
                print(f"[BATCH PROXY ERROR] File {file_id}: {e}", flush=True)
                print(f"[BATCH PROXY ERROR] Full traceback:\n{tb}", flush=True)

        # Mark job as complete
        job.status = 'COMPLETED' if job.status != 'CANCELLED' else 'CANCELLED'
        job.end_time = time.time()
        job.current_file = None
        logger.info(
            f"Batch proxy job {job.job_id} completed: {job.completed_files} succeeded, "
            f"{job.failed_files} failed, status: {job.status}"
        )
        print(
            f"[BATCH PROXY] Job {job.job_id} completed: {job.completed_files} succeeded, "
            f"{job.failed_files} failed, status: {job.status}", flush=True
        )


def _run_batch_transcribe(app, job: BatchJob):
    """Background worker for batch transcription."""
    with app.app_context():
        from app.models import TranscriptStatus
        from app.services.transcription_service import create_transcription_service
        from app.utils.media_metadata import extract_media_metadata, MediaMetadataError

        options = job.options or {}
        provider = normalize_transcription_provider(options.get('provider'))
        model_name = options.get('model_name') or current_app.config.get('WHISPER_MODEL_SIZE', 'medium')
        device = options.get('device') or current_app.config.get('WHISPER_DEVICE', 'auto')
        compute_type = options.get('compute_type') or current_app.config.get('WHISPER_COMPUTE_TYPE', 'default')
        language = options.get('language')
        force = bool(options.get('force', False))

        if provider == 'nova_sonic':
            from app.services.nova_transcription_service import create_nova_transcription_service
            model_name = 'nova-2-sonic'
            model_id = current_app.config.get('NOVA_SONIC_MODEL_ID')
            runtime_model_id = current_app.config.get('NOVA_SONIC_RUNTIME_ID', model_id)
            max_tokens = current_app.config.get('NOVA_SONIC_MAX_TOKENS', 8192)
            service = create_nova_transcription_service(
                bucket_name=current_app.config.get('S3_BUCKET_NAME'),
                region=current_app.config.get('AWS_REGION'),
                model_id=model_id,
                runtime_model_id=runtime_model_id,
                aws_access_key=current_app.config.get('AWS_ACCESS_KEY_ID'),
                aws_secret_key=current_app.config.get('AWS_SECRET_ACCESS_KEY'),
                max_tokens=max_tokens
            )
        else:
            service = create_transcription_service(model_name, device, compute_type)

        # Calculate total batch size
        db = get_db()
        for file_id in job.file_ids:
            try:
                file = db.get_file(file_id)
                if file and file.get('local_path'):
                    local_path = file['local_path']
                    if Path(local_path).exists():
                        job.total_batch_size += Path(local_path).stat().st_size
            except Exception:
                pass  # Skip files that can't be accessed

        for file_id in job.file_ids:
            if job.status == 'CANCELLED':
                break

            try:
                # Get file info
                db = get_db()
                file = db.get_file(file_id)
                if not file:
                    raise Exception(f'File {file_id} not found')

                local_path = file.get('local_path')
                if not local_path or not Path(local_path).exists():
                    raise Exception(f'Local file not found: {local_path}')

                job.current_file = file['filename']

                file_size, file_mtime = service.get_file_metadata(local_path)
                existing = db.get_transcript_by_file_info(
                    local_path, file_size, file_mtime, model_name
                )
                if existing and existing['status'] == TranscriptStatus.COMPLETED and not force:
                    job.completed_files += 1
                    job.processed_files_sizes.append(file_size)
                    job.results.append({
                        'file_id': file_id,
                        'filename': file['filename'],
                        'success': True,
                        'transcript_id': existing['id'],
                        'skipped': True
                    })
                    continue

                if existing:
                    transcript_id = existing['id']
                    db.update_transcript_status(transcript_id, TranscriptStatus.IN_PROGRESS)
                else:
                    transcript_id = db.create_transcript(
                        file_path=local_path,
                        file_name=os.path.basename(local_path),
                        file_size=file_size,
                        modified_time=file_mtime,
                        model_name=model_name
                    )

                metadata = {}
                try:
                    metadata = extract_media_metadata(local_path)
                except MediaMetadataError as e:
                    current_app.logger.warning(f"Failed to extract metadata: {e}")

                try:
                    result = service.transcribe_file(local_path, language=language)
                except Exception as e:
                    db.update_transcript_status(
                        transcript_id=transcript_id,
                        status=TranscriptStatus.FAILED,
                        error_message=str(e)
                    )
                    raise

                db.update_transcript_status(
                    transcript_id=transcript_id,
                    status=TranscriptStatus.COMPLETED,
                    transcript_text=result['transcript_text'],
                    character_count=result.get('character_count'),
                    word_count=result.get('word_count'),
                    duration_seconds=result.get('duration_seconds'),
                    segments=result.get('segments'),
                    word_timestamps=result.get('word_timestamps'),
                    language=result.get('language'),
                    confidence_score=result.get('confidence_score'),
                    processing_time=result.get('processing_time_seconds'),
                    resolution_width=metadata.get('resolution_width'),
                    resolution_height=metadata.get('resolution_height'),
                    frame_rate=metadata.get('frame_rate'),
                    codec_video=metadata.get('codec_video'),
                    codec_audio=metadata.get('codec_audio'),
                    bitrate=metadata.get('bitrate')
                )

                job.completed_files += 1
                job.processed_files_sizes.append(file_size)
                job.results.append({
                    'file_id': file_id,
                    'filename': file['filename'],
                    'success': True,
                    'transcript_id': transcript_id,
                    'skipped': False
                })

            except Exception as e:
                job.failed_files += 1
                error_msg = str(e)
                job.errors.append({
                    'file_id': file_id,
                    'filename': file.get('filename', f'File {file_id}'),
                    'error': error_msg
                })
                # Track failed file size too if available
                try:
                    if 'file_size' in locals():
                        job.processed_files_sizes.append(file_size)
                except Exception:
                    pass
                current_app.logger.error(f"Batch transcribe error for file {file_id}: {e}")

        # Mark job as complete
        job.status = 'COMPLETED' if job.status != 'CANCELLED' else 'CANCELLED'
        job.end_time = time.time()
        job.current_file = None


def _run_batch_transcript_summary(app, job: BatchJob):
    """Background worker for batch transcript summary generation."""
    with app.app_context():
        from app.services.nova_transcript_summary_service import NovaTranscriptSummaryService

        options = job.options or {}
        force = bool(options.get('force', False))

        service = NovaTranscriptSummaryService(
            region=current_app.config['AWS_REGION'],
            aws_access_key=current_app.config.get('AWS_ACCESS_KEY_ID'),
            aws_secret_key=current_app.config.get('AWS_SECRET_ACCESS_KEY')
        )

        db = get_db()
        for file_id in job.file_ids:
            try:
                file = db.get_file(file_id)
                if file and file.get('size_bytes'):
                    job.total_batch_size += file['size_bytes']
            except Exception:
                pass

        for file_id in job.file_ids:
            if job.status == 'CANCELLED':
                break

            try:
                db = get_db()
                file = db.get_file(file_id)
                if not file:
                    raise Exception(f'File {file_id} not found')

                job.current_file = file['filename']

                transcripts = db.get_transcripts_by_file(file_id)
                transcript = select_latest_completed_transcript(transcripts)
                if not transcript:
                    raise Exception('No completed transcript found')

                if transcript.get('transcript_summary') and not force:
                    job.completed_files += 1
                    job.processed_files_sizes.append(file.get('size_bytes') or 0)
                    job.results.append({
                        'file_id': file_id,
                        'filename': file['filename'],
                        'transcript_id': transcript['id'],
                        'success': True,
                        'skipped': True
                    })
                    continue

                summary_result = service.summarize_transcript(
                    transcript_text=transcript.get('transcript_text', ''),
                    max_chars=1000
                )
                summary_text = summary_result['summary']
                db.update_transcript_summary(transcript['id'], summary_text)

                # Track token usage
                tokens_used = summary_result.get('tokens_total', 0)
                job.total_tokens += tokens_used
                job.processed_files_tokens.append(tokens_used)

                job.completed_files += 1
                job.processed_files_sizes.append(file.get('size_bytes') or 0)
                job.results.append({
                    'file_id': file_id,
                    'filename': file['filename'],
                    'transcript_id': transcript['id'],
                    'success': True,
                    'summary_length': len(summary_text),
                    'tokens': tokens_used,
                    'was_truncated': summary_result.get('was_truncated', False)
                })

            except Exception as e:
                job.failed_files += 1
                error_msg = str(e)
                job.errors.append({
                    'file_id': file_id,
                    'filename': file.get('filename', f'File {file_id}'),
                    'error': error_msg
                })
                try:
                    job.processed_files_sizes.append(file.get('size_bytes') or 0)
                except Exception:
                    pass
                current_app.logger.error(f"Batch transcript summary error for file {file_id}: {e}")

        job.status = 'COMPLETED' if job.status != 'CANCELLED' else 'CANCELLED'
        job.end_time = time.time()
        job.current_file = None


def _run_batch_nova(app, job: BatchJob):
    """Background worker for batch Nova analysis (supports both video and image files)."""
    with app.app_context():
        from app.routes.nova_analysis import start_nova_analysis_internal
        from app.routes.upload import create_proxy_internal, create_image_proxy_internal
        from app.services.nova_image_service import NovaImageService
        from app.services.s3_service import S3Service
        import tempfile
        import os
        import json

        options = job.options or {}
        model_key = options.get('model', 'lite')
        analysis_types = options.get('analysis_types', ['summary'])
        user_options = options.get('user_options', {})
        processing_mode = options.get('processing_mode', user_options.get('processing_mode', 'realtime'))
        file_types = options.get('file_types', {})

        # Image analysis types mapping (video types to image types)
        image_analysis_types = []
        for atype in analysis_types:
            if atype == 'summary':
                image_analysis_types.append('description')
            elif atype == 'elements':
                image_analysis_types.append('elements')
            elif atype == 'waterfall_classification':
                image_analysis_types.append('waterfall')
            elif atype == 'combined':
                image_analysis_types = ['description', 'elements', 'waterfall', 'metadata']
                break
        if not image_analysis_types:
            image_analysis_types = ['description', 'elements', 'metadata']

        for file_id in job.file_ids:
            if job.status == 'CANCELLED':
                break

            file = None
            try:
                # Get file
                db = get_db()
                file = db.get_file(file_id)
                if not file:
                    raise Exception(f'File {file_id} not found')

                job.current_file = file['filename']
                file_type = file_types.get(file_id, file.get('file_type', 'video'))

                if file_type == 'image':
                    # Handle image analysis
                    payload = _process_nova_image(
                        app, db, file_id, file, model_key, image_analysis_types
                    )
                else:
                    # Handle video analysis (existing logic)
                    proxy = db.get_proxy_for_source(file_id)
                    if not proxy:
                        proxy_result = create_proxy_internal(file_id, upload_to_s3=False)
                        proxy = db.get_file(proxy_result['proxy_id'])
                    if not proxy:
                        raise Exception(f'Proxy not found for file {file_id}')

                    payload, status_code = start_nova_analysis_internal(
                        file_id=proxy['id'],
                        model=model_key,
                        analysis_types=analysis_types,
                        options=user_options,
                        processing_mode=processing_mode
                    )

                    if status_code >= 400:
                        raise Exception(payload.get('error') or 'Failed to start Nova analysis')

                    analysis_job_id = payload.get('analysis_job_id')
                    if analysis_job_id:
                        with db.get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                'UPDATE analysis_jobs SET file_id = ? WHERE id = ?',
                                (file_id, analysis_job_id)
                            )

                # Track token usage and cost for Nova jobs
                results_summary = payload.get('results_summary', {})
                tokens_used = results_summary.get('tokens_used', 0) or payload.get('tokens_total', 0)
                cost_usd = results_summary.get('cost_usd', 0.0) or payload.get('actual_cost', 0.0)

                if tokens_used > 0:
                    job.total_tokens += tokens_used
                    job.processed_files_tokens.append(tokens_used)

                if cost_usd > 0:
                    job.total_cost_usd += cost_usd
                    job.processed_files_costs.append(cost_usd)

                job.completed_files += 1
                job.results.append({
                    'file_id': file_id,
                    'filename': file['filename'],
                    'file_type': file_type,
                    'success': True,
                    'nova_job_id': payload.get('nova_job_id'),
                    'analysis_job_id': payload.get('analysis_job_id'),
                    'status': payload.get('status'),
                    'tokens_used': tokens_used,
                    'cost_usd': cost_usd
                })

            except Exception as e:
                job.failed_files += 1
                error_msg = str(e)
                job.errors.append({
                    'file_id': file_id,
                    'filename': file.get('filename', f'File {file_id}') if file else f'File {file_id}',
                    'error': error_msg
                })
                current_app.logger.error(f"Batch Nova error for file {file_id}: {e}")

        # Mark job as complete
        job.status = 'COMPLETED' if job.status != 'CANCELLED' else 'CANCELLED'
        job.end_time = time.time()
        job.current_file = None


def _process_nova_image(app, db, file_id, file, model_key, analysis_types):
    """Process a single image file with Nova analysis."""
    import tempfile
    import os
    import json
    from app.routes.upload import create_image_proxy_internal
    from app.services.nova_image_service import NovaImageService
    from app.services.s3_service import S3Service

    # Check/create image proxy
    proxy_file = db.get_proxy_for_source(file_id)
    if not proxy_file:
        # Create image proxy first
        proxy_result = create_image_proxy_internal(file_id)
        if not proxy_result.get('success'):
            raise Exception(proxy_result.get('error', 'Failed to create image proxy'))
        proxy_file = db.get_proxy_for_source(file_id)

    if not proxy_file:
        raise Exception('No proxy image found after creation attempt')

    # Create analysis job
    from datetime import datetime
    analysis_job_id = db.create_analysis_job(
        file_id=file_id,
        job_id=f"nova-image-{datetime.utcnow().timestamp()}",
        analysis_type='nova_image',
        status='SUBMITTED'
    )

    # Create Nova job
    nova_job_id = db.create_nova_job(
        analysis_job_id=analysis_job_id,
        model=model_key,
        analysis_types=analysis_types,
        user_options={'proxy_file_id': proxy_file['id']},
        content_type='image'
    )

    # Update status to IN_PROGRESS
    db.update_nova_job_status(nova_job_id, 'IN_PROGRESS', 0)
    db.update_nova_job_started_at(nova_job_id)

    # Get Nova image service
    service = NovaImageService(
        bucket_name=current_app.config['S3_BUCKET_NAME'],
        region=current_app.config['AWS_REGION'],
        aws_access_key=current_app.config.get('AWS_ACCESS_KEY_ID'),
        aws_secret_key=current_app.config.get('AWS_SECRET_ACCESS_KEY')
    )

    # Get proxy image path - prefer local file, fallback to S3 download
    temp_path = None
    cleanup_temp = False

    try:
        if proxy_file.get('local_path') and os.path.exists(proxy_file['local_path']):
            # Use local file directly
            temp_path = proxy_file['local_path']
        elif proxy_file.get('s3_key'):
            # Download from S3
            s3_service = S3Service(
                bucket_name=current_app.config['S3_BUCKET_NAME'],
                region=current_app.config['AWS_REGION']
            )
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
            temp_path = temp_file.name
            temp_file.close()
            cleanup_temp = True
            s3_service.download_file(proxy_file['s3_key'], temp_path)
        else:
            raise Exception(f"No valid path for proxy file {proxy_file['id']}: no local_path or s3_key")

        # Build file context
        file_context = service.build_file_context(file, temp_path)

        # Perform analysis
        result = service.analyze_image(
            image_path=temp_path,
            analysis_types=analysis_types,
            model=model_key,
            file_context=file_context
        )

        # Store results in database
        update_data = {
            'status': 'COMPLETED',
            'progress_percent': 100,
            'tokens_input': result['tokens_input'],
            'tokens_output': result['tokens_output'],
            'tokens_total': result['tokens_total'],
            'cost_usd': result['cost_usd'],
            'processing_time_seconds': result['processing_time_seconds'],
            'raw_response': json.dumps(result['raw_response'])
        }

        # Store individual result types
        results = result['results']
        if 'description' in results:
            update_data['description_result'] = results['description']
        if 'elements' in results:
            update_data['elements_result'] = results['elements']
        if 'waterfall_classification' in results:
            update_data['waterfall_classification_result'] = results['waterfall_classification']
        if 'metadata' in results:
            update_data['search_metadata'] = results['metadata']

        db.update_nova_job(nova_job_id, update_data)
        db.update_nova_job_completed_at(nova_job_id)
        db.update_analysis_job(analysis_job_id, status='COMPLETED')

        current_app.logger.info(f"Image analysis completed: job={nova_job_id}, cost=${result['cost_usd']:.6f}")

        return {
            'nova_job_id': nova_job_id,
            'analysis_job_id': analysis_job_id,
            'status': 'COMPLETED',
            'tokens_total': result['tokens_total'],
            'actual_cost': result['cost_usd'],
            'processing_time_seconds': result['processing_time_seconds']
        }

    except Exception as analysis_error:
        # Update job with error
        db.update_nova_job(nova_job_id, {
            'status': 'FAILED',
            'error_message': str(analysis_error),
            'progress_percent': 0
        })
        db.update_analysis_job(analysis_job_id, status='FAILED')
        raise

    finally:
        # Cleanup temp file only if we created it (S3 download)
        if cleanup_temp and temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _run_batch_embeddings(app, job: BatchJob):
    """Background worker for batch embeddings generation."""
    with app.app_context():
        from app.services.embedding_manager import EmbeddingManager

        options = job.options or {}
        force = bool(options.get('force', False))

        # Create embedding manager
        db = get_db()
        embedding_manager = EmbeddingManager(db)

        for file_id in job.file_ids:
            if job.status == 'CANCELLED':
                break

            try:
                # Get file
                file = db.get_file(file_id)
                if not file:
                    raise Exception(f'File {file_id} not found')

                job.current_file = file['filename']

                # Process transcripts for this file
                transcripts = db.get_transcripts_by_file(file_id)
                nova_jobs = db.get_nova_jobs_by_file(file_id)

                embedded_count = 0
                skipped_count = 0
                failed_count = 0

                # Process each transcript
                for transcript in transcripts:
                    if transcript.get('status') == 'COMPLETED':
                        try:
                            stats = embedding_manager.process_transcript(
                                transcript_id=transcript['id'],
                                force=force
                            )
                            embedded_count += stats.get('embedded', 0)
                            skipped_count += stats.get('skipped', 0)
                            failed_count += stats.get('failed', 0)
                        except Exception as e:
                            current_app.logger.error(
                                f"Failed to process transcript {transcript['id']}: {e}"
                            )
                            failed_count += 1

                # Process each Nova job
                for nova_job in nova_jobs:
                    if nova_job.get('status') == 'COMPLETED':
                        try:
                            stats = embedding_manager.process_nova_job(
                                nova_job_id=nova_job['id'],
                                force=force
                            )
                            embedded_count += stats.get('embedded', 0)
                            skipped_count += stats.get('skipped', 0)
                            failed_count += stats.get('failed', 0)
                        except Exception as e:
                            current_app.logger.error(
                                f"Failed to process Nova job {nova_job['id']}: {e}"
                            )
                            failed_count += 1

                job.completed_files += 1
                job.results.append({
                    'file_id': file_id,
                    'filename': file['filename'],
                    'success': True,
                    'embedded': embedded_count,
                    'skipped': skipped_count,
                    'failed': failed_count
                })

            except Exception as e:
                job.failed_files += 1
                error_msg = str(e)
                job.errors.append({
                    'file_id': file_id,
                    'filename': file.get('filename', f'File {file_id}'),
                    'error': error_msg
                })
                current_app.logger.error(f"Batch embeddings error for file {file_id}: {e}")

        # Mark job as complete
        job.status = 'COMPLETED' if job.status != 'CANCELLED' else 'CANCELLED'
        job.end_time = time.time()
        job.current_file = None


def _run_batch_image_proxy(app, job: BatchJob):
    """Background worker for batch image proxy creation."""
    with app.app_context():
        from app.routes.upload import create_image_proxy_internal
        from pathlib import Path
        import traceback
        import logging

        logger = logging.getLogger('app')
        options = job.options or {}
        force = bool(options.get('force', False))

        logger.info(f"Batch image proxy worker started for job {job.job_id} with {len(job.file_ids)} files")
        print(f"[BATCH IMAGE PROXY] Worker started for job {job.job_id} with {len(job.file_ids)} files", flush=True)

        # Calculate total batch size before processing
        db = get_db()
        for file_id in job.file_ids:
            try:
                file = db.get_file(file_id)
                if file and file.get('local_path'):
                    local_path = file['local_path']
                    if Path(local_path).exists():
                        job.total_batch_size += Path(local_path).stat().st_size
            except Exception:
                pass  # Skip files that can't be accessed

        for file_id in job.file_ids:
            if job.status == 'CANCELLED':
                logger.info(f"Batch job {job.job_id} was cancelled")
                print(f"[BATCH IMAGE PROXY] Job {job.job_id} was cancelled", flush=True)
                break

            try:
                # Get file info
                db = get_db()
                file = db.get_file(file_id)
                if not file:
                    raise Exception(f'File {file_id} not found')

                job.current_file = file['filename']
                logger.info(f"Processing file {file_id}: {file['filename']}")
                print(f"[BATCH IMAGE PROXY] Processing file {file_id}: {file['filename']}", flush=True)

                # Get source file size for tracking
                source_file_size = 0
                if file.get('local_path') and Path(file['local_path']).exists():
                    source_file_size = Path(file['local_path']).stat().st_size

                # Create image proxy
                result = create_image_proxy_internal(file_id, force=force)

                # Track processed source file size
                job.processed_files_sizes.append(source_file_size)

                # Track generated proxy size
                if result.get('proxy_size_bytes'):
                    job.total_proxy_size += result['proxy_size_bytes']

                job.completed_files += 1
                job.results.append({
                    'file_id': file_id,
                    'filename': file['filename'],
                    'success': True,
                    'proxy_id': result.get('proxy_id'),
                    'original_size': result.get('original_size_bytes'),
                    'proxy_size': result.get('proxy_size_bytes'),
                    'savings_percent': result.get('savings_percent'),
                    'was_resized': result.get('was_resized', False)
                })
                logger.info(
                    f"Successfully created image proxy for file {file_id}: {file['filename']} "
                    f"({result.get('savings_percent', 0):.1f}% reduction)"
                )
                print(
                    f"[BATCH IMAGE PROXY] Successfully created image proxy for file {file_id}: {file['filename']}",
                    flush=True
                )

            except Exception as e:
                job.failed_files += 1
                error_msg = str(e)
                tb = traceback.format_exc()
                job.errors.append({
                    'file_id': file_id,
                    'filename': file.get('filename', f'File {file_id}') if file else f'File {file_id}',
                    'error': error_msg
                })

                # Track failed file size too if available
                try:
                    if 'source_file_size' in locals():
                        job.processed_files_sizes.append(source_file_size)
                except Exception:
                    pass

                logger.error(f"Batch image proxy error for file {file_id}: {e}", exc_info=True)
                print(f"[BATCH IMAGE PROXY ERROR] File {file_id}: {e}", flush=True)
                print(f"[BATCH IMAGE PROXY ERROR] Full traceback:\n{tb}", flush=True)

        # Mark job as complete
        job.status = 'COMPLETED' if job.status != 'CANCELLED' else 'CANCELLED'
        job.end_time = time.time()
        job.current_file = None
        logger.info(
            f"Batch image proxy job {job.job_id} completed: {job.completed_files} succeeded, "
            f"{job.failed_files} failed, status: {job.status}"
        )
        print(
            f"[BATCH IMAGE PROXY] Job {job.job_id} completed: {job.completed_files} succeeded, "
            f"{job.failed_files} failed, status: {job.status}", flush=True
        )