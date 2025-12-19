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

        # Validate inputs
        if not file_id:
            return jsonify({'error': 'file_id is required'}), 400

        if not isinstance(analysis_types, list) or not analysis_types:
            return jsonify({'error': 'analysis_types must be a non-empty array'}), 400

        valid_models = ['micro', 'lite', 'pro', 'premier']
        if model not in valid_models:
            return jsonify({'error': f'model must be one of: {valid_models}'}), 400

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

        # Create analysis job record
        analysis_job_id = db.create_analysis_job(
            file_id=file_id,
            job_id=f"nova-{datetime.utcnow().timestamp()}",
            analysis_type='nova',
            status='SUBMITTED',
            parameters=json.dumps({
                'model': model,
                'analysis_types': analysis_types,
                'options': options
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
        nova_service = get_nova_service()

        # Estimate cost
        # TODO: Get actual video duration from metadata
        estimated_duration = file.get('metadata', {}).get('duration_seconds', 300)  # Default 5 min
        cost_estimate = nova_service.estimate_cost(
            model=model,
            video_duration_seconds=estimated_duration
        )

        try:
            # Update status to IN_PROGRESS
            db.update_nova_job_status(nova_job_id, 'IN_PROGRESS', 0)
            db.update_nova_job_started_at(nova_job_id)

            # Run analysis
            logger.info(f"Starting Nova analysis for job {nova_job_id}, S3 key: {s3_key}")
            results = nova_service.analyze_video(
                s3_key=s3_key,
                model=model,
                analysis_types=analysis_types,
                options=options
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
                'completed_at': job['completed_at']
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
                'best_for': config['best_for']
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

        nova_service = get_nova_service()

        # Estimate base cost
        base_estimate = nova_service.estimate_cost(
            model=model,
            video_duration_seconds=video_duration_seconds
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
            'price_per_1k_output': base_estimate['price_per_1k_output']
        }), 200

    except Exception as e:
        logger.error(f"Error estimating cost: {str(e)}")
        return jsonify({'error': str(e)}), 500
