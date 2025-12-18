"""
Dashboard routes for visualizing video analysis results.
"""
from flask import Blueprint, render_template, current_app
from app.database import get_db

bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@bp.route('/<job_id>')
def view_dashboard(job_id):
    """
    Display visual dashboard for analysis job results.

    Args:
        job_id: Job ID to display dashboard for

    Returns:
        Rendered dashboard template
    """
    try:
        db = get_db()
        job = db.get_job(job_id)

        if not job:
            return render_template('dashboard.html', error='Job not found'), 404

        # Get associated file info
        file = db.get_file(job['file_id'])

        # Pass job_id to template - data will be fetched via API on client side
        return render_template(
            'dashboard.html',
            job_id=job_id,
            job=job,
            file=file
        )

    except Exception as e:
        current_app.logger.error(f"Dashboard error: {e}")
        return render_template('dashboard.html', error=str(e)), 500
