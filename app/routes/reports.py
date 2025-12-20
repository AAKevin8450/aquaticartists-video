"""
Reports routes for usage and processing analytics.
"""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, current_app
from app.database import get_db

bp = Blueprint('reports', __name__, url_prefix='/reports')


def _parse_date(value: str):
    """Parse YYYY-MM-DD into a date object."""
    return datetime.strptime(value, '%Y-%m-%d').date()


def _date_range_defaults():
    """Return default date range (last 7 days)."""
    today = datetime.now().date()
    start = today - timedelta(days=6)
    return start, today


@bp.route('/')
def reports_page():
    """Render the reports page."""
    return render_template('reports.html')


@bp.route('/api/summary')
def reports_summary():
    """Return report summary for the provided date range."""
    try:
        start_raw = request.args.get('start')
        end_raw = request.args.get('end')

        if start_raw and end_raw:
            start_date = _parse_date(start_raw)
            end_date = _parse_date(end_raw)
        else:
            start_date, end_date = _date_range_defaults()

        if start_date > end_date:
            return jsonify({'error': 'start must be on or before end'}), 400

        start_str = start_date.isoformat()
        end_str = end_date.isoformat()

        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    COUNT(*) as nova_jobs,
                    COALESCE(SUM(tokens_total), 0) as tokens_total,
                    COALESCE(SUM(tokens_input), 0) as tokens_input,
                    COALESCE(SUM(tokens_output), 0) as tokens_output,
                    COALESCE(SUM(cost_usd), 0) as cost_total,
                    COALESCE(AVG(processing_time_seconds), 0) as avg_processing_time,
                    COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as nova_completed,
                    COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as nova_failed,
                    COUNT(CASE WHEN status = 'IN_PROGRESS' THEN 1 END) as nova_running,
                    COUNT(CASE WHEN status = 'SUBMITTED' THEN 1 END) as nova_submitted
                FROM nova_jobs
                WHERE date(created_at) BETWEEN date(?) AND date(?)
            ''', (start_str, end_str))
            nova_stats = dict(cursor.fetchone())

            cursor.execute('''
                SELECT
                    COUNT(*) as total_jobs,
                    COUNT(CASE WHEN status IN ('SUCCEEDED', 'COMPLETED') THEN 1 END) as success_jobs,
                    COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_jobs,
                    COUNT(CASE WHEN status = 'IN_PROGRESS' THEN 1 END) as running_jobs,
                    COUNT(CASE WHEN status = 'SUBMITTED' THEN 1 END) as submitted_jobs
                FROM analysis_jobs
                WHERE date(started_at) BETWEEN date(?) AND date(?)
            ''', (start_str, end_str))
            job_stats = dict(cursor.fetchone())

            cursor.execute('''
                SELECT COUNT(DISTINCT aj.file_id) as files_processed
                FROM analysis_jobs aj
                WHERE date(aj.started_at) BETWEEN date(?) AND date(?)
            ''', (start_str, end_str))
            files_processed = cursor.fetchone()['files_processed']

            cursor.execute('''
                SELECT
                    COUNT(*) as files_uploaded,
                    COALESCE(SUM(size_bytes), 0) as upload_bytes,
                    COALESCE(SUM(duration_seconds), 0) as upload_duration,
                    COUNT(CASE WHEN file_type = 'video' THEN 1 END) as uploaded_videos,
                    COUNT(CASE WHEN file_type = 'image' THEN 1 END) as uploaded_images
                FROM files f
                WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)
                  AND date(f.uploaded_at) BETWEEN date(?) AND date(?)
            ''', (start_str, end_str))
            file_upload_stats = dict(cursor.fetchone())

            cursor.execute('''
                SELECT f.file_type, COUNT(DISTINCT f.id) as count
                FROM files f
                JOIN analysis_jobs aj ON aj.file_id = f.id
                WHERE date(aj.started_at) BETWEEN date(?) AND date(?)
                GROUP BY f.file_type
                ORDER BY count DESC
            ''', (start_str, end_str))
            file_types = [dict(row) for row in cursor.fetchall()]

            cursor.execute('''
                SELECT f.content_type, COUNT(DISTINCT f.id) as count
                FROM files f
                JOIN analysis_jobs aj ON aj.file_id = f.id
                WHERE date(aj.started_at) BETWEEN date(?) AND date(?)
                GROUP BY f.content_type
                ORDER BY count DESC
                LIMIT 8
            ''', (start_str, end_str))
            content_types = [dict(row) for row in cursor.fetchall()]

            cursor.execute('''
                SELECT
                    CASE
                        WHEN INSTR(f.filename, '.') > 0
                        THEN LOWER(SUBSTR(f.filename, INSTR(f.filename, '.') + 1))
                        ELSE 'unknown'
                    END as extension,
                    COUNT(DISTINCT f.id) as count
                FROM files f
                JOIN analysis_jobs aj ON aj.file_id = f.id
                WHERE date(aj.started_at) BETWEEN date(?) AND date(?)
                GROUP BY extension
                ORDER BY count DESC
                LIMIT 8
            ''', (start_str, end_str))
            extensions = [dict(row) for row in cursor.fetchall()]

            cursor.execute('''
                SELECT analysis_type, COUNT(*) as count
                FROM analysis_jobs
                WHERE date(started_at) BETWEEN date(?) AND date(?)
                GROUP BY analysis_type
                ORDER BY count DESC
                LIMIT 10
            ''', (start_str, end_str))
            analysis_types = [dict(row) for row in cursor.fetchall()]

            cursor.execute('''
                SELECT
                    model,
                    COUNT(*) as count,
                    COALESCE(SUM(tokens_total), 0) as tokens_total,
                    COALESCE(SUM(cost_usd), 0) as cost_total
                FROM nova_jobs
                WHERE date(created_at) BETWEEN date(?) AND date(?)
                GROUP BY model
                ORDER BY count DESC
            ''', (start_str, end_str))
            model_breakdown = [dict(row) for row in cursor.fetchall()]

            cursor.execute('''
                SELECT date(created_at) as day,
                       COALESCE(SUM(tokens_total), 0) as tokens_total,
                       COALESCE(SUM(cost_usd), 0) as cost_total
                FROM nova_jobs
                WHERE date(created_at) BETWEEN date(?) AND date(?)
                GROUP BY day
                ORDER BY day
            ''', (start_str, end_str))
            tokens_by_day = {row['day']: dict(row) for row in cursor.fetchall()}

            cursor.execute('''
                SELECT date(started_at) as day,
                       COUNT(*) as total_jobs,
                       COUNT(CASE WHEN status IN ('SUCCEEDED', 'COMPLETED') THEN 1 END) as success_jobs,
                       COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_jobs
                FROM analysis_jobs
                WHERE date(started_at) BETWEEN date(?) AND date(?)
                GROUP BY day
                ORDER BY day
            ''', (start_str, end_str))
            jobs_by_day = {row['day']: dict(row) for row in cursor.fetchall()}

            cursor.execute('''
                SELECT
                    COUNT(*) as total_transcripts,
                    COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as completed_transcripts
                FROM transcripts
                WHERE date(created_at) BETWEEN date(?) AND date(?)
            ''', (start_str, end_str))
            transcript_stats = dict(cursor.fetchone())

        # Fill missing days for charting
        daily = []
        day_cursor = start_date
        while day_cursor <= end_date:
            day_key = day_cursor.isoformat()
            tokens_row = tokens_by_day.get(day_key, {})
            jobs_row = jobs_by_day.get(day_key, {})
            daily.append({
                'day': day_key,
                'tokens_total': tokens_row.get('tokens_total', 0),
                'cost_total': tokens_row.get('cost_total', 0),
                'jobs_total': jobs_row.get('total_jobs', 0),
                'jobs_success': jobs_row.get('success_jobs', 0),
                'jobs_failed': jobs_row.get('failed_jobs', 0)
            })
            day_cursor += timedelta(days=1)

        return jsonify({
            'range': {
                'start': start_str,
                'end': end_str,
                'days': (end_date - start_date).days + 1
            },
            'tokens': nova_stats,
            'jobs': job_stats,
            'files': {
                'processed': files_processed,
                **file_upload_stats
            },
            'file_types': {
                'by_type': file_types,
                'by_content_type': content_types,
                'by_extension': extensions
            },
            'analysis_types': analysis_types,
            'nova_models': model_breakdown,
            'transcripts': transcript_stats,
            'daily': daily
        })

    except ValueError as exc:
        return jsonify({'error': f'invalid date format: {exc}'}), 400
    except Exception as exc:
        current_app.logger.error(f"Reports summary error: {exc}", exc_info=True)
        return jsonify({'error': 'failed to load report summary'}), 500
