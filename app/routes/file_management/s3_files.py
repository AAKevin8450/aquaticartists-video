"""
S3 file browser endpoints.

Routes:
- GET /api/s3-files - List all files in S3 bucket
- GET /api/s3-file/<path:s3_key>/download-url - Get presigned download URL
- DELETE /api/s3-file/<path:s3_key> - Delete a file from S3
- POST /api/s3-files/delete-all - Delete all files from S3
"""
from flask import Blueprint, request, jsonify, current_app
from app.database import get_db
from app.services.s3_service import get_s3_service
from app.utils.formatters import format_timestamp, format_file_size

bp = Blueprint('s3_files', __name__)


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
