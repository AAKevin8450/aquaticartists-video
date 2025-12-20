"""
Main routes for page rendering.
"""
from flask import Blueprint, render_template, current_app
from app.database import get_db

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Dashboard home page with comprehensive statistics."""
    try:
        db = get_db()

        # Get comprehensive dashboard statistics
        stats = db.get_dashboard_stats()

        # Get active jobs for detail view
        active_jobs = db.list_jobs(status='IN_PROGRESS', limit=10)

        return render_template(
            'index.html',
            stats=stats,
            active_jobs=active_jobs
        )
    except Exception as e:
        current_app.logger.error(f"Dashboard error: {e}", exc_info=True)
        return render_template('index.html', error=str(e), stats={})


@bp.route('/upload')
def upload_page():
    """File upload page."""
    return render_template('upload.html')


@bp.route('/collections')
def collections_page():
    """Face collections page."""
    return render_template('collections.html')


@bp.route('/history')
def history_page():
    """Job history page."""
    # Don't pre-load jobs - let the frontend fetch them via AJAX
    # This ensures consistent formatting between initial page load and refreshes
    return render_template('history.html', jobs=[])
