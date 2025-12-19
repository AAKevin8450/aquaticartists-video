"""
History routes for viewing past analysis jobs.
"""
from flask import Blueprint, request, jsonify, current_app, send_file
from app.database import get_db
from app.utils.formatters import format_timestamp, format_analysis_type
from app.utils.excel_exporter import export_to_excel

bp = Blueprint('history', __name__, url_prefix='/api/history')


@bp.route('/', methods=['GET'])
def list_jobs():
    """
    List analysis jobs with optional filters.

    Query parameters:
        - file_id: Filter by file ID
        - status: Filter by job status
        - analysis_type: Filter by analysis type
        - limit: Maximum number of jobs (default 100)
        - offset: Pagination offset (default 0)

    Returns:
        {
            "jobs": [...],
            "total": 10
        }
    """
    try:
        file_id = request.args.get('file_id', type=int)
        status = request.args.get('status')
        analysis_type = request.args.get('analysis_type')
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))

        db = get_db()
        jobs = db.list_jobs(file_id=file_id, status=status, analysis_type=analysis_type, limit=limit, offset=offset)

        # Format job data
        formatted_jobs = []
        for job in jobs:
            job_data = {
                'id': job['id'],
                'job_id': job['job_id'],
                'file_id': job['file_id'],
                'analysis_type': job['analysis_type'],
                'analysis_type_display': format_analysis_type(job['analysis_type']),
                'status': job['status'],
                'started_at': format_timestamp(job['started_at']),
                'completed_at': format_timestamp(job['completed_at']),
                'has_results': job.get('results') is not None,
                'has_error': job.get('error_message') is not None
            }

            if job['analysis_type'] == 'nova':
                nova_job = db.get_nova_job_by_analysis_job(job['id'])
                if nova_job:
                    job_data['nova_job_id'] = nova_job['id']
                    job_data['nova_status'] = nova_job.get('status')
                    job_data['nova_progress_percent'] = nova_job.get('progress_percent')
                    job_data['nova_model'] = nova_job.get('model')
                    job_data['nova_chunk_count'] = nova_job.get('chunk_count')
                    job_data['nova_batch_status'] = nova_job.get('batch_status')
                    job_data['nova_batch_mode'] = nova_job.get('batch_mode')
            formatted_jobs.append(job_data)

        return jsonify({
            'jobs': formatted_jobs,
            'total': len(formatted_jobs)
        }), 200

    except Exception as e:
        current_app.logger.error(f"List jobs error: {e}")
        return jsonify({'error': 'Failed to list jobs'}), 500


@bp.route('/<job_id>', methods=['GET'])
def get_job_details(job_id):
    """
    Get detailed job information including results.

    Returns:
        {
            "job_id": "...",
            "file_id": 123,
            "analysis_type": "...",
            "status": "...",
            "results": {...},
            "error_message": "...",
            "started_at": "...",
            "completed_at": "..."
        }
    """
    try:
        db = get_db()
        job = db.get_job(job_id)

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        # Get associated file info
        file = db.get_file(job['file_id'])

        response = {
            'job_id': job['job_id'],
            'file_id': job['file_id'],
            'file_name': file['filename'] if file else 'Unknown',
            'analysis_type': job['analysis_type'],
            'analysis_type_display': format_analysis_type(job['analysis_type']),
            'status': job['status'],
            'parameters': job.get('parameters'),
            'results': job.get('results'),
            'error_message': job.get('error_message'),
            'started_at': format_timestamp(job['started_at']),
            'completed_at': format_timestamp(job['completed_at'])
        }

        if job['analysis_type'] == 'nova':
            nova_job = db.get_nova_job_by_analysis_job(job['id'])
            if nova_job:
                response['nova_job_id'] = nova_job['id']
                response['nova_status'] = nova_job.get('status')
                response['nova_progress_percent'] = nova_job.get('progress_percent')
                response['nova_batch_status'] = nova_job.get('batch_status')
                response['nova_batch_mode'] = nova_job.get('batch_mode')

        return jsonify(response), 200

    except Exception as e:
        current_app.logger.error(f"Get job details error: {e}")
        return jsonify({'error': 'Failed to get job details'}), 500


@bp.route('/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    """
    Delete a job record from history.

    Returns:
        {
            "message": "Job deleted successfully"
        }
    """
    try:
        db = get_db()
        success = db.delete_job(job_id)

        if not success:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify({'message': 'Job deleted successfully'}), 200

    except Exception as e:
        current_app.logger.error(f"Delete job error: {e}")
        return jsonify({'error': 'Failed to delete job'}), 500


@bp.route('/<job_id>/download', methods=['GET'])
def download_job_results(job_id):
    """
    Download job results in specified format.

    Query parameters:
        - format: 'json' or 'excel' (default: 'json')

    Returns:
        File download (JSON or Excel)
    """
    try:
        format_type = request.args.get('format', 'json').lower()

        db = get_db()
        job = db.get_job(job_id)

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        # Get associated file info
        file = db.get_file(job['file_id'])

        job_data = {
            'job_id': job['job_id'],
            'file_id': job['file_id'],
            'file_name': file['filename'] if file else 'Unknown',
            'analysis_type': job['analysis_type'],
            'analysis_type_display': format_analysis_type(job['analysis_type']),
            'status': job['status'],
            'parameters': job.get('parameters'),
            'results': job.get('results'),
            'error_message': job.get('error_message'),
            'started_at': format_timestamp(job['started_at']),
            'completed_at': format_timestamp(job['completed_at'])
        }

        if job['analysis_type'] == 'nova':
            nova_job = db.get_nova_job_by_analysis_job(job['id'])
            if nova_job:
                job_data['nova_job_id'] = nova_job['id']
                job_data['nova_status'] = nova_job.get('status')
                job_data['nova_progress_percent'] = nova_job.get('progress_percent')
                job_data['nova_batch_status'] = nova_job.get('batch_status')
                job_data['nova_batch_mode'] = nova_job.get('batch_mode')

        if format_type == 'excel':
            # Generate Excel file
            excel_file = export_to_excel(job_data)
            filename = f"job-{job_id}-results.xlsx"

            return send_file(
                excel_file,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=filename
            )
        else:
            # Return JSON
            return jsonify(job_data), 200

    except Exception as e:
        current_app.logger.error(f"Download job results error: {e}")
        return jsonify({'error': f'Failed to download results: {str(e)}'}), 500
