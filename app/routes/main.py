"""
Main routes for page rendering.
"""
from flask import Blueprint, render_template, current_app
from app.database import get_db
from app.utils.formatters import format_file_size, format_duration

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """Dashboard home page."""
    try:
        db = get_db()

        # Get statistics
        recent_files = db.list_files(limit=5)
        recent_jobs = db.list_jobs(limit=5)
        active_jobs = db.list_jobs(status='IN_PROGRESS', limit=10)

        total_files = len(db.list_files(limit=1000))
        total_jobs = len(db.list_jobs(limit=1000))

        return render_template(
            'index.html',
            recent_files=recent_files,
            recent_jobs=recent_jobs,
            active_jobs=active_jobs,
            total_files=total_files,
            total_jobs=total_jobs
        )
    except Exception as e:
        current_app.logger.error(f"Dashboard error: {e}")
        return render_template('index.html', error=str(e))


@bp.route('/upload')
def upload_page():
    """File upload page."""
    return render_template('upload.html')


@bp.route('/video-analysis')
def video_analysis_page():
    """Video analysis page."""
    try:
        db = get_db()
        video_files = db.list_files(file_type='video', limit=100)
        for file in video_files:
            metadata = file.get('metadata') or {}
            size_bytes = metadata.get('original_size_bytes', file.get('size_bytes'))
            duration_seconds = metadata.get('duration_seconds')
            file['display_size'] = format_file_size(size_bytes) if size_bytes is not None else 'N/A'
            file['display_duration'] = (
                format_duration(int(duration_seconds * 1000))
                if isinstance(duration_seconds, (int, float)) else 'N/A'
            )
        return render_template('video_analysis.html', files=video_files)
    except Exception as e:
        current_app.logger.error(f"Video analysis page error: {e}")
        return render_template('video_analysis.html', files=[], error=str(e))


@bp.route('/image-analysis')
def image_analysis_page():
    """Image analysis page."""
    try:
        db = get_db()
        image_files = db.list_files(file_type='image', limit=100)
        return render_template('image_analysis.html', files=image_files)
    except Exception as e:
        current_app.logger.error(f"Image analysis page error: {e}")
        return render_template('image_analysis.html', files=[], error=str(e))


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
