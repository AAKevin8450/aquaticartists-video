"""
Rescan job endpoints.

Routes:
- POST /api/files/rescan - Start an async rescan job
- GET /api/files/rescan/<job_id>/status - Get rescan job status
- POST /api/files/rescan/<job_id>/cancel - Cancel rescan job
- POST /api/files/rescan/apply - Apply changes detected by rescan
"""
from flask import Blueprint, request, jsonify, current_app
from app.database import get_db
from pathlib import Path

bp = Blueprint('rescan_jobs', __name__)


@bp.route('/api/files/rescan', methods=['POST'])
def rescan_directory():
    """
    Start an async rescan job for a directory.

    Request body:
    {
        "directory_path": "/path/to/scan",
        "recursive": true
    }

    Response:
    {
        "success": true,
        "job_id": "rescan_abc123def456",
        "message": "Rescan job started"
    }
    """
    try:
        from app.services.rescan_service import RescanService

        data = request.get_json()
        directory_path = data.get('directory_path')
        recursive = data.get('recursive', True)

        if not directory_path:
            return jsonify({'error': 'directory_path is required'}), 400

        # Validate directory exists
        dir_path = Path(directory_path)
        if not dir_path.exists():
            return jsonify({'error': 'Directory does not exist'}), 400
        if not dir_path.is_dir():
            return jsonify({'error': 'Path is not a directory'}), 400

        # Create job
        db = get_db()
        job_id = RescanService.generate_job_id()
        db.create_rescan_job(job_id, directory_path, recursive)

        # Start async rescan
        rescan_service = RescanService(db)
        rescan_service.run_rescan_job_async(job_id, directory_path, recursive)

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': 'Rescan job started'
        }), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Rescan error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/rescan/<job_id>/status', methods=['GET'])
def get_rescan_status(job_id):
    """
    Get status of a rescan job.

    Response:
    {
        "success": true,
        "job": {
            "job_id": "rescan_abc123",
            "status": "IN_PROGRESS",
            "progress_percent": 45,
            "files_scanned": 234,
            "total_files": 520,
            "current_operation": "Scanning filesystem...",
            "results": {...}  // Only present when completed
        }
    }
    """
    try:
        db = get_db()
        job = db.get_rescan_job(job_id)

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify({
            'success': True,
            'job': job
        }), 200

    except Exception as e:
        current_app.logger.error(f"Get rescan status error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/rescan/<job_id>/cancel', methods=['POST'])
def cancel_rescan_job(job_id):
    """
    Cancel a running rescan job.

    Response:
    {
        "success": true,
        "message": "Job cancelled"
    }
    """
    try:
        db = get_db()
        job = db.get_rescan_job(job_id)

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        if job['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            return jsonify({'error': 'Job already completed'}), 400

        db.cancel_rescan_job(job_id)

        return jsonify({
            'success': True,
            'message': 'Job cancelled'
        }), 200

    except Exception as e:
        current_app.logger.error(f"Cancel rescan job error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@bp.route('/api/files/rescan/apply', methods=['POST'])
def apply_rescan_changes():
    """
    Apply changes detected by rescan.

    Request body:
    {
        "directory_path": "/path/to/scan",
        "actions": {
            "update_moved": true,
            "delete_missing": true,
            "import_new": false,
            "handle_ambiguous": "skip"
        },
        "selected_files": {
            "moved": [1, 3, 5],       // File IDs to update
            "deleted": [2],            // File IDs to delete
            "new": ["/path/to/new.mp4"] // Paths to import
        }
    }

    Response:
    {
        "success": true,
        "results": {
            "updated": 3,
            "deleted": 1,
            "imported": 0,
            "skipped": 0,
            "errors": []
        }
    }
    """
    try:
        from app.services.rescan_service import RescanService

        data = request.get_json()
        directory_path = data.get('directory_path')
        actions = data.get('actions', {})
        selected_files = data.get('selected_files', {})

        if not directory_path:
            return jsonify({'error': 'directory_path is required'}), 400

        # Create rescan service with app for import functionality
        db = get_db()
        rescan_service = RescanService(db, app=current_app._get_current_object())
        reconcile_results = rescan_service.reconcile(directory_path, mode='smart')

        # Apply changes
        options = {
            'update_moved': actions.get('update_moved', True),
            'delete_missing': actions.get('delete_missing', False),
            'import_new': actions.get('import_new', False),
            'handle_ambiguous': actions.get('handle_ambiguous', 'skip'),
            'selected_files': selected_files,
            'directory_path': directory_path  # Pass for import metadata
        }

        results = rescan_service.apply_changes(reconcile_results, options)

        return jsonify({
            'success': True,
            'results': results
        }), 200

    except Exception as e:
        current_app.logger.error(f"Apply rescan error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
