"""
Upload routes for file management.
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.s3_service import get_s3_service, S3Error
from app.database import get_db
from app.utils.validators import (
    validate_file_type, validate_file_size, sanitize_filename,
    get_file_type, ValidationError
)
from app.utils.formatters import format_file_size, format_timestamp, format_duration
from app.utils.media_metadata import extract_media_metadata, MediaMetadataError
import uuid
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import PurePosixPath, Path

bp = Blueprint('upload', __name__, url_prefix='/api/upload')


def _format_duration_seconds(duration_seconds):
    if duration_seconds is None:
        return 'N/A'
    try:
        return format_duration(int(float(duration_seconds) * 1000))
    except (ValueError, TypeError):
        return 'N/A'


def _probe_duration_seconds(file_path: str):
    if shutil.which('ffprobe'):
        command = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            try:
                return float(result.stdout.strip())
            except ValueError:
                pass

    if shutil.which('ffmpeg'):
        command = ['ffmpeg', '-i', file_path]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        duration_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+\.\d+)', result.stderr or '')
        if duration_match:
            hours = int(duration_match.group(1))
            minutes = int(duration_match.group(2))
            seconds = float(duration_match.group(3))
            return hours * 3600 + minutes * 60 + seconds
    return None


def _create_proxy_video(source_path: str, proxy_path: str):
    command = [
        'ffmpeg',
        '-y',
        '-i', source_path,
        '-vf', 'scale=-2:720,fps=15',
        '-map', '0:v:0',
        '-map', '0:a?',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '28',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac',
        '-b:a', '96k',
        '-ac', '2',
        '-movflags', '+faststart',
        proxy_path
    ]

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or 'ffmpeg failed')


def _get_display_size_bytes(file_record):
    metadata = file_record.get('metadata') or {}
    return metadata.get('original_size_bytes', file_record.get('size_bytes'))


@bp.route('/presigned-url', methods=['POST'])
def get_presigned_url():
    """
    Generate presigned POST URL for direct browser-to-S3 upload.

    Expected JSON:
        {
            "filename": "video.mp4",
            "content_type": "video/mp4",
            "size_bytes": 1024000
        }

    Returns:
        {
            "url": "https://s3.amazonaws.com/...",
            "fields": {...},
            "s3_key": "uploads/uuid/filename"
        }
    """
    try:
        data = request.get_json()
        filename = data.get('filename')
        content_type = data.get('content_type')
        size_bytes = data.get('size_bytes', 0)

        if not filename or not content_type:
            return jsonify({'error': 'filename and content_type are required'}), 400

        # Validate file type
        file_type = get_file_type(
            filename,
            current_app.config['ALLOWED_VIDEO_EXTENSIONS'],
            current_app.config['ALLOWED_IMAGE_EXTENSIONS']
        )

        # Validate file size
        max_size_mb = (
            current_app.config['MAX_VIDEO_SIZE_MB'] if file_type == 'video'
            else current_app.config['MAX_IMAGE_SIZE_MB']
        )
        validate_file_size(size_bytes, max_size_mb)

        if file_type == 'video':
            return jsonify({
                'error': 'Video uploads must use /api/upload/file to generate a local proxy first'
            }), 400

        # Get S3 service and generate presigned POST
        s3_service = get_s3_service(current_app)
        presigned_data = s3_service.generate_presigned_post(
            filename, content_type, max_size_mb
        )

        return jsonify(presigned_data), 200

    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except S3Error as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"Presigned URL error: {e}")
        return jsonify({'error': 'Failed to generate upload URL'}), 500


@bp.route('/complete', methods=['POST'])
def complete_upload():
    """
    Complete upload by recording file metadata in database.

    Expected JSON:
        {
            "s3_key": "uploads/uuid/filename",
            "filename": "video.mp4",
            "size_bytes": 1024000,
            "content_type": "video/mp4"
        }

    Returns:
        {
            "file_id": 123,
            "message": "File uploaded successfully"
        }
    """
    try:
        data = request.get_json()
        s3_key = data.get('s3_key')
        filename = data.get('filename')
        size_bytes = data.get('size_bytes', 0)
        content_type = data.get('content_type', '')

        if not s3_key or not filename:
            return jsonify({'error': 's3_key and filename are required'}), 400

        # Determine file type
        file_type = get_file_type(
            filename,
            current_app.config['ALLOWED_VIDEO_EXTENSIONS'],
            current_app.config['ALLOWED_IMAGE_EXTENSIONS']
        )

        if file_type == 'video':
            return jsonify({
                'error': 'Video uploads must use /api/upload/file to generate a proxy'
            }), 400

        # Verify file exists in S3
        s3_service = get_s3_service(current_app)
        if not s3_service.file_exists(s3_key):
            return jsonify({'error': 'File not found in S3'}), 404

        # Get actual file metadata from S3
        s3_metadata = s3_service.get_file_metadata(s3_key)
        actual_size = s3_metadata['size']

        # Record in database
        db = get_db()
        file_id = db.create_file(
            filename=filename,
            s3_key=s3_key,
            file_type=file_type,
            size_bytes=actual_size,
            content_type=content_type,
            metadata={'original_size': size_bytes}
        )

        return jsonify({
            'file_id': file_id,
            'message': 'File uploaded successfully'
        }), 201

    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except S3Error as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"Upload completion error: {e}")
        return jsonify({'error': 'Failed to complete upload'}), 500


@bp.route('/file', methods=['POST'])
def upload_file_direct():
    """
    Direct file upload through server (fallback method).

    Expected form data:
        - file: File object
    """
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400

        # Validate file
        file_type = get_file_type(
            file.filename,
            current_app.config['ALLOWED_VIDEO_EXTENSIONS'],
            current_app.config['ALLOWED_IMAGE_EXTENSIONS']
        )

        # Generate S3 key
        safe_filename = sanitize_filename(file.filename)
        upload_id = uuid.uuid4()

        max_size_mb = (
            current_app.config['MAX_VIDEO_SIZE_MB'] if file_type == 'video'
            else current_app.config['MAX_IMAGE_SIZE_MB']
        )

        if request.content_length:
            validate_file_size(request.content_length, max_size_mb)

        # Upload to S3
        s3_service = get_s3_service(current_app)
        if file_type == 'video':
            # Proxy creation is now always required
            if not shutil.which('ffmpeg'):
                return jsonify({'error': 'ffmpeg is not available on the server'}), 500

            # Save source video to local storage
            upload_root = Path(current_app.config['UPLOAD_FOLDER'])
            upload_dir = upload_root / str(upload_id)
            upload_dir.mkdir(parents=True, exist_ok=True)
            source_local_path = upload_dir / safe_filename
            file.save(source_local_path)

            source_size_bytes = os.path.getsize(source_local_path)
            try:
                validate_file_size(source_size_bytes, max_size_mb)
            except ValidationError as e:
                if source_local_path.exists():
                    source_local_path.unlink()
                return jsonify({'error': str(e)}), 400

            # Extract media metadata from source video
            try:
                source_metadata = extract_media_metadata(str(source_local_path))
            except MediaMetadataError as e:
                current_app.logger.warning(f"Failed to extract metadata: {e}")
                source_metadata = {}

            # Create proxy video in proxy_video folder
            proxy_video_dir = Path('proxy_video')
            proxy_video_dir.mkdir(parents=True, exist_ok=True)
            proxy_filename = f"{upload_id}_720p15.mp4"
            proxy_local_path = proxy_video_dir / proxy_filename

            try:
                _create_proxy_video(str(source_local_path), str(proxy_local_path))
            except RuntimeError as e:
                if source_local_path.exists():
                    source_local_path.unlink()
                raise

            proxy_size_bytes = os.path.getsize(proxy_local_path)

            # Extract media metadata from proxy video
            try:
                proxy_metadata = extract_media_metadata(str(proxy_local_path))
            except MediaMetadataError as e:
                current_app.logger.warning(f"Failed to extract proxy metadata: {e}")
                proxy_metadata = {}

            # Upload proxy to S3
            proxy_s3_key = f"uploads/{upload_id}/proxy_720p15.mp4"
            with open(proxy_local_path, 'rb') as proxy_file:
                s3_service.upload_file(proxy_file, proxy_s3_key, 'video/mp4')

            # Create source file record in database (no S3 upload for source)
            db = get_db()
            source_s3_key = f"uploads/{upload_id}/{safe_filename}"  # Not uploaded, just for reference
            source_file_id = db.create_source_file(
                filename=file.filename,
                s3_key=source_s3_key,
                file_type=file_type,
                size_bytes=source_size_bytes,
                content_type=file.content_type or 'video/mp4',
                local_path=str(source_local_path),
                resolution_width=source_metadata.get('resolution_width'),
                resolution_height=source_metadata.get('resolution_height'),
                frame_rate=source_metadata.get('frame_rate'),
                codec_video=source_metadata.get('codec_video'),
                codec_audio=source_metadata.get('codec_audio'),
                duration_seconds=source_metadata.get('duration_seconds'),
                bitrate=source_metadata.get('bitrate'),
                metadata={
                    'upload_id': str(upload_id),
                    'original_content_type': file.content_type or ''
                }
            )

            # Create proxy file record in database
            proxy_file_id = db.create_proxy_file(
                source_file_id=source_file_id,
                filename=proxy_filename,
                s3_key=proxy_s3_key,
                size_bytes=proxy_size_bytes,
                content_type='video/mp4',
                local_path=str(proxy_local_path),
                resolution_width=proxy_metadata.get('resolution_width'),
                resolution_height=proxy_metadata.get('resolution_height'),
                frame_rate=proxy_metadata.get('frame_rate'),
                codec_video=proxy_metadata.get('codec_video'),
                codec_audio=proxy_metadata.get('codec_audio'),
                duration_seconds=proxy_metadata.get('duration_seconds'),
                bitrate=proxy_metadata.get('bitrate'),
                metadata={
                    'upload_id': str(upload_id),
                    'proxy_spec': '720p15',
                    'proxy_generated_at': datetime.utcnow().isoformat() + 'Z'
                }
            )

            return jsonify({
                'file_id': source_file_id,
                'proxy_file_id': proxy_file_id,
                'message': 'File uploaded successfully',
                's3_key': proxy_s3_key,
                'size_bytes': source_size_bytes,
                'proxy_size_bytes': proxy_size_bytes,
                'display_size': format_file_size(source_size_bytes),
                'duration_seconds': source_metadata.get('duration_seconds'),
                'display_duration': _format_duration_seconds(source_metadata.get('duration_seconds'))
            }), 201

        s3_key = f"uploads/{upload_id}/{safe_filename}"
        file.seek(0, 2)
        size_bytes = file.tell()
        file.seek(0)
        validate_file_size(size_bytes, max_size_mb)
        s3_service.upload_file(file, s3_key, file.content_type)

        # Record in database
        db = get_db()
        file_id = db.create_file(
            filename=file.filename,
            s3_key=s3_key,
            file_type=file_type,
            size_bytes=size_bytes,
            content_type=file.content_type
        )

        return jsonify({
            'file_id': file_id,
            'message': 'File uploaded successfully',
            's3_key': s3_key,
            'size_bytes': size_bytes,
            'display_size': format_file_size(size_bytes)
        }), 201

    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except S3Error as e:
        return jsonify({'error': str(e)}), 500
    except RuntimeError as e:
        current_app.logger.error(f"Proxy creation error: {e}")
        return jsonify({'error': 'Failed to create proxy video'}), 500
    except Exception as e:
        current_app.logger.error(f"Direct upload error: {e}")
        return jsonify({'error': 'Failed to upload file'}), 500


@bp.route('/create-proxy', methods=['POST'])
def create_proxy():
    """
    Create a 720p/15fps proxy video for an existing upload.

    Expected JSON:
        {
            "file_id": 123,
            "force": false
        }

    Returns:
        {
            "file_id": 123,
            "proxy_s3_key": "uploads/.../proxy_720p15.mp4",
            "proxy_size_bytes": 1024000
        }
    """
    try:
        data = request.get_json() or {}
        file_id = data.get('file_id')
        force = bool(data.get('force', False))

        if not file_id:
            return jsonify({'error': 'file_id is required'}), 400

        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        if file['file_type'] != 'video':
            return jsonify({'error': 'File must be a video'}), 400

        metadata = file.get('metadata', {}) or {}
        existing_proxy = metadata.get('proxy_s3_key')
        if existing_proxy and not force:
            return jsonify({
                'file_id': file_id,
                'proxy_s3_key': existing_proxy,
                'proxy_size_bytes': metadata.get('proxy_size_bytes'),
                'message': 'Proxy already exists'
            }), 200

        if not shutil.which('ffmpeg'):
            return jsonify({'error': 'ffmpeg is not available on the server'}), 500

        s3_service = get_s3_service(current_app)
        source_s3_key = file['s3_key']

        key_path = PurePosixPath(source_s3_key)
        proxy_s3_key = str(key_path.parent / 'proxy_720p15.mp4')

        duration_seconds = metadata.get('duration_seconds')

        with tempfile.TemporaryDirectory() as tmp_dir:
            proxy_path = os.path.join(tmp_dir, 'proxy_720p15.mp4')

            local_path = metadata.get('local_path')
            if local_path and os.path.isfile(local_path):
                source_path = local_path
                if duration_seconds is None:
                    duration_seconds = _probe_duration_seconds(local_path)
            else:
                if metadata.get('proxy_s3_key') and source_s3_key == metadata.get('proxy_s3_key'):
                    return jsonify({'error': 'Local source video not available for proxy creation'}), 404
                source_path = os.path.join(tmp_dir, 'source' + os.path.splitext(file['filename'])[1])
                s3_service.download_file(source_s3_key, source_path)

            try:
                _create_proxy_video(source_path, proxy_path)
            except RuntimeError as e:
                current_app.logger.error(f"ffmpeg error: {e}")
                return jsonify({'error': 'Failed to create proxy video'}), 500

            proxy_size = os.path.getsize(proxy_path)
            with open(proxy_path, 'rb') as proxy_file:
                s3_service.upload_file(proxy_file, proxy_s3_key, 'video/mp4')

        metadata_updates = {
            'proxy_s3_key': proxy_s3_key,
            'proxy_size_bytes': proxy_size,
            'proxy_content_type': 'video/mp4',
            'proxy_generated_at': datetime.utcnow().isoformat() + 'Z',
            'proxy_spec': '720p15',
            'proxy_source_s3_key': source_s3_key
        }
        if duration_seconds is not None:
            metadata_updates['duration_seconds'] = duration_seconds
        updated_metadata = db.update_file_metadata(file_id, metadata_updates)

        return jsonify({
            'file_id': file_id,
            'proxy_s3_key': proxy_s3_key,
            'proxy_size_bytes': proxy_size,
            'metadata': updated_metadata
        }), 201

    except S3Error as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"Proxy creation error: {e}")
        return jsonify({'error': 'Failed to create proxy video'}), 500


@bp.route('/files', methods=['GET'])
def list_files():
    """
    List uploaded files.

    Query parameters:
        - type: Filter by file type ('video' or 'image')
        - limit: Maximum number of files to return (default 100)
        - offset: Pagination offset (default 0)

    Returns:
        {
            "files": [...],
            "total": 10
        }
    """
    try:
        file_type = request.args.get('type')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))

        db = get_db()
        files = db.list_files(file_type=file_type, limit=limit, offset=offset)

        # Format file data
        formatted_files = []
        for file in files:
            size_bytes = _get_display_size_bytes(file)
            duration_seconds = (file.get('metadata') or {}).get('duration_seconds')
            formatted_files.append({
                'id': file['id'],
                'filename': file['filename'],
                's3_key': file['s3_key'],
                'file_type': file['file_type'],
                'size': format_file_size(size_bytes) if size_bytes is not None else 'N/A',
                'size_bytes': size_bytes,
                'duration_seconds': duration_seconds,
                'duration': _format_duration_seconds(duration_seconds),
                'content_type': file['content_type'],
                'uploaded_at': format_timestamp(file['uploaded_at'])
            })

        return jsonify({
            'files': formatted_files,
            'total': len(formatted_files)
        }), 200

    except Exception as e:
        current_app.logger.error(f"List files error: {e}")
        return jsonify({'error': 'Failed to list files'}), 500


@bp.route('/files/<int:file_id>', methods=['GET'])
def get_file(file_id):
    """
    Get file details.

    Returns:
        {
            "id": 123,
            "filename": "video.mp4",
            "s3_key": "uploads/...",
            "file_type": "video",
            "size": "10.5 MB",
            "uploaded_at": "2024-01-15 14:30:00",
            "presigned_url": "https://..."
        }
    """
    try:
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        # Generate presigned URL for viewing
        s3_service = get_s3_service(current_app)
        presigned_url = s3_service.generate_presigned_url(file['s3_key'])

        return jsonify({
            'id': file['id'],
            'filename': file['filename'],
            's3_key': file['s3_key'],
            'file_type': file['file_type'],
            'size': format_file_size(_get_display_size_bytes(file)),
            'size_bytes': _get_display_size_bytes(file),
            'duration_seconds': (file.get('metadata') or {}).get('duration_seconds'),
            'duration': _format_duration_seconds((file.get('metadata') or {}).get('duration_seconds')),
            'content_type': file['content_type'],
            'uploaded_at': format_timestamp(file['uploaded_at']),
            'presigned_url': presigned_url
        }), 200

    except S3Error as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"Get file error: {e}")
        return jsonify({'error': 'Failed to get file'}), 500


@bp.route('/files/<int:file_id>', methods=['DELETE'])
def delete_file(file_id):
    """
    Delete file from S3 and database.

    Returns:
        {
            "message": "File deleted successfully"
        }
    """
    try:
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        # Delete from S3
        s3_service = get_s3_service(current_app)
        s3_service.delete_file(file['s3_key'])

        # Delete from database (cascade will delete related jobs)
        db.delete_file(file_id)

        return jsonify({'message': 'File deleted successfully'}), 200

    except S3Error as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"Delete file error: {e}")
        return jsonify({'error': 'Failed to delete file'}), 500
