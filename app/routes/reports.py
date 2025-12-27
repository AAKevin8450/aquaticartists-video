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
                    COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as success_jobs,
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
                       COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as success_jobs,
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


@bp.route('/api/billing/summary')
def billing_summary():
    """
    Get AWS billing summary from Cost and Usage Reports.

    Query params:
        - start: Start date (YYYY-MM-DD), defaults to 7 days ago
        - end: End date (YYYY-MM-DD), defaults to today
        - refresh: Force refresh from S3 (true/false), defaults to false

    Returns:
        {
            'range': {'start': '2025-01-01', 'end': '2025-01-31', 'days': 31},
            'total_cost': 123.45,
            'services': [
                {'service_code': 'AmazonS3', 'service_name': 'Amazon S3',
                 'cost': 45.67, 'percent': 37.0},
                ...
            ],
            'daily': [{'day': '2025-01-01', 'cost': 4.12}, ...],
            'cached': true,
            'last_sync': '2025-01-15T10:30:00Z'
        }
    """
    from app.services.billing_service import get_billing_service, BillingError, get_operation_display_name
    from app.database import get_db
    from datetime import datetime, timedelta
    from collections import defaultdict

    try:
        # Get billing service
        billing_service = get_billing_service(current_app)
        if not billing_service:
            return jsonify({'error': 'Billing not configured. Set BILLING_BUCKET_NAME in .env'}), 503

        db = get_db()

        # Parse date range
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        refresh = request.args.get('refresh', '').lower() == 'true'

        if not start_date or not end_date:
            # Default to last 7 days
            end = datetime.now()
            start = end - timedelta(days=7)
            start_date = start.strftime('%Y-%m-%d')
            end_date = end.strftime('%Y-%m-%d')

        # Validate date format
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            if start_dt > end_dt:
                return jsonify({'error': 'start_date must be before end_date'}), 400
        except ValueError as e:
            return jsonify({'error': f'Invalid date format: {e}'}), 400

        # Calculate days in range
        days = (end_dt - start_dt).days + 1

        # Check cache first unless refresh requested
        cached_data = db.get_cached_billing_data(start_date, end_date) if not refresh else []
        last_sync = db.get_latest_billing_sync()

        if cached_data and not refresh:
            # Use cached data
            # Aggregate by service
            service_costs = defaultdict(float)
            daily_costs = defaultdict(float)

            for row in cached_data:
                service_costs[row['service_code']] += row['cost_usd']
                daily_costs[row['usage_date']] += row['cost_usd']

            # Build service list
            total_cost = sum(service_costs.values())
            services = []
            for service_code, cost in service_costs.items():
                # Get service name from cached_data
                service_name = next(
                    (r['service_name'] for r in cached_data if r['service_code'] == service_code),
                    service_code
                )
                percent = (cost / total_cost * 100) if total_cost > 0 else 0
                services.append({
                    'service_code': service_code,
                    'service_name': service_name,
                    'cost': cost,
                    'percent': percent
                })

            # Sort by cost descending
            services.sort(key=lambda x: x['cost'], reverse=True)

            # Get detailed operations from cache
            cached_details = db.get_cached_billing_details(start_date, end_date)

            # Enhance services list with operations
            for service in services:
                service_code = service['service_code']
                operations = cached_details.get(service_code, [])

                # Calculate percentages for operations
                service_total = service['cost']
                for op in operations:
                    op['operation_name'] = get_operation_display_name(
                        op['operation'],
                        service_code,
                        op.get('usage_type')
                    )
                    op['percent'] = (op['cost'] / service_total * 100) if service_total > 0 else 0

                service['operations'] = operations

            # Build daily list with zero-filling
            daily = []
            current = start_dt
            while current <= end_dt:
                day_str = current.strftime('%Y-%m-%d')
                daily.append({
                    'day': day_str,
                    'cost': daily_costs.get(day_str, 0.0)
                })
                current += timedelta(days=1)

            return jsonify({
                'range': {
                    'start': start_date,
                    'end': end_date,
                    'days': days
                },
                'total_cost': total_cost,
                'services': services,
                'daily': daily,
                'cached': True,
                'last_sync': last_sync['sync_completed_at'] if last_sync else None
            })

        else:
            # Fetch from S3 and cache
            current_app.logger.info(f"Fetching billing data from S3 for {start_date} to {end_date}")

            # Create sync log
            sync_id = db.create_billing_sync_log(start_date, end_date)

            try:
                # Fetch from S3
                billing_data = billing_service.fetch_cur_data(start_date, end_date)

                # Clear existing cache for this date range
                db.clear_billing_cache(start_date, end_date)
                db.clear_billing_details(start_date, end_date)

                # Cache the data using the detailed service_by_date breakdown
                service_by_date = billing_data.get('service_by_date', {})
                service_names = {s['service_code']: s['service_name'] for s in billing_data['services']}

                for service_code, date_costs in service_by_date.items():
                    service_name = service_names.get(service_code, service_code)
                    for date, cost in date_costs.items():
                        db.cache_billing_data(
                            service_code,
                            service_name,
                            date,
                            cost
                        )

                # Cache detailed operations
                operations_by_service = billing_data.get('operations_by_service', {})
                for service_code, operations in operations_by_service.items():
                    for op in operations:
                        # Need to distribute costs across dates proportionally
                        # Get this service's daily costs from service_by_date
                        service_daily = service_by_date.get(service_code, {})
                        total_service_cost = sum(service_daily.values())

                        # Calculate operation's share
                        op_share = op['cost'] / total_service_cost if total_service_cost > 0 else 0

                        # Distribute across dates
                        for date, daily_cost in service_daily.items():
                            op_cost_for_date = daily_cost * op_share
                            op_usage_for_date = op['usage_amount'] * op_share  # Approximate

                            db.cache_billing_detail(
                                service_code,
                                op['operation'],
                                op['usage_type'],
                                date,
                                op_usage_for_date,
                                op_cost_for_date
                            )

                # Enhance services with operations before returning
                for service in billing_data['services']:
                    service_code = service['service_code']
                    service['operations'] = operations_by_service.get(service_code, [])

                # Update sync log
                db.update_billing_sync_log(
                    sync_id,
                    'COMPLETED',
                    billing_data['rows_processed']
                )

                return jsonify({
                    'range': {
                        'start': start_date,
                        'end': end_date,
                        'days': days
                    },
                    'total_cost': billing_data['total_cost'],
                    'services': billing_data['services'],
                    'daily': billing_data['daily'],
                    'cached': False,
                    'last_sync': datetime.now().isoformat()
                })

            except BillingError as e:
                # Update sync log with error
                db.update_billing_sync_log(sync_id, 'FAILED', 0, str(e))
                current_app.logger.error(f"Billing fetch error: {e}")
                return jsonify({'error': str(e)}), 500

    except Exception as e:
        current_app.logger.error(f"Billing summary error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to load billing summary'}), 500
