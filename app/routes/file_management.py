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

bp = Blueprint('file_management', __name__)

# ============================================================================
# BATCH PROCESSING STATE
# ============================================================================

# Global batch jobs dictionary: {job_id: BatchJob}
_batch_jobs: Dict[str, 'BatchJob'] = {}
_batch_jobs_lock = threading.Lock()


class BatchJob:
    """Tracks batch processing job state."""

    def __init__(self, job_id: str, action_type: str, total_files: int, file_ids: List[int]):
        self.job_id = job_id
        self.action_type = action_type  # 'proxy', 'transcribe', 'nova', 'rekognition'
        self.total_files = total_files
        self.file_ids = file_ids
        self.completed_files = 0
        self.failed_files = 0
        self.current_file = None
        self.status = 'RUNNING'  # RUNNING, COMPLETED, CANCELLED, FAILED
        self.errors = []
        self.start_time = time.time()
        self.end_time = None
        self.results = []  # List of result dicts for each file
        self.total_batch_size = 0  # Total size of all files in batch (bytes)
        self.processed_files_sizes = []  # Sizes of processed files (bytes)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        elapsed = (self.end_time or time.time()) - self.start_time
        progress = (self.completed_files + self.failed_files) / self.total_files * 100 if self.total_files > 0 else 0

        # Calculate average sizes
        avg_video_size_total = self.total_batch_size / self.total_files if self.total_files > 0 else None
        avg_video_size_processed = (
            sum(self.processed_files_sizes) / len(self.processed_files_sizes)
            if len(self.processed_files_sizes) > 0 else None
        )

        return {
            'job_id': self.job_id,
            'action_type': self.action_type,
            'status': self.status,
            'total_files': self.total_files,
            'completed_files': self.completed_files,
            'failed_files': self.failed_files,
            'current_file': self.current_file,
            'progress_percent': round(progress, 1),
            'elapsed_seconds': round(elapsed, 1),
            'avg_video_size_total': avg_video_size_total,
            'avg_video_size_processed': avg_video_size_processed,
            'errors': self.errors,
            'results': self.results
        }


def _normalize_transcription_provider(provider: str) -> str:
    if not provider:
        return 'whisper'
    provider = provider.lower()
    if provider in (
        'nova', 'sonic', 'nova_sonic',
        'sonic2', 'sonic_2', 'sonic_2_online',
        'nova2_sonic', 'nova_2_sonic'
    ):
        return 'nova_sonic'
    return provider


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
            max_duration=max_duration
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
            max_duration=max_duration
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


@bp.route('/api/files/browse', methods=['POST'])
def browse_directory():
    """
    Browse directory structure for folder picker.

    Expected JSON:
        {
            "path": "E:\\"  # optional, defaults to drives on Windows or / on Linux
        }
    """
    try:
        data = request.get_json() or {}
        requested_path = data.get('path', '')

        import platform
        is_windows = platform.system() == 'Windows'

        # Get available drives on Windows
        drives = []
        if is_windows:
            import string
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    drives.append(drive)

        # Determine current path
        if not requested_path:
            if is_windows:
                current_path = drives[0] if drives else "C:\\"
            else:
                current_path = "/"
        else:
            current_path = os.path.abspath(requested_path)

        if not os.path.isdir(current_path):
            return jsonify({'error': f'Directory not found: {current_path}'}), 404

        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            parent_path = None

        directories = []
        try:
            for entry in os.scandir(current_path):
                if entry.is_dir():
                    try:
                        os.listdir(entry.path)
                        directories.append({
                            'name': entry.name,
                            'path': entry.path
                        })
                    except PermissionError:
                        pass
        except PermissionError:
            return jsonify({'error': f'Permission denied: {current_path}'}), 403

        directories.sort(key=lambda d: d['name'].lower())

        return jsonify({
            'current_path': current_path,
            'parent_path': parent_path,
            'directories': directories,
            'drives': drives if is_windows else []
        }), 200

    except Exception as e:
        current_app.logger.error(f"Browse directory error: {e}")
        return jsonify({'error': 'Failed to browse directory'}), 500


@bp.route('/api/files/import-directory', methods=['POST'])
def import_directory():
    """
    Import files from a directory into the files table without copying.

    Expected JSON:
        {
            "directory_path": "E:\\videos",
            "recursive": true
        }
    """
    try:
        data = request.get_json() or {}
        directory_path = data.get('directory_path')
        recursive = bool(data.get('recursive', True))

        if not directory_path:
            return jsonify({'error': 'directory_path is required'}), 400

        if not os.path.isdir(directory_path):
            return jsonify({'error': f'Directory not found: {directory_path}'}), 404

        allowed_video = current_app.config['ALLOWED_VIDEO_EXTENSIONS']
        allowed_image = current_app.config['ALLOWED_IMAGE_EXTENSIONS']

        db = get_db()
        imported = 0
        skipped_existing = 0
        skipped_unsupported = 0
        errors = []
        scanned = 0

        def handle_file(file_path: str):
            nonlocal imported, skipped_existing, skipped_unsupported, scanned
            scanned += 1
            abs_path = os.path.abspath(file_path)
            filename = os.path.basename(abs_path)

            try:
                file_type = get_file_type(filename, allowed_video, allowed_image)
            except ValidationError:
                skipped_unsupported += 1
                return

            if db.get_file_by_local_path(abs_path):
                skipped_existing += 1
                return

            try:
                file_stat = os.stat(abs_path)
            except OSError as e:
                errors.append({'path': abs_path, 'error': str(e)})
                return

            content_type = mimetypes.guess_type(abs_path)[0] or 'application/octet-stream'

            media_metadata = {}
            try:
                media_metadata = extract_media_metadata(abs_path)
            except MediaMetadataError as e:
                current_app.logger.warning(f"Failed to extract metadata for {abs_path}: {e}")

            db.create_source_file(
                filename=filename,
                s3_key=None,
                file_type=file_type,
                size_bytes=file_stat.st_size,
                content_type=content_type,
                local_path=abs_path,
                resolution_width=media_metadata.get('resolution_width'),
                resolution_height=media_metadata.get('resolution_height'),
                frame_rate=media_metadata.get('frame_rate'),
                codec_video=media_metadata.get('codec_video'),
                codec_audio=media_metadata.get('codec_audio'),
                duration_seconds=media_metadata.get('duration_seconds'),
                bitrate=media_metadata.get('bitrate'),
                metadata={
                    'imported_from': 'directory',
                    'source_directory': directory_path,
                    'original_size_bytes': file_stat.st_size,
                    'file_mtime': file_stat.st_mtime,
                    'file_ctime': file_stat.st_ctime
                }
            )
            imported += 1

        if recursive:
            seen_dirs = set()
            for root, dirs, files in os.walk(directory_path, followlinks=True):
                real_root = os.path.realpath(root)
                if real_root in seen_dirs:
                    dirs[:] = []
                    continue
                seen_dirs.add(real_root)

                pruned_dirs = []
                for name in dirs:
                    real_path = os.path.realpath(os.path.join(root, name))
                    if real_path not in seen_dirs:
                        pruned_dirs.append(name)
                dirs[:] = pruned_dirs

                for name in files:
                    handle_file(os.path.join(root, name))
        else:
            for entry in os.scandir(directory_path):
                if entry.is_file():
                    handle_file(entry.path)

        return jsonify({
            'scanned': scanned,
            'imported': imported,
            'skipped_existing': skipped_existing,
            'skipped_unsupported': skipped_unsupported,
            'errors': errors
        }), 200

    except Exception as e:
        current_app.logger.error(f"Import directory error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to import directory'}), 500


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
        provider = _normalize_transcription_provider(data.get('provider'))
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


# ============================================================================
# BATCH PROCESSING ENDPOINTS
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

        with _batch_jobs_lock:
            _batch_jobs[job_id] = job

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
        provider = _normalize_transcription_provider(data.get('provider'))
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

        with _batch_jobs_lock:
            _batch_jobs[job_id] = job

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

        # Validate files exist and have proxies (Nova requires S3 files)
        db = get_db()
        eligible_file_ids = []

        for file_id in file_ids:
            file = db.get_file(file_id)
            if not file:
                current_app.logger.warning(f"File {file_id} not found, skipping")
                continue

            # Check if it's a video
            if file.get('file_type') != 'video':
                current_app.logger.warning(f"File {file_id} is not a video, skipping")
                continue

            local_path = file.get('local_path')
            if not local_path or not Path(local_path).exists():
                current_app.logger.warning(f"File {file_id} has no local path, skipping")
                continue

            eligible_file_ids.append(file_id)

        if not eligible_file_ids:
            return jsonify({'error': 'No eligible files for Nova analysis (need videos with local paths)'}), 404

        # Create batch job
        job_id = f"batch-nova-{uuid.uuid4().hex[:8]}"
        job = BatchJob(job_id, 'nova', len(eligible_file_ids), eligible_file_ids)
        job.options = {
            'model': model,
            'analysis_types': analysis_types,
            'user_options': options,
            'processing_mode': processing_mode
        }

        with _batch_jobs_lock:
            _batch_jobs[job_id] = job

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


@bp.route('/api/batch/rekognition', methods=['POST'])
def batch_rekognition():
    """
    Start Rekognition analysis for specified files (from currently filtered view).

    Request body:
        {
            "file_ids": [1, 2, 3, ...],
            "analysis_types": ["label_detection", "face_detection"],
            "use_proxy": true
        }

    Returns:
        {
            "job_id": "batch-xxx",
            "total_files": 10,
            "message": "Batch Rekognition analysis started"
        }
    """
    try:
        data = request.get_json() or {}

        # Get file IDs from request
        file_ids = data.get('file_ids', [])

        if not file_ids:
            return jsonify({'error': 'No file IDs provided'}), 400

        # Rekognition options
        analysis_types = data.get('analysis_types', ['label_detection'])
        use_proxy = data.get('use_proxy', True)

        # Validate files exist (proxy check done later in worker if use_proxy=True)
        db = get_db()
        eligible_file_ids = []

        for file_id in file_ids:
            file = db.get_file(file_id)
            if not file:
                current_app.logger.warning(f"File {file_id} not found, skipping")
                continue

            # If using proxy, check if proxy exists
            if use_proxy:
                proxy = db.get_proxy_for_source(file_id)
                if not proxy:
                    current_app.logger.warning(f"File {file_id} has no proxy, skipping")
                    continue

            eligible_file_ids.append(file_id)

        if not eligible_file_ids:
            error_msg = 'No eligible files for Rekognition analysis'
            if use_proxy:
                error_msg += ' (need files with proxies)'
            return jsonify({'error': error_msg}), 404

        # Create batch job
        job_id = f"batch-rekognition-{uuid.uuid4().hex[:8]}"
        job = BatchJob(job_id, 'rekognition', len(eligible_file_ids), eligible_file_ids)
        job.options = {'analysis_types': analysis_types, 'use_proxy': use_proxy}

        with _batch_jobs_lock:
            _batch_jobs[job_id] = job

        # Start background thread
        app = current_app._get_current_object()
        thread = threading.Thread(target=_run_batch_rekognition, args=(app, job))
        thread.daemon = True
        thread.start()

        return jsonify({
            'job_id': job_id,
            'total_files': len(eligible_file_ids),
            'message': f'Batch Rekognition analysis started for {len(eligible_file_ids)} file(s)'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Batch Rekognition error: {e}", exc_info=True)
        import traceback
        current_app.logger.error(f"Full traceback:\n{traceback.format_exc()}")
        return jsonify({'error': f'Batch Rekognition error: {str(e)}'}), 500


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

        with _batch_jobs_lock:
            _batch_jobs[job_id] = job

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
        with _batch_jobs_lock:
            job = _batch_jobs.get(job_id)

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
        with _batch_jobs_lock:
            job = _batch_jobs.get(job_id)

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
        import traceback
        import logging

        logger = logging.getLogger('app')
        logger.info(f"Batch proxy worker started for job {job.job_id} with {len(job.file_ids)} files")
        print(f"[BATCH PROXY] Worker started for job {job.job_id} with {len(job.file_ids)} files", flush=True)

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

                # Create proxy (local only, no S3 upload)
                result = create_proxy_internal(file_id, upload_to_s3=False)

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
        provider = _normalize_transcription_provider(options.get('provider'))
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


def _run_batch_nova(app, job: BatchJob):
    """Background worker for batch Nova analysis."""
    with app.app_context():
        from app.routes.nova_analysis import start_nova_analysis_internal
        from app.routes.upload import create_proxy_internal

        options = job.options or {}
        model_key = options.get('model', 'lite')
        analysis_types = options.get('analysis_types', ['summary'])
        user_options = options.get('user_options', {})
        processing_mode = options.get('processing_mode', user_options.get('processing_mode', 'realtime'))

        for file_id in job.file_ids:
            if job.status == 'CANCELLED':
                break

            try:
                # Get file and proxy
                db = get_db()
                file = db.get_file(file_id)
                if not file:
                    raise Exception(f'File {file_id} not found')

                proxy = db.get_proxy_for_source(file_id)
                if not proxy:
                    proxy_result = create_proxy_internal(file_id, upload_to_s3=False)
                    proxy = db.get_file(proxy_result['proxy_id'])
                if not proxy:
                    raise Exception(f'Proxy not found for file {file_id}')

                job.current_file = file['filename']

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

                job.completed_files += 1
                job.results.append({
                    'file_id': file_id,
                    'filename': file['filename'],
                    'success': True,
                    'nova_job_id': payload.get('nova_job_id'),
                    'analysis_job_id': analysis_job_id,
                    'status': payload.get('status')
                })

            except Exception as e:
                job.failed_files += 1
                error_msg = str(e)
                job.errors.append({
                    'file_id': file_id,
                    'filename': file.get('filename', f'File {file_id}'),
                    'error': error_msg
                })
                current_app.logger.error(f"Batch Nova error for file {file_id}: {e}")

        # Mark job as complete
        job.status = 'COMPLETED' if job.status != 'CANCELLED' else 'CANCELLED'
        job.end_time = time.time()
        job.current_file = None


def _run_batch_rekognition(app, job: BatchJob):
    """Background worker for batch Rekognition analysis."""
    with app.app_context():
        from app.routes.analysis import start_analysis_job

        options = job.options
        use_proxy = options['use_proxy']
        analysis_types = options['analysis_types']

        for file_id in job.file_ids:
            if job.status == 'CANCELLED':
                break

            try:
                # Get file
                db = get_db()
                file = db.get_file(file_id)
                if not file:
                    raise Exception(f'File {file_id} not found')

                job.current_file = file['filename']

                # Determine target file (proxy or source)
                if use_proxy:
                    proxy = db.get_proxy_for_source(file_id)
                    if not proxy:
                        raise Exception(f'Proxy not found for file {file_id}')
                    target_file_id = proxy['id']
                else:
                    target_file_id = file_id

                # Start analysis for each type
                job_ids = []
                for analysis_type in analysis_types:
                    result = start_analysis_job(target_file_id, analysis_type)
                    if result and 'job_id' in result:
                        job_ids.append(result['job_id'])

                job.completed_files += 1
                job.results.append({
                    'file_id': file_id,
                    'filename': file['filename'],
                    'success': True,
                    'job_ids': job_ids
                })

            except Exception as e:
                job.failed_files += 1
                error_msg = str(e)
                job.errors.append({
                    'file_id': file_id,
                    'filename': file.get('filename', f'File {file_id}'),
                    'error': error_msg
                })
                current_app.logger.error(f"Batch Rekognition error for file {file_id}: {e}")

        # Mark job as complete
        job.status = 'COMPLETED' if job.status != 'CANCELLED' else 'CANCELLED'
        job.end_time = time.time()
        job.current_file = None


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
