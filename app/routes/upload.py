"""
Upload routes for file management.
"""
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from app.services.s3_service import get_s3_service, S3Error
from app.database import get_db
from app.utils.validators import (
    validate_file_type, validate_file_size, sanitize_filename,
    get_file_type, ValidationError
)
from app.utils.formatters import format_file_size, format_timestamp
import uuid

bp = Blueprint('upload', __name__, url_prefix='/api/upload')


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
        s3_key = f"uploads/{uuid.uuid4()}/{safe_filename}"

        # Get file size BEFORE uploading
        file.seek(0, 2)  # Seek to end
        size_bytes = file.tell()
        file.seek(0)  # Reset to beginning for upload

        # Upload to S3
        s3_service = get_s3_service(current_app)
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
            's3_key': s3_key
        }), 201

    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except S3Error as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        current_app.logger.error(f"Direct upload error: {e}")
        return jsonify({'error': 'Failed to upload file'}), 500


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
            formatted_files.append({
                'id': file['id'],
                'filename': file['filename'],
                's3_key': file['s3_key'],
                'file_type': file['file_type'],
                'size': format_file_size(file['size_bytes']),
                'size_bytes': file['size_bytes'],
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
            'size': format_file_size(file['size_bytes']),
            'size_bytes': file['size_bytes'],
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
