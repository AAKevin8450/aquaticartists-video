"""
File management routes for viewing and managing uploaded files.
"""
from flask import Blueprint, request, jsonify, current_app, render_template
from app.database import get_db
from app.services.s3_service import get_s3_service
from app.utils.formatters import format_timestamp, format_file_size, format_duration
from pathlib import Path
import os

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
        - from_date: Uploaded after date (ISO format)
        - to_date: Uploaded before date (ISO format)
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
        search = request.args.get('search', '').strip()
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
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

        # Calculate pagination
        offset = (page - 1) * per_page

        # Get files from database (includes both uploaded files and transcribed files)
        db = get_db()
        files = db.list_all_files_with_stats(
            file_type=file_type,
            has_proxy=has_proxy,
            has_transcription=has_transcription,
            search=search or None,
            from_date=from_date,
            to_date=to_date,
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
            search=search or None,
            from_date=from_date,
            to_date=to_date
        )

        # Get summary statistics
        summary = db.get_all_files_summary(
            file_type=file_type,
            has_proxy=has_proxy,
            has_transcription=has_transcription,
            search=search or None,
            from_date=from_date,
            to_date=to_date
        )

        # Format files for display
        formatted_files = []
        for file in files:
            formatted_file = {
                'id': file['id'],
                'filename': file['filename'],
                's3_key': file['s3_key'],
                'file_type': file['file_type'],
                'size_bytes': file['size_bytes'],
                'size_display': format_file_size(file['size_bytes']),
                'content_type': file['content_type'],
                'uploaded_at': format_timestamp(file['uploaded_at']),
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

                # Analysis counts
                'total_analyses': file.get('total_analyses', 0),
                'completed_analyses': file.get('completed_analyses', 0),
                'running_analyses': file.get('running_analyses', 0),
                'failed_analyses': file.get('failed_analyses', 0),

                # Transcript counts
                'total_transcripts': file.get('total_transcripts', 0),
                'completed_transcripts': file.get('completed_transcripts', 0)
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
                'total_duration_display': format_duration(summary['total_duration_seconds']) if summary['total_duration_seconds'] else None
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
            's3_key': file['s3_key'],
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
            s3_service = get_s3_service(current_app)
            presigned_url = s3_service.generate_presigned_url(proxy['s3_key'], expires_in=3600)
            formatted_proxy = {
                'id': proxy['id'],
                'filename': proxy['filename'],
                's3_key': proxy['s3_key'],
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
        if proxy:
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
            "model_name": "medium",
            "language": "en",
            "force": false
        }

    Returns:
        {
            "transcript_id": 5,
            "message": "Transcription started"
        }
    """
    try:
        data = request.get_json() or {}
        model_name = data.get('model_name', 'medium')
        language = data.get('language')
        force = data.get('force', False)

        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        local_path = file.get('local_path')
        if not local_path or not Path(local_path).exists():
            return jsonify({'error': 'Local file not found'}), 404

        # Import and call the transcription service
        from app.services.transcription_service import TranscriptionService
        from pathlib import Path

        service = TranscriptionService(model_name=model_name)

        # Start transcription
        transcript_id = service.transcribe_file(
            file_path=local_path,
            language=language,
            force=force
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
            "model": "us.amazon.nova-lite-v1:0",
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
        model = data.get('model', 'us.amazon.nova-lite-v1:0')
        analysis_types = data.get('analysis_types', ['summary'])
        options = data.get('options', {})

        db = get_db()

        # Get proxy file (Nova requires S3 files)
        proxy = db.get_proxy_for_source(file_id)
        if not proxy:
            return jsonify({'error': 'Proxy file not found. Please create proxy first.'}), 404

        # Import and call the Nova service
        from app.routes.nova_analysis import start_nova_analysis

        result = start_nova_analysis(
            file_id=proxy['id'],
            model=model,
            analysis_types=analysis_types,
            user_options=options
        )

        return jsonify(result), 200

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


@bp.route('/api/s3-files', methods=['GET'])
def list_s3_files():
    """
    List all files stored in S3 by directly querying the S3 bucket.

    Query parameters:
        - prefix: Filter by S3 key prefix (default: none)

    Returns:
        {
            "s3_files": [{...}],
            "total": 45
        }
    """
    try:
        prefix = request.args.get('prefix', '')

        s3_service = get_s3_service(current_app)
        db = get_db()

        # List all files from S3 bucket directly
        s3_objects = s3_service.list_files(prefix=prefix)

        # Format files for display
        formatted_files = []
        for s3_obj in s3_objects:
            s3_key = s3_obj['key']
            size_bytes = s3_obj['size']
            last_modified = s3_obj.get('last_modified')

            # Try to find matching database record
            db_file = db.get_file_by_s3_key(s3_key)

            formatted_file = {
                's3_key': s3_key,
                'size_bytes': size_bytes,
                'size_display': format_file_size(size_bytes),
                'last_modified': format_timestamp(last_modified) if last_modified else None,
                'filename': s3_key.split('/')[-1],  # Extract filename from S3 key
                'in_database': db_file is not None,
                'file_id': db_file['id'] if db_file else None,
                'file_type': db_file['file_type'] if db_file else 'unknown'
            }
            formatted_files.append(formatted_file)

        return jsonify({
            's3_files': formatted_files,
            'total': len(formatted_files)
        }), 200

    except Exception as e:
        current_app.logger.error(f"List S3 files error: {e}", exc_info=True)
        return jsonify({'error': f'Failed to list S3 files: {str(e)}'}), 500


@bp.route('/api/s3-file/<path:s3_key>/download-url', methods=['GET'])
def get_s3_download_url(s3_key: str):
    """
    Get presigned download URL for an S3 file.

    Returns:
        {
            "download_url": "https://...",
            "expires_in": 3600
        }
    """
    try:
        s3_service = get_s3_service(current_app)

        # Generate presigned URL
        download_url = s3_service.get_presigned_download_url(s3_key, expires_in=3600)

        return jsonify({
            'download_url': download_url,
            'expires_in': 3600,
            's3_key': s3_key
        }), 200

    except Exception as e:
        current_app.logger.error(f"Get download URL error: {e}", exc_info=True)
        return jsonify({'error': f'Failed to generate download URL: {str(e)}'}), 500


@bp.route('/api/s3-file/<path:s3_key>', methods=['DELETE'])
def delete_s3_file(s3_key: str):
    """
    Delete a single file from S3.

    Returns:
        {
            "message": "File deleted successfully",
            "s3_key": "..."
        }
    """
    try:
        s3_service = get_s3_service(current_app)

        # Delete the file
        s3_service.delete_file(s3_key)

        return jsonify({
            'message': 'File deleted successfully',
            's3_key': s3_key
        }), 200

    except Exception as e:
        current_app.logger.error(f"Delete S3 file error: {e}", exc_info=True)
        return jsonify({'error': f'Failed to delete file: {str(e)}'}), 500


@bp.route('/api/s3-files/delete-all', methods=['POST'])
def delete_all_s3_files():
    """
    Delete ALL files from the S3 bucket.

    WARNING: This is a destructive operation!

    Request body (optional):
        {
            "confirm": true,  # Must be true to proceed
            "prefix": "folder/"  # Optional: only delete files with this prefix
        }

    Returns:
        {
            "message": "Deleted X files",
            "deleted_count": X
        }
    """
    try:
        data = request.get_json() or {}

        # Require explicit confirmation
        if not data.get('confirm'):
            return jsonify({'error': 'Confirmation required. Set "confirm": true in request body'}), 400

        s3_service = get_s3_service(current_app)
        prefix = data.get('prefix', '')

        # Delete all files
        deleted_count = s3_service.delete_all_files(prefix=prefix)

        message = f"Deleted {deleted_count} file{'s' if deleted_count != 1 else ''}"
        if prefix:
            message += f" with prefix '{prefix}'"

        return jsonify({
            'message': message,
            'deleted_count': deleted_count
        }), 200

    except Exception as e:
        current_app.logger.error(f"Delete all S3 files error: {e}", exc_info=True)
        return jsonify({'error': f'Failed to delete files: {str(e)}'}), 500
