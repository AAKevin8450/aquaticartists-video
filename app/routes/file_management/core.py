"""
File management routes for viewing and managing uploaded files.
"""
from flask import Blueprint, request, jsonify, current_app, render_template
from app.database import get_db
from app.services.s3_service import get_s3_service
from app.utils.formatters import format_timestamp, format_file_size, format_duration
from app.utils.validators import get_file_type, ValidationError
from app.utils.media_metadata import extract_media_metadata, MediaMetadataError
from pathlib import Path
from datetime import datetime, timezone
import os
import threading
import uuid
import time
import mimetypes
from typing import Dict, Any, List
from app.routes.file_management.shared import (
    BatchJob,
    get_batch_job,
    set_batch_job,
    delete_batch_job,
    normalize_transcription_provider,
    select_latest_completed_transcript,
)

bp = Blueprint('file_management', __name__)

# ============================================================================
# PAGE ROUTES
# ============================================================================

@bp.route('/files', methods=['GET'])
def file_management_page():
    """Render the file management page."""
    return render_template('file_management.html')


# ============================================================================
# API ROUTES
# ============================================================================

@bp.route('/api/files', methods=['GET'])
def list_files():
    """
    List source files with aggregated statistics.

    Query parameters:
        - file_type: Filter by 'video' or 'image'
        - has_proxy: Filter files with proxy (true/false)
        - has_transcription: Filter files with transcripts (true/false)
        - search: Full-text search across filenames, metadata, transcripts
        - upload_from_date: Uploaded after date (YYYY-MM-DD)
        - upload_to_date: Uploaded before date (YYYY-MM-DD)
        - created_from_date: Created after date (YYYY-MM-DD)
        - created_to_date: Created before date (YYYY-MM-DD)
        - sort_by: Sort field (uploaded_at, filename, size_bytes, duration_seconds)
        - sort_order: 'asc' or 'desc'
        - page: Page number (default 1)
        - per_page: Items per page (default 50)

    Returns:
        {
            "files": [{...}],
            "pagination": {
                "page": 1,
                "per_page": 50,
                "total": 156,
                "pages": 4
            }
        }
    """
    try:
        # Parse query parameters
        file_type = request.args.get('file_type')
        has_proxy_str = request.args.get('has_proxy')
        has_transcription_str = request.args.get('has_transcription')
        has_nova_analysis_str = request.args.get('has_nova_analysis')
        has_rekognition_analysis_str = request.args.get('has_rekognition_analysis')
        has_nova_embeddings_str = request.args.get('has_nova_embeddings')
        search = request.args.get('search', '').strip()

        # Upload date filters
        upload_from_date = request.args.get('upload_from_date')
        upload_to_date = request.args.get('upload_to_date')

        # Created date filters (based on file metadata when available, otherwise uploaded_at)
        created_from_date = request.args.get('created_from_date')
        created_to_date = request.args.get('created_to_date')

        min_size = request.args.get('min_size')
        max_size = request.args.get('max_size')
        min_duration = request.args.get('min_duration')
        max_duration = request.args.get('max_duration')
        min_transcript_chars = request.args.get('min_transcript_chars')

        # Directory path filter
        directory_path = request.args.get('directory_path', '').strip()
        include_subdirectories_str = request.args.get('include_subdirectories', 'true')
        include_subdirectories = include_subdirectories_str.lower() in ('true', '1', 'yes')

        sort_by = request.args.get('sort_by', 'uploaded_at')
        sort_order = request.args.get('sort_order', 'desc')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))

        # Convert string booleans
        has_proxy = None
        if has_proxy_str:
            has_proxy = has_proxy_str.lower() in ('true', '1', 'yes')

        has_transcription = None
        if has_transcription_str:
            has_transcription = has_transcription_str.lower() in ('true', '1', 'yes')

        has_nova_analysis = None
        if has_nova_analysis_str:
            has_nova_analysis = has_nova_analysis_str.lower() in ('true', '1', 'yes')

        has_rekognition_analysis = None
        if has_rekognition_analysis_str:
            has_rekognition_analysis = has_rekognition_analysis_str.lower() in ('true', '1', 'yes')

        has_nova_embeddings = None
        if has_nova_embeddings_str:
            has_nova_embeddings = has_nova_embeddings_str.lower() in ('true', '1', 'yes')

        # Convert size and duration to integers
        min_size = int(min_size) if min_size else None
        max_size = int(max_size) if max_size else None
        min_duration = int(min_duration) if min_duration else None
        max_duration = int(max_duration) if max_duration else None
        min_transcript_chars = int(min_transcript_chars) if min_transcript_chars else None

        # Calculate pagination
        offset = (page - 1) * per_page

        # Get files from database (includes both uploaded files and transcribed files)
        db = get_db()
        files = db.list_all_files_with_stats(
            file_type=file_type,
            has_proxy=has_proxy,
            has_transcription=has_transcription,
            has_nova_analysis=has_nova_analysis,
            has_rekognition_analysis=has_rekognition_analysis,
            has_nova_embeddings=has_nova_embeddings,
            search=search or None,
            upload_from_date=upload_from_date,
            upload_to_date=upload_to_date,
            created_from_date=created_from_date,
            created_to_date=created_to_date,
            min_size=min_size,
            max_size=max_size,
            min_duration=min_duration,
            max_duration=max_duration,
            min_transcript_chars=min_transcript_chars,
            directory_path=directory_path or None,
            include_subdirectories=include_subdirectories,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=per_page,
            offset=offset
        )

        # Get total count for pagination
        total = db.count_all_files(
            file_type=file_type,
            has_proxy=has_proxy,
            has_transcription=has_transcription,
            has_nova_analysis=has_nova_analysis,
            has_rekognition_analysis=has_rekognition_analysis,
            has_nova_embeddings=has_nova_embeddings,
            search=search or None,
            upload_from_date=upload_from_date,
            upload_to_date=upload_to_date,
            created_from_date=created_from_date,
            created_to_date=created_to_date,
            min_size=min_size,
            max_size=max_size,
            min_duration=min_duration,
            max_duration=max_duration,
            min_transcript_chars=min_transcript_chars,
            directory_path=directory_path or None,
            include_subdirectories=include_subdirectories
        )

        # Get summary statistics
        summary = db.get_all_files_summary(
            file_type=file_type,
            has_proxy=has_proxy,
            has_transcription=has_transcription,
            has_nova_analysis=has_nova_analysis,
            has_rekognition_analysis=has_rekognition_analysis,
            has_nova_embeddings=has_nova_embeddings,
            search=search or None,
            upload_from_date=upload_from_date,
            upload_to_date=upload_to_date,
            created_from_date=created_from_date,
            created_to_date=created_to_date,
            min_size=min_size,
            max_size=max_size,
            min_duration=min_duration,
            max_duration=max_duration,
            min_transcript_chars=min_transcript_chars,
            directory_path=directory_path or None,
            include_subdirectories=include_subdirectories
        )

        # Format files for display
        formatted_files = []
        for file in files:
            metadata = file.get('metadata') or {}
            file_ctime = metadata.get('file_ctime')
            file_mtime = metadata.get('file_mtime')
            created_epoch = None
            if isinstance(file_ctime, (int, float)) and isinstance(file_mtime, (int, float)):
                created_epoch = min(file_ctime, file_mtime)
            elif isinstance(file_mtime, (int, float)):
                created_epoch = file_mtime
            elif isinstance(file_ctime, (int, float)):
                created_epoch = file_ctime
            created_at_display = None
            if isinstance(created_epoch, (int, float)):
                created_at_display = format_timestamp(
                    datetime.fromtimestamp(created_epoch, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
                )
            if not created_at_display:
                created_at_display = format_timestamp(file['uploaded_at'])

            formatted_file = {
                'id': file['id'],
                'filename': file['filename'],
                's3_key': file.get('s3_key'),
                'file_type': file['file_type'],
                'size_bytes': file['size_bytes'],
                'size_display': format_file_size(file['size_bytes']),
                'content_type': file['content_type'],
                'uploaded_at': format_timestamp(file['uploaded_at']),
                'created_at': created_at_display,
                'local_path': file.get('local_path'),

                # Media metadata
                'resolution_width': file.get('resolution_width'),
                'resolution_height': file.get('resolution_height'),
                'resolution': f"{file.get('resolution_width')}x{file.get('resolution_height')}" if file.get('resolution_width') and file.get('resolution_height') else None,
                'frame_rate': file.get('frame_rate'),
                'codec_video': file.get('codec_video'),
                'codec_audio': file.get('codec_audio'),
                'duration_seconds': file.get('duration_seconds'),
                'duration_display': format_duration(file.get('duration_seconds')) if file.get('duration_seconds') else None,
                'bitrate': file.get('bitrate'),

                # Proxy status
                'has_proxy': bool(file.get('has_proxy')),
                'proxy_file_id': file.get('proxy_file_id'),
                'proxy_s3_key': file.get('proxy_s3_key'),
                'proxy_size_bytes': file.get('proxy_size_bytes'),
                'proxy_size_display': format_file_size(file.get('proxy_size_bytes')) if file.get('proxy_size_bytes') else None,

                # Analysis counts
                'total_analyses': file.get('total_analyses', 0),
                'completed_analyses': file.get('completed_analyses', 0),
                'running_analyses': file.get('running_analyses', 0),
                'failed_analyses': file.get('failed_analyses', 0),

                # Transcript counts
                'total_transcripts': file.get('total_transcripts', 0),
                'completed_transcripts': file.get('completed_transcripts', 0),
                'max_completed_transcript_chars': file.get('max_completed_transcript_chars')
            }
            formatted_files.append(formatted_file)

        # Calculate pagination info
        pages = (total + per_page - 1) // per_page if per_page > 0 else 0

        return jsonify({
            'files': formatted_files,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'pages': pages
            },
            'summary': {
                'total_count': summary['total_count'],
                'total_size_bytes': summary['total_size_bytes'],
                'total_size_display': format_file_size(summary['total_size_bytes']),
                'total_duration_seconds': summary['total_duration_seconds'],
                'total_duration_display': format_duration(summary['total_duration_seconds']) if summary['total_duration_seconds'] else None,
                'total_proxy_size_bytes': summary['total_proxy_size_bytes'],
                'total_proxy_size_display': format_file_size(summary['total_proxy_size_bytes']) if summary['total_proxy_size_bytes'] else None
            }
        }), 200

    except Exception as e:
        current_app.logger.error(f"List files error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to list files'}), 500
@bp.route('/api/files/<int:file_id>', methods=['GET'])
def get_file_details(file_id):
    """
    Get detailed file information with all related data.

    Returns:
        {
            "file": {...},
            "proxy": {...},
            "analysis_jobs": [{...}],
            "transcripts": [{...}]
        }
    """
    try:
        db = get_db()
        data = db.get_file_with_stats(file_id)

        if not data:
            return jsonify({'error': 'File not found'}), 404

        # Format file data
        file = data['file']
        formatted_file = {
            'id': file['id'],
            'filename': file['filename'],
            's3_key': file.get('s3_key'),
            'file_type': file['file_type'],
            'size_bytes': file['size_bytes'],
            'size_display': format_file_size(file['size_bytes']),
            'content_type': file['content_type'],
            'uploaded_at': format_timestamp(file['uploaded_at']),
            'local_path': file.get('local_path'),
            'metadata': file.get('metadata', {}),
            'media_metadata': {
                'resolution_width': file.get('resolution_width'),
                'resolution_height': file.get('resolution_height'),
                'frame_rate': file.get('frame_rate'),
                'codec_video': file.get('codec_video'),
                'codec_audio': file.get('codec_audio'),
                'duration_seconds': file.get('duration_seconds'),
                'bitrate': file.get('bitrate')
            }
        }

        # Format proxy data
        proxy = data.get('proxy')
        formatted_proxy = None
        if proxy:
            presigned_url = None
            if proxy.get('s3_key'):
                s3_service = get_s3_service(current_app)
                presigned_url = s3_service.generate_presigned_url(proxy['s3_key'], expires_in=3600)
            formatted_proxy = {
                'id': proxy['id'],
                'filename': proxy['filename'],
                's3_key': proxy.get('s3_key'),
                'size_bytes': proxy['size_bytes'],
                'size_display': format_file_size(proxy['size_bytes']),
                'local_path': proxy.get('local_path'),
                'presigned_url': presigned_url,
                'uploaded_at': format_timestamp(proxy['uploaded_at'])
            }

        # Format analysis jobs
        formatted_jobs = []
        for job in data.get('analysis_jobs', []):
            formatted_jobs.append({
                'id': job['id'],
                'job_id': job['job_id'],
                'analysis_type': job['analysis_type'],
                'status': job['status'],
                'started_at': format_timestamp(job['started_at']),
                'completed_at': format_timestamp(job['completed_at']),
                'has_results': job.get('results') is not None,
                'error_message': job.get('error_message')
            })

        # Format transcripts
        formatted_transcripts = []
        for transcript in data.get('transcripts', []):
            formatted_transcripts.append({
                'id': transcript['id'],
                'model_name': transcript['model_name'],
                'language': transcript.get('language'),
                'status': transcript['status'],
                'character_count': transcript.get('character_count'),
                'word_count': transcript.get('word_count'),
                'duration_seconds': transcript.get('duration_seconds'),
                'confidence_score': transcript.get('confidence_score'),
                'processing_time': transcript.get('processing_time'),
                'created_at': transcript['created_at'],
                'completed_at': transcript.get('completed_at'),
                'error_message': transcript.get('error_message')
            })

        return jsonify({
            'file': formatted_file,
            'proxy': formatted_proxy,
            'analysis_jobs': formatted_jobs,
            'transcripts': formatted_transcripts
        }), 200

    except Exception as e:
        current_app.logger.error(f"Get file details error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to get file details'}), 500


@bp.route('/api/files/<int:file_id>/s3-files', methods=['GET'])
def get_file_s3_files(file_id):
    """
    Get S3 files for a source file (its proxies).

    Returns:
        {
            "s3_files": [{...}]
        }
    """
    try:
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        # Get proxy for this file
        proxy = db.get_proxy_for_source(file_id)

        s3_files = []
        if proxy and proxy.get('s3_key'):
            s3_service = get_s3_service(current_app)
            presigned_url = s3_service.generate_presigned_url(proxy['s3_key'], expires_in=3600)

            s3_files.append({
                'proxy_id': proxy['id'],
                's3_key': proxy['s3_key'],
                'size_bytes': proxy['size_bytes'],
                'size_display': format_file_size(proxy['size_bytes']),
                'presigned_url': presigned_url,
                'uploaded_at': format_timestamp(proxy['uploaded_at'])
            })

        return jsonify({
            's3_files': s3_files
        }), 200

    except Exception as e:
        current_app.logger.error(f"Get S3 files error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to get S3 files'}), 500


@bp.route('/api/files/<int:file_id>/nova-analyses', methods=['GET'])
def get_file_nova_analyses(file_id):
    """
    Get all Nova analyses for a file.

    Returns:
        {
            "nova_analyses": [
                {
                    "id": 1,
                    "analysis_job_id": 123,
                    "job_id": "nova-123456789",
                    "model": "lite",
                    "analysis_types": ["summary", "chapters"],
                    "status": "COMPLETED",
                    "created_at": "2025-12-25T10:30:00Z",
                    "completed_at": "2025-12-25T10:32:00Z",
                    "cost_usd": 0.05,
                    "processing_mode": "realtime"
                }
            ]
        }
    """
    try:
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        # Get all Nova jobs for this file with analysis_jobs.job_id
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    nj.*,
                    aj.job_id as analysis_job_job_id
                FROM nova_jobs nj
                JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id
                WHERE aj.file_id = ?
                ORDER BY nj.created_at DESC
            ''', (file_id,))

            nova_jobs = []
            for row in cursor.fetchall():
                job = dict(row)
                # Parse JSON fields
                if job.get('analysis_types'):
                    import json
                    job['analysis_types'] = json.loads(job['analysis_types'])
                nova_jobs.append(job)

        formatted_jobs = []
        for job in nova_jobs:
            formatted_jobs.append({
                'id': job['id'],
                'analysis_job_id': job['analysis_job_id'],
                'job_id': job.get('analysis_job_job_id'),  # This is the job_id from analysis_jobs table
                'model': job['model'],
                'analysis_types': job.get('analysis_types', []),
                'status': job['status'],
                'created_at': format_timestamp(job['created_at']),
                'started_at': format_timestamp(job.get('started_at')),
                'completed_at': format_timestamp(job.get('completed_at')),
                'cost_usd': job.get('cost_usd'),
                'tokens_total': job.get('tokens_total'),
                'processing_time_seconds': job.get('processing_time_seconds'),
                'processing_mode': 'batch' if job.get('batch_mode') else 'realtime',
                'error_message': job.get('error_message')
            })

        return jsonify({
            'nova_analyses': formatted_jobs
        }), 200

    except Exception as e:
        current_app.logger.error(f"Get Nova analyses error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to get Nova analyses'}), 500


@bp.route('/api/files/<int:file_id>/create-proxy', methods=['POST'])
def create_proxy_for_file(file_id):
    """
    Create proxy for source file.

    This endpoint delegates to the upload.create_proxy endpoint.
    """
    try:
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        if file.get('is_proxy'):
            return jsonify({'error': 'Cannot create proxy for a proxy file'}), 400

        # Check if proxy already exists
        existing_proxy = db.get_proxy_for_source(file_id)
        if existing_proxy:
            return jsonify({'error': 'Proxy already exists for this file'}), 409

        # Import and call the create_proxy function from upload routes
        from app.routes.upload import create_proxy_internal

        result = create_proxy_internal(file_id)
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"Create proxy error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/<int:file_id>/create-image-proxy', methods=['POST'])
def create_image_proxy_for_file(file_id):
    """
    Create optimized image proxy for Nova 2 Lite analysis.

    Image proxies are resized to 896px on the shorter side (Nova's minimum threshold),
    reducing S3 storage costs, network transfer time, and API payload sizes.

    Request body (optional):
        {
            "force": false  // Recreate even if proxy exists
        }

    Returns:
        {
            "proxy_id": 456,
            "source_id": 123,
            "original_size_bytes": 4000000,
            "proxy_size_bytes": 200000,
            "savings_percent": 95.0,
            "original_dimensions": [4000, 3000],
            "proxy_dimensions": [1195, 896]
        }
    """
    try:
        data = request.get_json() or {}
        force = bool(data.get('force', False))

        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        if file.get('is_proxy'):
            return jsonify({'error': 'Cannot create proxy for a proxy file'}), 400

        if file.get('file_type') != 'image':
            return jsonify({'error': 'File must be an image'}), 400

        # Check if proxy already exists
        existing_proxy = db.get_proxy_for_source(file_id)
        if existing_proxy and not force:
            return jsonify({'error': 'Proxy already exists for this file', 'proxy_id': existing_proxy['id']}), 409

        # Create image proxy
        from app.routes.upload import create_image_proxy_internal

        result = create_image_proxy_internal(file_id, force=force)
        return jsonify(result), 200

    except Exception as e:
        current_app.logger.error(f"Create image proxy error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/<int:file_id>/start-analysis', methods=['POST'])
def start_analysis_for_file(file_id):
    """
    Start Rekognition analysis for file.

    Request body:
        {
            "analysis_types": ["label_detection", "face_detection"],
            "use_proxy": true
        }

    Returns:
        {
            "job_ids": ["rekognition-abc123", ...],
            "message": "Started X analysis jobs"
        }
    """
    try:
        data = request.get_json() or {}
        analysis_types = data.get('analysis_types', [])
        use_proxy = data.get('use_proxy', True)

        if not analysis_types:
            return jsonify({'error': 'No analysis types specified'}), 400

        db = get_db()

        # Determine which file to analyze
        if use_proxy:
            proxy = db.get_proxy_for_source(file_id)
            if not proxy:
                return jsonify({'error': 'Proxy file not found. Please create proxy first.'}), 404
            target_file_id = proxy['id']
        else:
            file = db.get_file(file_id)
            if not file:
                return jsonify({'error': 'File not found'}), 404
            target_file_id = file_id

        # Import and call the start_analysis function
        from app.routes.analysis import start_analysis_job

        job_ids = []
        for analysis_type in analysis_types:
            try:
                result = start_analysis_job(target_file_id, analysis_type)
                if result and 'job_id' in result:
                    job_ids.append(result['job_id'])
            except Exception as e:
                current_app.logger.error(f"Failed to start {analysis_type}: {e}")

        return jsonify({
            'job_ids': job_ids,
            'message': f'Started {len(job_ids)} analysis job(s)'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Start analysis error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/<int:file_id>/start-transcription', methods=['POST'])
def start_transcription_for_file(file_id):
    """
    Start transcription for file.

    Request body:
        {
            "provider": "whisper",  # whisper or nova_sonic
            "model_size": "medium",
            "language": "en",
            "force": false,
            "device": "auto",
            "compute_type": "default"
        }

    Returns:
        {
            "transcript_id": 5,
            "message": "Transcription started"
        }
    """
    try:
        data = request.get_json() or {}
        provider = normalize_transcription_provider(data.get('provider'))
        if provider not in ('whisper', 'nova_sonic'):
            return jsonify({'error': 'Invalid provider. Use whisper or nova_sonic (sonic_2_online).'}), 400

        model_name = data.get('model_size') or data.get('model_name') or current_app.config.get('WHISPER_MODEL_SIZE', 'medium')
        language = data.get('language')
        force = data.get('force', False)
        device = data.get('device') or current_app.config.get('WHISPER_DEVICE', 'auto')
        compute_type = data.get('compute_type') or current_app.config.get('WHISPER_COMPUTE_TYPE', 'default')

        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        local_path = file.get('local_path')
        if not local_path or not Path(local_path).exists():
            return jsonify({'error': 'Local file not found'}), 404

        # Import and call the transcription service
        from app.models import TranscriptStatus
        from app.services.transcription_service import create_transcription_service
        from app.utils.media_metadata import extract_media_metadata, MediaMetadataError

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

        file_size, file_mtime = service.get_file_metadata(local_path)
        existing = db.get_transcript_by_file_info(
            local_path, file_size, file_mtime, model_name
        )
        if existing and existing['status'] == TranscriptStatus.COMPLETED and not force:
            return jsonify({
                'transcript_id': existing['id'],
                'message': 'File already transcribed with this model (use force=true to reprocess)'
            }), 200

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

        return jsonify({
            'transcript_id': transcript_id,
            'message': 'Transcription started'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Start transcription error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/<int:file_id>/start-nova', methods=['POST'])
def start_nova_for_file(file_id):
    """
    Start Nova analysis for file.

    Request body:
        {
            "model": "lite",
            "analysis_types": ["summary", "chapters"],
            "options": {
                "summary_depth": "standard"
            }
        }

    Returns:
        {
            "job_id": "nova-job-abc123",
            "nova_job_id": 15,
            "message": "Nova analysis started"
        }
    """
    try:
        data = request.get_json() or {}
        model = data.get('model', 'lite')
        analysis_types = data.get('analysis_types', ['summary'])
        options = data.get('options', {})

        db = get_db()

        # Ensure proxy exists (create + upload to S3 if missing)
        proxy = db.get_proxy_for_source(file_id)
        if not proxy:
            from app.routes.upload import create_proxy_internal
            proxy_result = create_proxy_internal(file_id, upload_to_s3=True)
            proxy = db.get_file(proxy_result['proxy_id'])
            if not proxy:
                return jsonify({'error': 'Failed to create proxy for Nova analysis.'}), 500

        # Import and call the Nova service
        from app.routes.nova_analysis import start_nova_analysis_internal

        processing_mode = data.get('processing_mode', options.get('processing_mode', 'realtime'))
        payload, status_code = start_nova_analysis_internal(
            file_id=proxy['id'],
            model=model,
            analysis_types=analysis_types,
            options=options,
            processing_mode=processing_mode
        )

        analysis_job_id = payload.get('analysis_job_id')
        if analysis_job_id:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE analysis_jobs SET file_id = ? WHERE id = ?',
                    (file_id, analysis_job_id)
                )

        return jsonify(payload), status_code

    except Exception as e:
        current_app.logger.error(f"Start Nova error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/<int:file_id>', methods=['DELETE'])
def delete_file(file_id):
    """
    Delete file and all related data.

    Returns:
        {
            "message": "File deleted successfully",
            "deleted": {
                "analysis_jobs": 3,
                "nova_jobs": 2,
                "transcripts": 2,
                "proxy_files": 1,
                "s3_files": 1,
                "local_files": 2
            }
        }
    """
    try:
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        # Get proxy files before deletion
        proxy = db.get_proxy_for_source(file_id)

        # Delete from database (cascade)
        deleted_counts = db.delete_file_cascade(file_id)

        # Delete S3 files
        s3_service = get_s3_service(current_app)
        s3_deleted = 0

        if proxy and proxy.get('s3_key'):
            try:
                s3_service.delete_file(proxy['s3_key'])
                s3_deleted += 1
            except Exception as e:
                current_app.logger.error(f"Failed to delete S3 file: {e}")

        # Delete local files
        local_deleted = 0

        # Delete source local file
        if file.get('local_path'):
            try:
                local_path = Path(file['local_path'])
                if local_path.exists():
                    local_path.unlink()
                    local_deleted += 1
            except Exception as e:
                current_app.logger.error(f"Failed to delete source file: {e}")

        # Delete proxy local file
        if proxy and proxy.get('local_path'):
            try:
                proxy_path = Path(proxy['local_path'])
                if proxy_path.exists():
                    proxy_path.unlink()
                    local_deleted += 1
            except Exception as e:
                current_app.logger.error(f"Failed to delete proxy file: {e}")

        deleted_counts['s3_files'] = s3_deleted
        deleted_counts['local_files'] = local_deleted

        return jsonify({
            'message': 'File deleted successfully',
            'deleted': deleted_counts
        }), 200

    except Exception as e:
        current_app.logger.error(f"Delete file error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to delete file'}), 500
