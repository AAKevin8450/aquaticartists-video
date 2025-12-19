"""
AWS Nova video analysis routes.
Provides API endpoints for intelligent video comprehension using Amazon Nova models.
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.nova_service import NovaVideoService, NovaError
from app.database import get_db
import json
import logging
from datetime import datetime
import traceback

logger = logging.getLogger(__name__)

bp = Blueprint('nova_analysis', __name__, url_prefix='/api/nova')


def get_nova_service():
    """Get configured Nova service instance."""
    return NovaVideoService(
        bucket_name=current_app.config['S3_BUCKET_NAME'],
        region=current_app.config['AWS_REGION'],
        aws_access_key=current_app.config.get('AWS_ACCESS_KEY_ID'),
        aws_secret_key=current_app.config.get('AWS_SECRET_ACCESS_KEY')
    )


@bp.route('/analyze', methods=['POST'])
def start_nova_analysis():
    """
    Start Nova video analysis.

    Expected JSON:
        {
            "file_id": 123,
            "model": "lite",  # 'micro', 'lite', 'pro', 'premier'
            "analysis_types": ["summary", "chapters", "elements"],
            "options": {
                "summary_depth": "standard",  # 'brief', 'standard', 'detailed'
                "language": "auto"  # 'auto' or ISO code like 'en', 'es'
            }
        }

    Returns:
        {
            "nova_job_id": 1,
            "analysis_job_id": 123,
            "status": "IN_PROGRESS",
            "model": "lite",
            "analysis_types": ["summary", "chapters"],
            "estimated_cost": {
                "total_cost_usd": 0.05,
                "model": "lite"
            }
        }
    """
    try:
        data = request.get_json()
        file_id = data.get('file_id')
        model = data.get('model', 'lite')
        analysis_types = data.get('analysis_types', ['summary'])
        options = data.get('options', {})
        processing_mode = data.get('processing_mode', options.get('processing_mode', 'realtime'))
        options['processing_mode'] = processing_mode

        # Validate inputs
        if not file_id:
            return jsonify({'error': 'file_id is required'}), 400

        if not isinstance(analysis_types, list) or not analysis_types:
            return jsonify({'error': 'analysis_types must be a non-empty array'}), 400

        valid_models = ['micro', 'lite', 'pro', 'pro_2_preview', 'omni_2_preview', 'premier']
        if model not in valid_models:
            return jsonify({'error': f'model must be one of: {valid_models}'}), 400

        if processing_mode not in ('realtime', 'batch'):
            return jsonify({'error': 'processing_mode must be "realtime" or "batch"'}), 400

        valid_analysis_types = ['summary', 'chapters', 'elements']
        invalid_types = [t for t in analysis_types if t not in valid_analysis_types]
        if invalid_types:
            return jsonify({'error': f'Invalid analysis types: {invalid_types}. Valid types: {valid_analysis_types}'}), 400

        # Get file from database
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        if file['file_type'] != 'video':
            return jsonify({'error': 'File must be a video'}), 400

        s3_key = file['s3_key']

        # Estimate duration for cost estimates and batch fallback
        estimated_duration = file.get('metadata', {}).get('duration_seconds', 300)
        options['estimated_duration_seconds'] = estimated_duration

        # Create analysis job record
        analysis_job_id = db.create_analysis_job(
            file_id=file_id,
            job_id=f"nova-{datetime.utcnow().timestamp()}",
            analysis_type='nova',
            status='SUBMITTED',
            parameters=json.dumps({
                'model': model,
                'analysis_types': analysis_types,
                'options': options,
                'processing_mode': processing_mode
            })
        )

        # Create Nova job record
        nova_job_id = db.create_nova_job(
            analysis_job_id=analysis_job_id,
            model=model,
            analysis_types=analysis_types,
            user_options=options
        )

        logger.info(f"Created Nova job {nova_job_id} for file {file_id}, model: {model}, types: {analysis_types}")

        # Get Nova service
        if processing_mode not in ('realtime', 'batch'):
            return jsonify({'error': 'processing_mode must be "realtime" or "batch"'}), 400

        nova_service = get_nova_service()

        # Estimate cost
        cost_estimate = nova_service.estimate_cost(
            model=model,
            video_duration_seconds=estimated_duration,
            batch_mode=(processing_mode == 'batch')
        )

        try:
            if processing_mode == 'batch':
                batch_job_name = f"nova-batch-{nova_job_id}-{int(datetime.utcnow().timestamp())}"
                batch_response = nova_service.start_batch_analysis(
                    s3_key=s3_key,
                    model=model,
                    analysis_types=analysis_types,
                    options=options,
                    role_arn=current_app.config.get('BEDROCK_BATCH_ROLE_ARN'),
                    input_prefix=current_app.config.get('NOVA_BATCH_INPUT_PREFIX', 'nova/batch/input'),
                    output_prefix=current_app.config.get('NOVA_BATCH_OUTPUT_PREFIX', 'nova/batch/output'),
                    job_name=batch_job_name
                )

                db.update_nova_job(nova_job_id, {
                    'status': 'IN_PROGRESS',
                    'progress_percent': 0,
                    'batch_mode': 1,
                    'batch_job_arn': batch_response['batch_job_arn'],
                    'batch_status': 'SUBMITTED',
                    'batch_input_s3_key': batch_response['batch_input_s3_key'],
                    'batch_output_s3_prefix': batch_response['batch_output_s3_prefix']
                })
                db.update_nova_job_started_at(nova_job_id)
                db.update_analysis_job(analysis_job_id, status='IN_PROGRESS')

                return jsonify({
                    'nova_job_id': nova_job_id,
                    'analysis_job_id': analysis_job_id,
                    'status': 'IN_PROGRESS',
                    'model': model,
                    'analysis_types': analysis_types,
                    'processing_mode': 'batch',
                    'batch_job_arn': batch_response['batch_job_arn'],
                    'estimated_cost': cost_estimate
                }), 202

            # Update status to IN_PROGRESS
            db.update_nova_job_status(nova_job_id, 'IN_PROGRESS', 0)
            db.update_nova_job_started_at(nova_job_id)

            # Define progress callback for chunk progress tracking
            def progress_callback(current_chunk: int, total_chunks: int, status_message: str):
                """Update database with chunk progress."""
                try:
                    db.update_nova_job_chunk_progress(
                        nova_job_id=nova_job_id,
                        current_chunk=current_chunk,
                        total_chunks=total_chunks,
                        status_message=status_message
                    )
                    logger.info(f"Job {nova_job_id}: {status_message}")
                except Exception as e:
                    logger.warning(f"Failed to update chunk progress: {e}")

            # Run analysis
            logger.info(f"Starting Nova analysis for job {nova_job_id}, S3 key: {s3_key}")
            results = nova_service.analyze_video(
                s3_key=s3_key,
                model=model,
                analysis_types=analysis_types,
                options=options,
                progress_callback=progress_callback
            )

            # Store results in database
            update_data = {
                'status': 'COMPLETED',
                'progress_percent': 100,
                'tokens_input': results['totals'].get('tokens_total', 0),  # Will be refined
                'tokens_output': 0,  # Will be calculated per-analysis
                'tokens_total': results['totals']['tokens_total'],
                'processing_time_seconds': results['totals']['processing_time_seconds'],
                'cost_usd': results['totals']['cost_total_usd']
            }

            # Store chunk metadata if video was chunked
            if results.get('chunked', False) and 'chunk_metadata' in results:
                chunk_meta = results['chunk_metadata']
                update_data['is_chunked'] = 1
                update_data['chunk_count'] = chunk_meta['total_chunks']
                update_data['chunk_duration'] = chunk_meta['chunk_duration']
                update_data['overlap_duration'] = chunk_meta['overlap_seconds']

            # Store individual analysis results
            if 'summary' in results:
                update_data['summary_result'] = json.dumps(results['summary'])
                update_data['tokens_input'] = results['summary']['tokens_input']
                update_data['tokens_output'] = results['summary']['tokens_output']

            if 'chapters' in results:
                update_data['chapters_result'] = json.dumps(results['chapters'])

            if 'elements' in results:
                update_data['elements_result'] = json.dumps(results['elements'])

            # Update database
            db.update_nova_job(nova_job_id, update_data)
            db.update_nova_job_completed_at(nova_job_id)

            # Update analysis job status
            db.update_analysis_job(
                analysis_job_id,
                status='COMPLETED',
                results=json.dumps(results)
            )

            logger.info(f"Nova analysis completed for job {nova_job_id}. Cost: ${results['totals']['cost_total_usd']:.4f}")

            return jsonify({
                'nova_job_id': nova_job_id,
                'analysis_job_id': analysis_job_id,
                'status': 'COMPLETED',
                'model': model,
                'analysis_types': analysis_types,
                'processing_mode': processing_mode,
                'results_summary': {
                    'tokens_used': results['totals']['tokens_total'],
                    'cost_usd': results['totals']['cost_total_usd'],
                    'processing_time_seconds': results['totals']['processing_time_seconds'],
                    'analyses_completed': results['totals']['analyses_completed']
                }
            }), 200

        except NovaError as e:
            error_msg = str(e)
            logger.error(f"Nova analysis failed for job {nova_job_id}: {error_msg}")

            # Update job status to FAILED
            db.update_nova_job(nova_job_id, {
                'status': 'FAILED',
                'error_message': error_msg
            })

            db.update_analysis_job(
                analysis_job_id,
                status='FAILED',
                error_message=error_msg
            )

            return jsonify({
                'nova_job_id': nova_job_id,
                'analysis_job_id': analysis_job_id,
                'status': 'FAILED',
                'error': error_msg
            }), 500

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(f"Unexpected error in Nova analysis for job {nova_job_id}: {error_msg}")
            logger.error(traceback.format_exc())

            db.update_nova_job(nova_job_id, {
                'status': 'FAILED',
                'error_message': error_msg
            })

            db.update_analysis_job(
                analysis_job_id,
                status='FAILED',
                error_message=error_msg
            )

            return jsonify({
                'nova_job_id': nova_job_id,
                'analysis_job_id': analysis_job_id,
                'status': 'FAILED',
                'error': error_msg
            }), 500

    except Exception as e:
        logger.error(f"Error in start_nova_analysis: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@bp.route('/status/<int:nova_job_id>', methods=['GET'])
def get_nova_status(nova_job_id):
    """
    Get Nova job status.

    Returns:
        {
            "nova_job_id": 1,
            "status": "IN_PROGRESS",
            "progress_percent": 50,
            "model": "lite",
            "analysis_types": ["summary", "chapters"],
            "created_at": "2025-12-18T10:30:00Z",
            "processing_time_seconds": 45.2
        }
    """
    try:
        db = get_db()
        job = db.get_nova_job(nova_job_id)

        if not job:
            return jsonify({'error': 'Nova job not found'}), 404

        response = {
            'nova_job_id': job['id'],
            'analysis_job_id': job['analysis_job_id'],
            'status': job['status'],
            'progress_percent': job['progress_percent'],
            'model': job['model'],
            'analysis_types': json.loads(job['analysis_types']),
            'created_at': job['created_at'],
            'started_at': job['started_at'],
            'completed_at': job['completed_at']
        }
        response['processing_mode'] = 'batch' if job.get('batch_mode') else 'realtime'

        if job.get('batch_mode'):
            response['processing_mode'] = 'batch'
            response['batch_job_arn'] = job.get('batch_job_arn')
            response['batch_status'] = job.get('batch_status')

        # Include chunk progress information if video is being chunked
        if job.get('is_chunked') or job.get('chunk_count', 0) > 1:
            response['chunk_progress'] = {
                'is_chunked': bool(job.get('is_chunked', 0)),
                'current_chunk': job.get('current_chunk', 0),
                'total_chunks': job.get('chunk_count', 0),
                'status_message': job.get('chunk_status_message'),
                'chunk_duration': job.get('chunk_duration'),
                'overlap_duration': job.get('overlap_duration')
            }

        if job.get('batch_job_arn') and job['status'] not in ('COMPLETED', 'FAILED'):
            nova_service = get_nova_service()
            batch_status = nova_service.get_batch_job_status(job['batch_job_arn'])
            response['batch_status'] = batch_status['status']
            batch_state = (batch_status['status'] or '').upper()
            if batch_status['status']:
                db.update_nova_job(nova_job_id, {
                    'batch_status': batch_status['status']
                })

            if batch_state in ('COMPLETED', 'SUCCEEDED'):
                results = nova_service.fetch_batch_results(
                    s3_prefix=job.get('batch_output_s3_prefix', ''),
                    model=job['model'],
                    analysis_types=json.loads(job['analysis_types']),
                    options=json.loads(job.get('user_options') or '{}')
                )

                update_data = {
                    'status': 'COMPLETED',
                    'progress_percent': 100,
                    'tokens_total': results['totals']['tokens_total'],
                    'processing_time_seconds': results['totals']['processing_time_seconds'],
                    'cost_usd': results['totals']['cost_total_usd'],
                    'batch_status': 'COMPLETED'
                }

                if 'summary' in results:
                    update_data['summary_result'] = json.dumps(results['summary'])
                    update_data['tokens_input'] = results['summary'].get('tokens_input')
                    update_data['tokens_output'] = results['summary'].get('tokens_output')

                if 'chapters' in results:
                    update_data['chapters_result'] = json.dumps(results['chapters'])

                if 'elements' in results:
                    update_data['elements_result'] = json.dumps(results['elements'])

                db.update_nova_job(nova_job_id, update_data)
                db.update_nova_job_completed_at(nova_job_id)

                db.update_analysis_job(
                    job['analysis_job_id'],
                    status='COMPLETED',
                    results=json.dumps(results)
                )

                response['status'] = 'COMPLETED'
                response['progress_percent'] = 100
                response['results_summary'] = {
                    'tokens_total': results['totals']['tokens_total'],
                    'cost_usd': results['totals']['cost_total_usd'],
                    'processing_time_seconds': results['totals']['processing_time_seconds']
                }

            elif batch_state == 'FAILED':
                error_msg = batch_status.get('failure_message') or 'Batch job failed'
                db.update_nova_job(nova_job_id, {
                    'status': 'FAILED',
                    'error_message': error_msg,
                    'batch_status': 'FAILED'
                })
                db.update_analysis_job(
                    job['analysis_job_id'],
                    status='FAILED',
                    error_message=error_msg
                )
                response['status'] = 'FAILED'
                response['error_message'] = error_msg

        if job['status'] == 'COMPLETED':
            response['results_summary'] = {
                'tokens_total': job['tokens_total'],
                'cost_usd': job['cost_usd'],
                'processing_time_seconds': job['processing_time_seconds']
            }

        if job['status'] == 'FAILED':
            response['error_message'] = job['error_message']

        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error getting Nova status: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/results/<int:nova_job_id>', methods=['GET'])
def get_nova_results(nova_job_id):
    """
    Get Nova job results.

    Returns:
        {
            "nova_job_id": 1,
            "status": "COMPLETED",
            "model": "lite",
            "analysis_types": ["summary", "chapters", "elements"],
            "results": {
                "summary": {...},
                "chapters": {...},
                "elements": {...}
            },
            "metadata": {
                "tokens_total": 15234,
                "cost_usd": 0.045,
                "processing_time_seconds": 32.5
            }
        }
    """
    try:
        db = get_db()
        job = db.get_nova_job(nova_job_id)

        if not job:
            return jsonify({'error': 'Nova job not found'}), 404

        if job['status'] != 'COMPLETED':
            return jsonify({
                'error': 'Job not completed yet',
                'status': job['status'],
                'progress_percent': job['progress_percent']
            }), 400

        results = {}

        if job['summary_result']:
            results['summary'] = json.loads(job['summary_result'])

        if job['chapters_result']:
            results['chapters'] = json.loads(job['chapters_result'])

        if job['elements_result']:
            results['elements'] = json.loads(job['elements_result'])

        response = {
            'nova_job_id': job['id'],
            'analysis_job_id': job['analysis_job_id'],
            'status': job['status'],
            'model': job['model'],
            'analysis_types': json.loads(job['analysis_types']),
            'results': results,
            'metadata': {
                'tokens_input': job['tokens_input'],
                'tokens_output': job['tokens_output'],
                'tokens_total': job['tokens_total'],
                'cost_usd': job['cost_usd'],
                'processing_time_seconds': job['processing_time_seconds'],
                'created_at': job['created_at'],
                'started_at': job['started_at'],
                'completed_at': job['completed_at'],
                'processing_mode': 'batch' if job.get('batch_mode') else 'realtime'
            }
        }

        return jsonify(response), 200

    except Exception as e:
        logger.error(f"Error getting Nova results: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/models', methods=['GET'])
def get_available_models():
    """
    Get list of available Nova models with pricing and capabilities.

    Returns:
        {
            "models": [
                {
                    "id": "micro",
                    "name": "Nova Micro",
                    "context_tokens": 128000,
                    "max_video_minutes": 12,
                    "price_input_per_1k": 0.035,
                    "price_output_per_1k": 0.14,
                    "best_for": "Quick summaries, batch processing"
                },
                ...
            ]
        }
    """
    try:
        nova_service = get_nova_service()
        models = []

        for model_key, config in nova_service.MODEL_CONFIG.items():
            models.append({
                'id': model_key,
                'name': config['name'],
                'model_id': config['id'],
                'context_tokens': config['context_tokens'],
                'max_video_minutes': config['max_video_minutes'],
                'price_input_per_1k': config['price_input_per_1k'],
                'price_output_per_1k': config['price_output_per_1k'],
                'best_for': config['best_for'],
                'supports_batch': config.get('supports_batch', False)
            })

        return jsonify({'models': models}), 200

    except Exception as e:
        logger.error(f"Error getting models: {str(e)}")
        return jsonify({'error': str(e)}), 500


@bp.route('/estimate-cost', methods=['POST'])
def estimate_analysis_cost():
    """
    Estimate cost for Nova video analysis.

    Expected JSON:
        {
            "model": "lite",
            "video_duration_seconds": 300,
            "analysis_types": ["summary", "chapters", "elements"]
        }

    Returns:
        {
            "model": "lite",
            "video_duration_seconds": 300,
            "estimated_input_tokens": 30000,
            "estimated_output_tokens": 2048,
            "input_cost_usd": 0.018,
            "output_cost_usd": 0.0049,
            "total_cost_usd": 0.0229,
            "analysis_count": 3
        }
    """
    try:
        data = request.get_json()
        model = data.get('model', 'lite')
        video_duration_seconds = data.get('video_duration_seconds', 300)
        analysis_types = data.get('analysis_types', ['summary'])
        processing_mode = data.get('processing_mode', 'realtime')

        nova_service = get_nova_service()

        # Estimate base cost
        base_estimate = nova_service.estimate_cost(
            model=model,
            video_duration_seconds=video_duration_seconds,
            batch_mode=(processing_mode == 'batch')
        )

        # Multiply by number of analysis types (each requires separate API call in current implementation)
        # Future optimization: combine analyses in single prompt
        analysis_count = len(analysis_types)
        total_cost = base_estimate['total_cost_usd'] * analysis_count

        return jsonify({
            'model': model,
            'video_duration_seconds': video_duration_seconds,
            'estimated_input_tokens': base_estimate['estimated_input_tokens'],
            'estimated_output_tokens': base_estimate['estimated_output_tokens'],
            'input_cost_usd': round(base_estimate['input_cost_usd'] * analysis_count, 4),
            'output_cost_usd': round(base_estimate['output_cost_usd'] * analysis_count, 4),
            'total_cost_usd': round(total_cost, 4),
            'analysis_count': analysis_count,
            'price_per_1k_input': base_estimate['price_per_1k_input'],
            'price_per_1k_output': base_estimate['price_per_1k_output'],
            'batch_discount_applied': base_estimate.get('batch_discount_applied', False)
        }), 200

    except Exception as e:
        logger.error(f"Error estimating cost: {str(e)}")
        return jsonify({'error': str(e)}), 500
