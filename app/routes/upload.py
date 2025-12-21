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
import mimetypes
import json
from datetime import datetime
from pathlib import PurePosixPath, Path

bp = Blueprint('upload', __name__, url_prefix='/api/upload')

DEFAULT_PROXY_SPEC = '720p15'


def _build_proxy_filename(source_filename: str, source_file_id: int, proxy_spec: str) -> str:
    name_parts = Path(source_filename)
    suffix = name_parts.suffix or '.mp4'
    return f"{name_parts.stem}_{source_file_id}_{proxy_spec}{suffix}"


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


def _select_audio_stream(file_path: str):
    if not shutil.which('ffprobe'):
        return None
    command = [
        'ffprobe',
        '-v', 'error',
        '-select_streams', 'a',
        '-show_entries', 'stream=index,codec_name,channels',
        '-of', 'json',
        file_path
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    streams = data.get('streams') or []
    candidates = []
    for stream in streams:
        codec_name = (stream.get('codec_name') or '').lower()
        if not codec_name or codec_name == 'none':
            continue
        channels = stream.get('channels')
        candidates.append((channels or 0, stream.get('index')))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _create_proxy_video(source_path: str, proxy_path: str):
    audio_stream_index = _select_audio_stream(source_path)
    command = [
        'ffmpeg',
        '-y',
        '-i', source_path,
        '-vf', 'scale=-2:720,fps=15',
        '-map', '0:v:0'
    ]
    if audio_stream_index is not None:
        command.extend(['-map', f'0:a:{audio_stream_index}'])
    command.extend([
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '28',
        '-pix_fmt', 'yuv420p'
    ])
    if audio_stream_index is not None:
        command.extend(['-c:a', 'aac', '-b:a', '96k', '-ac', '2'])
    command.extend(['-movflags', '+faststart', proxy_path])

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

    This endpoint is disabled in local-first mode.
    """
    try:
        return jsonify({
            'error': 'Direct S3 uploads are disabled in local-first mode. Use /api/upload/file.'
        }), 400

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
    This endpoint is disabled in local-first mode.
    """
    try:
        return jsonify({
            'error': 'Direct S3 uploads are disabled in local-first mode. Use /api/upload/file.'
        }), 400

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

        # Generate upload ID and safe filename
        safe_filename = sanitize_filename(file.filename)
        upload_id = uuid.uuid4()

        max_size_mb = (
            current_app.config['MAX_VIDEO_SIZE_MB'] if file_type == 'video'
            else current_app.config['MAX_IMAGE_SIZE_MB']
        )

        if request.content_length:
            validate_file_size(request.content_length, max_size_mb)

        upload_root = Path(current_app.config['UPLOAD_FOLDER'])
        upload_root.mkdir(parents=True, exist_ok=True)
        temp_source_path = upload_root / f"tmp_{upload_id}_{safe_filename}"

        if file_type == 'video':
            # Proxy creation is now always required
            if not shutil.which('ffmpeg'):
                return jsonify({'error': 'ffmpeg is not available on the server'}), 500

            # Save source video to local storage
            file.save(temp_source_path)

            source_size_bytes = os.path.getsize(temp_source_path)
            try:
                validate_file_size(source_size_bytes, max_size_mb)
            except ValidationError as e:
                if temp_source_path.exists():
                    temp_source_path.unlink()
                return jsonify({'error': str(e)}), 400

            # Extract media metadata from source video
            try:
                source_metadata = extract_media_metadata(str(temp_source_path))
            except MediaMetadataError as e:
                current_app.logger.warning(f"Failed to extract metadata: {e}")
                source_metadata = {}

            db = get_db()
            source_file_id = db.create_source_file(
                filename=file.filename,
                s3_key=None,
                file_type=file_type,
                size_bytes=source_size_bytes,
                content_type=file.content_type or 'video/mp4',
                local_path=str(temp_source_path),
                resolution_width=source_metadata.get('resolution_width'),
                resolution_height=source_metadata.get('resolution_height'),
                frame_rate=source_metadata.get('frame_rate'),
                codec_video=source_metadata.get('codec_video'),
                codec_audio=source_metadata.get('codec_audio'),
                duration_seconds=source_metadata.get('duration_seconds'),
                bitrate=source_metadata.get('bitrate'),
                metadata={
                    'upload_id': str(upload_id),
                    'original_content_type': file.content_type or '',
                    'original_size_bytes': source_size_bytes
                }
            )

            name_parts = Path(safe_filename)
            final_filename = f"{name_parts.stem}_{source_file_id}{name_parts.suffix}"
            source_local_path = upload_root / final_filename
            try:
                temp_source_path.replace(source_local_path)
                db.update_file_local_path(source_file_id, str(source_local_path))
            except Exception:
                if temp_source_path.exists():
                    temp_source_path.unlink()
                db.delete_file(source_file_id)
                raise

            proxy_spec = DEFAULT_PROXY_SPEC

            # Create proxy video in proxy_video folder
            proxy_video_dir = Path('proxy_video')
            proxy_video_dir.mkdir(parents=True, exist_ok=True)
            proxy_filename = _build_proxy_filename(safe_filename, source_file_id, proxy_spec)
            proxy_local_path = proxy_video_dir / proxy_filename

            try:
                _create_proxy_video(str(source_local_path), str(proxy_local_path))
            except RuntimeError as e:
                if source_local_path.exists():
                    source_local_path.unlink()
                if proxy_local_path.exists():
                    proxy_local_path.unlink()
                db.delete_file(source_file_id)
                raise

            proxy_size_bytes = os.path.getsize(proxy_local_path)

            # Extract media metadata from proxy video
            try:
                proxy_metadata = extract_media_metadata(str(proxy_local_path))
            except MediaMetadataError as e:
                current_app.logger.warning(f"Failed to extract proxy metadata: {e}")
                proxy_metadata = {}

            # Create proxy file record in database
            proxy_file_id = db.create_proxy_file(
                source_file_id=source_file_id,
                filename=proxy_filename,
                s3_key=None,
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
                    'proxy_spec': proxy_spec,
                    'proxy_generated_at': datetime.utcnow().isoformat() + 'Z'
                }
            )

            return jsonify({
                'file_id': source_file_id,
                'proxy_file_id': proxy_file_id,
                'message': 'File uploaded successfully',
                'size_bytes': source_size_bytes,
                'proxy_size_bytes': proxy_size_bytes,
                'display_size': format_file_size(source_size_bytes),
                'duration_seconds': source_metadata.get('duration_seconds'),
                'display_duration': _format_duration_seconds(source_metadata.get('duration_seconds'))
            }), 201

        # Image upload (local only)
        file.save(temp_source_path)
        size_bytes = os.path.getsize(temp_source_path)
        validate_file_size(size_bytes, max_size_mb)

        try:
            image_metadata = extract_media_metadata(str(temp_source_path))
        except MediaMetadataError as e:
            current_app.logger.warning(f"Failed to extract image metadata: {e}")
            image_metadata = {}

        # Record in database
        content_type = file.content_type or mimetypes.guess_type(safe_filename)[0] or 'application/octet-stream'
        db = get_db()
        file_id = db.create_source_file(
            filename=file.filename,
            s3_key=None,
            file_type=file_type,
            size_bytes=size_bytes,
            content_type=content_type,
            local_path=str(temp_source_path),
            resolution_width=image_metadata.get('resolution_width'),
            resolution_height=image_metadata.get('resolution_height'),
            frame_rate=image_metadata.get('frame_rate'),
            codec_video=image_metadata.get('codec_video'),
            codec_audio=image_metadata.get('codec_audio'),
            duration_seconds=image_metadata.get('duration_seconds'),
            bitrate=image_metadata.get('bitrate'),
            metadata={
                'upload_id': str(upload_id),
                'original_content_type': file.content_type or '',
                'original_size_bytes': size_bytes
            }
        )

        name_parts = Path(safe_filename)
        final_filename = f"{name_parts.stem}_{file_id}{name_parts.suffix}"
        source_local_path = upload_root / final_filename
        try:
            temp_source_path.replace(source_local_path)
            db.update_file_local_path(file_id, str(source_local_path))
        except Exception:
            if temp_source_path.exists():
                temp_source_path.unlink()
            db.delete_file(file_id)
            raise

        return jsonify({
            'file_id': file_id,
            'message': 'File uploaded successfully',
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


def create_proxy_internal(file_id: int, force: bool = False, upload_to_s3: bool = False):
    """
    Internal function to create a proxy video for a file.

    Args:
        file_id: The file ID to create proxy for
        force: If True, recreate proxy even if it exists
        upload_to_s3: If True, upload proxy to S3 (default True). If False, only create local proxy.

    Returns:
        dict with proxy info

    Raises:
        Exception: If proxy creation fails
    """
    db = get_db()
    file = db.get_file(file_id)

    if not file:
        raise Exception('File not found')

    if file['file_type'] != 'video':
        raise Exception('File must be a video')

    # Check for existing proxy in new schema (proxy as separate file record)
    existing_proxy = db.get_proxy_for_source(file_id)
    if existing_proxy and not force:
        return {
            'file_id': file_id,
            'proxy_id': existing_proxy['id'],
            's3_key': existing_proxy.get('s3_key'),
            'size_bytes': existing_proxy['size_bytes'],
            'local_path': existing_proxy.get('local_path'),
            'message': 'Proxy already exists'
        }

    if not shutil.which('ffmpeg'):
        raise Exception('ffmpeg is not available on the server')

    from flask import current_app
    s3_service = get_s3_service(current_app) if upload_to_s3 else None

    # Use local path if available
    local_path = file.get('local_path')
    if not local_path or not os.path.isfile(local_path):
        raise Exception('Local source video not available for proxy creation')

    # Generate proxy filename
    proxy_spec = DEFAULT_PROXY_SPEC
    source_filename = file['filename']
    proxy_filename = _build_proxy_filename(source_filename, file_id, proxy_spec)

    # Determine where to save proxy
    if upload_to_s3:
        # Use temporary directory, will upload to S3
        with tempfile.TemporaryDirectory() as tmp_dir:
            proxy_path = os.path.join(tmp_dir, proxy_filename)

            try:
                _create_proxy_video(local_path, proxy_path)
            except RuntimeError as e:
                current_app.logger.error(f"ffmpeg error: {e}")
                raise Exception(f'Failed to create proxy video: {e}')

            # Upload to S3
            proxy_s3_key = f"proxies/{proxy_filename}"
            proxy_size = os.path.getsize(proxy_path)

            with open(proxy_path, 'rb') as proxy_file:
                s3_service.upload_file(proxy_file, proxy_s3_key, 'video/mp4')

            proxy_local_path = None
    else:
        # Save to local proxy_video folder (no S3 upload)
        proxy_video_dir = Path('proxy_video')
        proxy_video_dir.mkdir(parents=True, exist_ok=True)
        proxy_path = str(proxy_video_dir / proxy_filename)

        try:
            _create_proxy_video(local_path, proxy_path)
        except RuntimeError as e:
            current_app.logger.error(f"ffmpeg error: {e}")
            raise Exception(f'Failed to create proxy video: {e}')

        proxy_s3_key = None  # No S3 upload
        proxy_size = os.path.getsize(proxy_path)
        proxy_local_path = proxy_path

    # Extract media metadata from proxy
    try:
        from app.utils.media_metadata import extract_media_metadata
        proxy_metadata = extract_media_metadata(proxy_path)
    except Exception as e:
        current_app.logger.warning(f"Failed to extract proxy metadata: {e}")
        proxy_metadata = {
            'resolution_width': 1280,
            'resolution_height': 720,
            'frame_rate': 15.0
        }

    # Create proxy file record in database
    proxy_id = db.create_proxy_file(
        source_file_id=file_id,
        filename=proxy_filename,
        s3_key=proxy_s3_key,
        size_bytes=proxy_size,
        content_type='video/mp4',
        local_path=proxy_local_path,
        resolution_width=proxy_metadata.get('resolution_width', 1280),
        resolution_height=proxy_metadata.get('resolution_height', 720),
        frame_rate=proxy_metadata.get('frame_rate', 15.0),
        codec_video=proxy_metadata.get('codec_video'),
        codec_audio=proxy_metadata.get('codec_audio'),
        duration_seconds=proxy_metadata.get('duration_seconds'),
        bitrate=proxy_metadata.get('bitrate'),
        metadata={
            'proxy_spec': proxy_spec,
            'uploaded_to_s3': upload_to_s3
        }
    )

    return {
        'file_id': file_id,
        'proxy_id': proxy_id,
        's3_key': proxy_s3_key,
        'local_path': proxy_local_path,
        'size_bytes': proxy_size,
        'uploaded_to_s3': upload_to_s3
    }


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

        # Use internal function
        result = create_proxy_internal(file_id, force)
        return jsonify(result), 201

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
            duration_seconds = file.get('duration_seconds') or (file.get('metadata') or {}).get('duration_seconds')
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

        # Generate presigned URL for viewing (only if file is in S3)
        presigned_url = None
        if file.get('s3_key'):
            s3_service = get_s3_service(current_app)
            presigned_url = s3_service.generate_presigned_url(file['s3_key'])

        return jsonify({
            'id': file['id'],
            'filename': file['filename'],
            's3_key': file.get('s3_key'),
            'file_type': file['file_type'],
            'size': format_file_size(_get_display_size_bytes(file)),
            'size_bytes': _get_display_size_bytes(file),
            'duration_seconds': file.get('duration_seconds') or (file.get('metadata') or {}).get('duration_seconds'),
            'duration': _format_duration_seconds(file.get('duration_seconds') or (file.get('metadata') or {}).get('duration_seconds')),
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

        # Delete from S3 (only if file is in S3)
        if file.get('s3_key'):
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
