"""
Routes for local video transcription.
"""
from flask import Blueprint, request, jsonify, render_template, current_app, send_file
from app.database import get_db
from app.services.transcription_service import create_transcription_service, TranscriptionError
from app.models import TranscriptStatus
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, Any
import io
import json

bp = Blueprint('transcription', __name__, url_prefix='/transcription')

# Global transcription service instance (lazy loaded)
_transcription_service = None
_service_lock = threading.Lock()


def get_transcription_service():
    """Get or create transcription service instance."""
    global _transcription_service
    if _transcription_service is None:
        with _service_lock:
            if _transcription_service is None:
                # Get model size from app config or use default
                model_size = current_app.config.get('WHISPER_MODEL_SIZE', 'medium')
                device = current_app.config.get('WHISPER_DEVICE', 'auto')
                compute_type = current_app.config.get('WHISPER_COMPUTE_TYPE', 'default')
                _transcription_service = create_transcription_service(model_size, device, compute_type)
    return _transcription_service


@bp.route('/')
def index():
    """Render transcription page."""
    return render_template('transcription.html')


@bp.route('/api/browse', methods=['POST'])
def browse_directory():
    """
    Browse directory structure for folder picker.

    Expected JSON:
        {
            "path": "E:\\"  # optional, defaults to drives on Windows or / on Linux
        }

    Returns:
        {
            "current_path": "E:\\videos",
            "parent_path": "E:\\",
            "directories": [
                {"name": "movies", "path": "E:\\videos\\movies"},
                {"name": "shows", "path": "E:\\videos\\shows"}
            ],
            "drives": ["C:\\", "D:\\", "E:\\"]  # Windows only
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
            # Default to first available drive on Windows, or / on Linux
            if is_windows:
                current_path = drives[0] if drives else "C:\\"
            else:
                current_path = "/"
        else:
            current_path = os.path.abspath(requested_path)

        # Verify path exists and is a directory
        if not os.path.isdir(current_path):
            return jsonify({'error': f'Directory not found: {current_path}'}), 404

        # Get parent path
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            parent_path = None  # At root

        # List subdirectories
        directories = []
        try:
            for entry in os.scandir(current_path):
                if entry.is_dir():
                    try:
                        # Check if directory is accessible
                        os.listdir(entry.path)
                        directories.append({
                            'name': entry.name,
                            'path': entry.path
                        })
                    except PermissionError:
                        # Skip directories we can't access
                        pass
        except PermissionError:
            return jsonify({'error': f'Permission denied: {current_path}'}), 403

        # Sort directories alphabetically
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


@bp.route('/api/scan', methods=['POST'])
def scan_directory():
    """
    Scan directory for video files.

    Expected JSON:
        {
            "directory_path": "/path/to/videos",
            "recursive": true,
            "extensions": [".mp4", ".mov"]  # optional
        }

    Returns:
        {
            "files": [
                {
                    "path": "/path/to/video.mp4",
                    "filename": "video.mp4",
                    "size_bytes": 123456,
                    "already_transcribed": true,
                    "transcript_id": 1  # if already_transcribed
                }
            ],
            "total_count": 10,
            "already_transcribed_count": 3
        }
    """
    try:
        data = request.get_json()
        directory_path = data.get('directory_path')
        recursive = data.get('recursive', True)
        extensions = data.get('extensions')

        if not directory_path:
            return jsonify({'error': 'directory_path is required'}), 400

        if not os.path.isdir(directory_path):
            return jsonify({'error': f'Directory not found: {directory_path}'}), 404

        # Scan directory
        service = get_transcription_service()
        video_files = service.scan_directory(directory_path, extensions, recursive)

        # Check which files are already transcribed
        # OPTIMIZATION: Check by file path only during scan (no hash calculation)
        # Hash will be calculated during actual transcription
        db = get_db()
        files_info = []
        already_transcribed_count = 0

        for file_path in video_files:
            file_stat = os.stat(file_path)

            # Check if already transcribed by file path (fast)
            existing_transcript = db.get_transcript_by_path(file_path)
            already_transcribed = existing_transcript is not None and existing_transcript['status'] == TranscriptStatus.COMPLETED

            if already_transcribed:
                already_transcribed_count += 1

            files_info.append({
                'path': file_path,
                'filename': os.path.basename(file_path),
                'size_bytes': file_stat.st_size,
                'already_transcribed': already_transcribed,
                'transcript_id': existing_transcript['id'] if already_transcribed else None
            })

        return jsonify({
            'files': files_info,
            'total_count': len(files_info),
            'already_transcribed_count': already_transcribed_count
        }), 200

    except TranscriptionError as e:
        current_app.logger.error(f"Transcription error: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Scan directory error: {e}")
        return jsonify({'error': 'Failed to scan directory'}), 500


@bp.route('/api/transcribe-single', methods=['POST'])
def transcribe_single():
    """
    Transcribe a single video file.

    Expected JSON:
        {
            "file_path": "/path/to/video.mp4",
            "language": "en",  # optional
            "force": false  # optional, reprocess even if already exists
        }

    Returns:
        {
            "transcript_id": 1,
            "status": "COMPLETED",
            "transcript": { ... }
        }
    """
    try:
        data = request.get_json()
        file_path = data.get('file_path')
        language = data.get('language')
        force = data.get('force', False)

        if not file_path:
            return jsonify({'error': 'file_path is required'}), 400

        if not os.path.isfile(file_path):
            return jsonify({'error': f'File not found: {file_path}'}), 404

        db = get_db()
        service = get_transcription_service()

        # Get file metadata (instant - no file reading)
        file_size, file_mtime = service.get_file_metadata(file_path)

        # Check if already transcribed
        existing_transcript = db.get_transcript_by_file_info(file_path, file_size, file_mtime)
        if existing_transcript and existing_transcript['status'] == TranscriptStatus.COMPLETED and not force:
            return jsonify({
                'transcript_id': existing_transcript['id'],
                'status': 'COMPLETED',
                'transcript': existing_transcript,
                'message': 'File already transcribed (use force=true to reprocess)'
            }), 200

        # Create or update transcript record
        if existing_transcript:
            transcript_id = existing_transcript['id']
            db.update_transcript_status(transcript_id, TranscriptStatus.IN_PROGRESS)
        else:
            transcript_id = db.create_transcript(
                file_path=file_path,
                file_size_bytes=file_size,
                file_modified_time=file_mtime,
                model_used=service.model_size
            )

        try:
            # Transcribe
            result = service.transcribe_file(file_path, language=language)

            # Update database with results
            db.update_transcript_status(
                transcript_id=transcript_id,
                status=TranscriptStatus.COMPLETED,
                transcript_text=result['transcript_text'],
                transcript_segments=result['segments'],
                word_timestamps=result['word_timestamps'],
                duration_seconds=result['duration_seconds'],
                language=result['language'],
                confidence_score=result['confidence_score'],
                processing_time_seconds=result['processing_time_seconds']
            )

            # Get updated transcript
            transcript = db.get_transcript(transcript_id)

            return jsonify({
                'transcript_id': transcript_id,
                'status': TranscriptStatus.COMPLETED,
                'transcript': transcript
            }), 201

        except Exception as e:
            # Update status to failed
            db.update_transcript_status(
                transcript_id=transcript_id,
                status=TranscriptStatus.FAILED,
                error_message=str(e)
            )
            raise

    except TranscriptionError as e:
        current_app.logger.error(f"Transcription error: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Transcribe single error: {e}")
        return jsonify({'error': f'Failed to transcribe file: {str(e)}'}), 500


@bp.route('/api/start-batch', methods=['POST'])
def start_batch():
    """
    Start batch transcription job.

    Expected JSON:
        {
            "file_paths": ["/path/to/video1.mp4", "/path/to/video2.mp4"],
            "language": "en",  # optional
            "force": false,  # optional
            "model_size": "large-v3"  # optional (tiny, base, small, medium, large-v2, large-v3)
        }

    Returns:
        {
            "job_id": "uuid",
            "total_files": 10,
            "status": "RUNNING"
        }
    """
    try:
        data = request.get_json()
        file_paths = data.get('file_paths', [])
        language = data.get('language')
        force = data.get('force', False)
        model_size = data.get('model_size')  # Get model size from request

        if not file_paths:
            return jsonify({'error': 'file_paths is required'}), 400

        # Generate job ID
        job_id = str(uuid.uuid4())

        # Start batch transcription in background thread
        db = get_db()
        service = get_transcription_service()

        # Get app reference for background thread
        app = current_app._get_current_object()

        def db_callback(file_path: str, result: Dict[str, Any]):
            """Callback to save transcription results to database."""
            try:
                # Get file metadata (instant - no file reading)
                file_size, file_mtime = service.get_file_metadata(file_path)

                # Check if already exists
                existing = db.get_transcript_by_file_info(file_path, file_size, file_mtime)

                if existing and not force:
                    transcript_id = existing['id']
                else:
                    if existing:
                        transcript_id = existing['id']
                    else:
                        transcript_id = db.create_transcript(
                            file_path=file_path,
                            file_size_bytes=file_size,
                            file_modified_time=file_mtime,
                            model_used=service.model_size
                        )

                    # Update with results
                    db.update_transcript_status(
                        transcript_id=transcript_id,
                        status=TranscriptStatus.COMPLETED,
                        transcript_text=result['transcript_text'],
                        transcript_segments=result['segments'],
                        word_timestamps=result['word_timestamps'],
                        duration_seconds=result['duration_seconds'],
                        language=result['language'],
                        confidence_score=result['confidence_score'],
                        processing_time_seconds=result['processing_time_seconds']
                    )

            except Exception as e:
                app.logger.error(f"Failed to save transcript for {file_path}: {e}")

        def run_batch():
            """Run batch transcription in background."""
            with app.app_context():
                try:
                    service.batch_transcribe(
                        file_paths=file_paths,
                        job_id=job_id,
                        db_callback=db_callback,
                        force=force,
                        model_size=model_size,
                        language=language
                    )
                except Exception as e:
                    app.logger.error(f"Batch transcription error: {e}")

        # Start background thread
        thread = threading.Thread(target=run_batch, daemon=True)
        thread.start()

        return jsonify({
            'job_id': job_id,
            'total_files': len(file_paths),
            'status': 'RUNNING'
        }), 202

    except Exception as e:
        current_app.logger.error(f"Start batch error: {e}")
        return jsonify({'error': 'Failed to start batch job'}), 500


@bp.route('/api/batch-status/<job_id>', methods=['GET'])
def batch_status(job_id: str):
    """
    Get batch job status.

    Returns:
        {
            "job_id": "uuid",
            "status": "RUNNING",
            "total_files": 10,
            "completed_files": 5,
            "failed_files": 1,
            "current_file": "/path/to/current.mp4",
            "progress_percent": 50.0,
            "elapsed_time": 123.45,
            "errors": [...]
        }
    """
    try:
        service = get_transcription_service()
        progress = service.get_batch_progress(job_id)

        if progress is None:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify({
            'job_id': job_id,
            'status': progress.status,
            'total_files': progress.total_files,
            'completed_files': progress.completed_files,
            'failed_files': progress.failed_files,
            'current_file': progress.current_file,
            'progress_percent': progress.progress_percent,
            'elapsed_time': progress.elapsed_time,
            'errors': progress.errors
        }), 200

    except Exception as e:
        current_app.logger.error(f"Batch status error: {e}")
        return jsonify({'error': 'Failed to get batch status'}), 500


@bp.route('/api/batch-cancel/<job_id>', methods=['POST'])
def cancel_batch(job_id: str):
    """Cancel a running batch job."""
    try:
        service = get_transcription_service()
        cancelled = service.cancel_batch(job_id)

        if not cancelled:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify({
            'job_id': job_id,
            'status': 'CANCELLED',
            'message': 'Batch job cancelled successfully'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Cancel batch error: {e}")
        return jsonify({'error': 'Failed to cancel batch job'}), 500


@bp.route('/api/transcripts', methods=['GET'])
def list_transcripts():
    """
    List all transcripts with pagination.

    Query params:
        - status: Filter by status (PENDING, IN_PROGRESS, COMPLETED, FAILED)
        - limit: Max results (default 100)
        - offset: Pagination offset (default 0)

    Returns:
        {
            "transcripts": [...],
            "total_count": 150,
            "limit": 100,
            "offset": 0
        }
    """
    try:
        status = request.args.get('status')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))

        db = get_db()
        transcripts = db.list_transcripts(status=status, limit=limit, offset=offset)
        total_count = db.count_transcripts(status=status)

        return jsonify({
            'transcripts': transcripts,
            'total_count': total_count,
            'limit': limit,
            'offset': offset
        }), 200

    except Exception as e:
        current_app.logger.error(f"List transcripts error: {e}")
        return jsonify({'error': 'Failed to list transcripts'}), 500


@bp.route('/api/transcript/<int:transcript_id>', methods=['GET'])
def get_transcript(transcript_id: int):
    """Get single transcript by ID."""
    try:
        db = get_db()
        transcript = db.get_transcript(transcript_id)

        if not transcript:
            return jsonify({'error': 'Transcript not found'}), 404

        return jsonify(transcript), 200

    except Exception as e:
        current_app.logger.error(f"Get transcript error: {e}")
        return jsonify({'error': 'Failed to get transcript'}), 500


@bp.route('/api/transcript/<int:transcript_id>', methods=['DELETE'])
def delete_transcript(transcript_id: int):
    """Delete transcript by ID."""
    try:
        db = get_db()
        deleted = db.delete_transcript(transcript_id)

        if not deleted:
            return jsonify({'error': 'Transcript not found'}), 404

        return jsonify({'message': 'Transcript deleted successfully'}), 200

    except Exception as e:
        current_app.logger.error(f"Delete transcript error: {e}")
        return jsonify({'error': 'Failed to delete transcript'}), 500


@bp.route('/api/transcript/<int:transcript_id>/download', methods=['GET'])
def download_transcript(transcript_id: int):
    """
    Download transcript in various formats.

    Query params:
        - format: 'txt', 'json', 'srt', 'vtt' (default: 'txt')
    """
    try:
        format_type = request.args.get('format', 'txt').lower()
        db = get_db()
        transcript = db.get_transcript(transcript_id)

        if not transcript:
            return jsonify({'error': 'Transcript not found'}), 404

        filename = f"transcript_{transcript_id}"

        if format_type == 'txt':
            # Plain text format
            content = transcript['transcript_text'] or ''
            return send_file(
                io.BytesIO(content.encode('utf-8')),
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'{filename}.txt'
            )

        elif format_type == 'json':
            # Full JSON format
            content = json.dumps(transcript, indent=2, ensure_ascii=False)
            return send_file(
                io.BytesIO(content.encode('utf-8')),
                mimetype='application/json',
                as_attachment=True,
                download_name=f'{filename}.json'
            )

        elif format_type == 'srt':
            # SubRip subtitle format
            srt_content = _generate_srt(transcript['transcript_segments'])
            return send_file(
                io.BytesIO(srt_content.encode('utf-8')),
                mimetype='text/plain',
                as_attachment=True,
                download_name=f'{filename}.srt'
            )

        elif format_type == 'vtt':
            # WebVTT subtitle format
            vtt_content = _generate_vtt(transcript['transcript_segments'])
            return send_file(
                io.BytesIO(vtt_content.encode('utf-8')),
                mimetype='text/vtt',
                as_attachment=True,
                download_name=f'{filename}.vtt'
            )

        else:
            return jsonify({'error': f'Unsupported format: {format_type}'}), 400

    except Exception as e:
        current_app.logger.error(f"Download transcript error: {e}")
        return jsonify({'error': 'Failed to download transcript'}), 500


def _format_timestamp_srt(seconds: float) -> str:
    """Format timestamp for SRT format (HH:MM:SS,mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    """Format timestamp for VTT format (HH:MM:SS.mmm)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _generate_srt(segments: list) -> str:
    """Generate SRT subtitle file content."""
    if not segments:
        return ''

    lines = []
    for i, segment in enumerate(segments, 1):
        start = _format_timestamp_srt(segment['start'])
        end = _format_timestamp_srt(segment['end'])
        text = segment['text'].strip()

        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")  # Empty line between segments

    return '\n'.join(lines)


def _generate_vtt(segments: list) -> str:
    """Generate WebVTT subtitle file content."""
    if not segments:
        return 'WEBVTT\n\n'

    lines = ['WEBVTT', '']

    for segment in segments:
        start = _format_timestamp_vtt(segment['start'])
        end = _format_timestamp_vtt(segment['end'])
        text = segment['text'].strip()

        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")  # Empty line between segments

    return '\n'.join(lines)
