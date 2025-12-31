"""
Import job endpoints.

Routes:
- POST /api/files/import-directory - Start an async import job
- GET /api/files/import-directory/<job_id>/status - Get import job status
- POST /api/files/import-directory/<job_id>/cancel - Cancel import job
"""
from flask import Blueprint, request, jsonify, current_app
from app.database import get_db
import os

bp = Blueprint('import_jobs', __name__)


@bp.route('/api/files/import-directory', methods=['POST'])
def import_directory():
    """
    Start an async import job for a directory.

    Expected JSON:
        {
            "directory_path": "E:\\videos",
            "recursive": true
        }

    Response:
        {
            "success": true,
            "job_id": "import_abc123def456",
            "message": "Import job started"
        }
    """
    try:
        from app.services.import_service import ImportService

        data = request.get_json() or {}
        directory_path = data.get('directory_path')
        recursive = bool(data.get('recursive', True))

        if not directory_path:
            return jsonify({'error': 'directory_path is required'}), 400

        if not os.path.isdir(directory_path):
            return jsonify({'error': f'Directory not found: {directory_path}'}), 404

        # Create job
        db = get_db()
        job_id = ImportService.generate_job_id()
        db.create_import_job(job_id, directory_path, recursive)

        # Start async import
        import_service = ImportService(db, current_app._get_current_object())
        import_service.run_import_job_async(job_id, directory_path, recursive)

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Import job started'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Import directory error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to start import'}), 500


@bp.route('/api/files/import-directory/<job_id>/status', methods=['GET'])
def get_import_status(job_id):
    """
    Get status of an import job.

    Response:
    {
        "success": true,
        "job": {
            "job_id": "import_abc123",
            "status": "IN_PROGRESS",
            "progress_percent": 45,
            "files_scanned": 234,
            "files_imported": 180,
            "files_skipped_existing": 40,
            "files_skipped_unsupported": 14,
            "total_files": 520,
            "current_operation": "Importing files...",
            "results": {...}  // Only present when completed
        }
    }
    """
    try:
        db = get_db()
        job = db.get_import_job(job_id)

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify({
            'success': True,
            'job': job
        }), 200

    except Exception as e:
        current_app.logger.error(f"Get import status error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/import-directory/<job_id>/cancel', methods=['POST'])
def cancel_import_job(job_id):
    """
    Cancel a running import job.

    Response:
    {
        "success": true,
        "message": "Job cancelled"
    }
    """
    try:
        db = get_db()
        job = db.get_import_job(job_id)

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        if job['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            return jsonify({'error': 'Job already completed'}), 400

        db.cancel_import_job(job_id)

        return jsonify({
            'success': True,
            'message': 'Job cancelled'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Cancel import job error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
