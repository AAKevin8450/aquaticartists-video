"""
AWS Nova image analysis routes.
Provides API endpoints for intelligent image comprehension using Amazon Nova models.
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.nova_image_service import NovaImageService, NovaError
from app.database import get_db
import json
import logging
import traceback
import os
import tempfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

bp = Blueprint('nova_image_analysis', __name__, url_prefix='/api/nova/image')


def get_nova_image_service():
    """Get configured Nova image service instance."""
    return NovaImageService(
        bucket_name=current_app.config['S3_BUCKET_NAME'],
        region=current_app.config['AWS_REGION'],
        aws_access_key=current_app.config.get('AWS_ACCESS_KEY_ID'),
        aws_secret_key=current_app.config.get('AWS_SECRET_ACCESS_KEY')
    )


@bp.route('/analyze', methods=['POST'])
def start_image_analysis():
    """
    Start Nova image analysis.

    Request:
    {
        "file_id": 123,
        "model": "lite",  # lite, pro, premier
        "analysis_types": ["description", "elements", "waterfall", "metadata"]
    }

    Response:
    {
        "nova_job_id": 456,
        "analysis_job_id": 789,
        "status": "SUBMITTED",
        "estimated_cost": 0.001
    }
    """
    try:
        data = request.get_json()
        file_id = data.get('file_id')
        model = data.get('model', 'lite')
        analysis_types = data.get('analysis_types', ['description', 'elements', 'metadata'])

        if not file_id:
            return jsonify({'error': 'file_id is required'}), 400

        if not analysis_types:
            return jsonify({'error': 'At least one analysis type must be specified'}), 400

        # Validate model
        valid_models = ['lite', 'pro', 'premier']
        if model not in valid_models:
            return jsonify({'error': f'Invalid model. Choose from: {valid_models}'}), 400

        # Validate analysis types
        valid_types = ['description', 'elements', 'waterfall', 'metadata']
        for atype in analysis_types:
            if atype not in valid_types:
                return jsonify({'error': f'Invalid analysis type: {atype}. Choose from: {valid_types}'}), 400

        # Get file record
        db = get_db()
        file_record = db.get_file_by_id(file_id)
        if not file_record:
            return jsonify({'error': f'File not found: {file_id}'}), 404

        # Ensure file is an image
        file_type = file_record.get('file_type', '')
        if file_type != 'image':
            return jsonify({'error': f'File must be an image, got: {file_type}'}), 400

        # Check if proxy exists (we always analyze proxies)
        proxy_files = db.get_proxy_files(file_id)
        if not proxy_files:
            return jsonify({'error': 'No proxy image found. Create image proxy first.'}), 400

        proxy_file = proxy_files[0]  # Should only be one image proxy
        proxy_file_id = proxy_file['id']

        # Create analysis job
        analysis_job_id = db.create_analysis_job(
            file_id=file_id,
            analysis_type='nova_image'
        )

        # Create Nova job
        nova_job_id = db.create_nova_job(
            analysis_job_id=analysis_job_id,
            model=model,
            analysis_types=analysis_types,
            user_options={'proxy_file_id': proxy_file_id},
            content_type='image'
        )

        # Update status to IN_PROGRESS
        db.update_nova_job_status(nova_job_id, 'IN_PROGRESS', 0)
        db.update_nova_job_started_at(nova_job_id)

        # Get Nova image service
        service = get_nova_image_service()

        # Estimate cost
        cost_estimate = service.estimate_image_cost(model, analysis_types)

        # Download proxy image to temp file
        from app.services.s3_service import S3Service
        s3_service = S3Service(
            bucket_name=current_app.config['S3_BUCKET_NAME'],
            region=current_app.config['AWS_REGION']
        )

        # Create temp file for image
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
        temp_path = temp_file.name
        temp_file.close()

        try:
            # Download proxy image
            s3_service.download_file(proxy_file['s3_key'], temp_path)

            # Build file context
            file_context = service.build_file_context(file_record, temp_path)

            # Perform analysis
            result = service.analyze_image(
                image_path=temp_path,
                analysis_types=analysis_types,
                model=model,
                file_context=file_context
            )

            # Store results in database
            update_data = {
                'status': 'COMPLETED',
                'progress_percent': 100,
                'tokens_input': result['tokens_input'],
                'tokens_output': result['tokens_output'],
                'tokens_total': result['tokens_total'],
                'cost_usd': result['cost_usd'],
                'processing_time_seconds': result['processing_time_seconds'],
                'raw_response': json.dumps(result['raw_response'])
            }

            # Store individual result types
            results = result['results']
            if 'description' in results:
                update_data['description_result'] = results['description']
            if 'elements' in results:
                update_data['elements_result'] = results['elements']
            if 'waterfall_classification' in results:
                update_data['waterfall_classification_result'] = results['waterfall_classification']
            if 'metadata' in results:
                update_data['search_metadata'] = results['metadata']

            db.update_nova_job(nova_job_id, update_data)
            db.update_nova_job_completed_at(nova_job_id)
            db.update_analysis_job(analysis_job_id, status='COMPLETED')

            logger.info(f"Image analysis completed: job={nova_job_id}, cost=${result['cost_usd']:.6f}")

            return jsonify({
                'nova_job_id': nova_job_id,
                'analysis_job_id': analysis_job_id,
                'status': 'COMPLETED',
                'estimated_cost': cost_estimate['estimated_cost_usd'],
                'actual_cost': result['cost_usd'],
                'processing_time_seconds': result['processing_time_seconds']
            }), 200

        except Exception as analysis_error:
            # Update job with error
            db.update_nova_job(nova_job_id, {
                'status': 'FAILED',
                'error_message': str(analysis_error),
                'progress_percent': 0
            })
            db.update_analysis_job(analysis_job_id, status='FAILED')
            logger.error(f"Image analysis failed: {analysis_error}\n{traceback.format_exc()}")
            raise

        finally:
            # Cleanup temp file
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    except NovaError as e:
        logger.error(f"Nova error in image analysis: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error starting image analysis: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f'Internal error: {str(e)}'}), 500


@bp.route('/status/<int:job_id>', methods=['GET'])
def get_image_analysis_status(job_id: int):
    """
    Get status of image analysis job.

    Response:
    {
        "nova_job_id": 456,
        "status": "COMPLETED|IN_PROGRESS|FAILED|SUBMITTED",
        "progress_percent": 100,
        "error_message": null
    }
    """
    try:
        db = get_db()
        nova_job = db.get_nova_job(job_id)

        if not nova_job:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify({
            'nova_job_id': nova_job['id'],
            'status': nova_job['status'],
            'progress_percent': nova_job.get('progress_percent', 0),
            'error_message': nova_job.get('error_message'),
            'processing_time_seconds': nova_job.get('processing_time_seconds'),
            'cost_usd': nova_job.get('cost_usd')
        }), 200

    except Exception as e:
        logger.error(f"Error getting image analysis status: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f'Internal error: {str(e)}'}), 500


@bp.route('/results/<int:job_id>', methods=['GET'])
def get_image_analysis_results(job_id: int):
    """
    Get results of completed image analysis.

    Response:
    {
        "nova_job_id": 456,
        "status": "COMPLETED",
        "results": {
            "description": {...},
            "elements": {...},
            "waterfall_classification": {...},
            "metadata": {...}
        },
        "tokens_input": 1500,
        "tokens_output": 1000,
        "tokens_total": 2500,
        "cost_usd": 0.00006,
        "processing_time_seconds": 5.2
    }
    """
    try:
        db = get_db()
        nova_job = db.get_nova_job(job_id)

        if not nova_job:
            return jsonify({'error': 'Job not found'}), 404

        # Build results object
        results = {}
        if nova_job.get('description_result'):
            results['description'] = nova_job['description_result']
        if nova_job.get('elements_result'):
            results['elements'] = nova_job['elements_result']
        if nova_job.get('waterfall_classification_result'):
            results['waterfall_classification'] = nova_job['waterfall_classification_result']

        # Extract metadata from search_metadata if present
        if nova_job.get('search_metadata'):
            search_metadata = nova_job['search_metadata']
            if isinstance(search_metadata, str):
                search_metadata = json.loads(search_metadata)
            results['metadata'] = search_metadata

        return jsonify({
            'nova_job_id': nova_job['id'],
            'status': nova_job['status'],
            'results': results,
            'tokens_input': nova_job.get('tokens_input'),
            'tokens_output': nova_job.get('tokens_output'),
            'tokens_total': nova_job.get('tokens_total'),
            'cost_usd': nova_job.get('cost_usd'),
            'processing_time_seconds': nova_job.get('processing_time_seconds'),
            'error_message': nova_job.get('error_message')
        }), 200

    except Exception as e:
        logger.error(f"Error getting image analysis results: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f'Internal error: {str(e)}'}), 500


@bp.route('/models', methods=['GET'])
def get_image_models():
    """
    Get available models and pricing for image analysis.

    Response:
    {
        "lite": {
            "id": "amazon.nova-2-lite-v1:0",
            "name": "Nova 2 Lite",
            "price_input_per_1k": 0.00033,
            "price_output_per_1k": 0.00275,
            "best_for": "General image understanding (recommended)"
        },
        ...
    }
    """
    try:
        service = get_nova_image_service()
        models = service.get_models()

        return jsonify(models), 200

    except Exception as e:
        logger.error(f"Error getting models: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f'Internal error: {str(e)}'}), 500


@bp.route('/estimate-cost', methods=['POST'])
def estimate_image_cost():
    """
    Estimate cost for image analysis.

    Request:
    {
        "model": "lite",
        "analysis_types": ["description", "elements", "metadata"]
    }

    Response:
    {
        "estimated_input_tokens": 1500,
        "estimated_output_tokens": 1000,
        "estimated_cost_usd": 0.00006,
        "model": "Nova 2 Lite"
    }
    """
    try:
        data = request.get_json()
        model = data.get('model', 'lite')
        analysis_types = data.get('analysis_types', ['description', 'elements', 'metadata'])

        service = get_nova_image_service()
        estimate = service.estimate_image_cost(model, analysis_types)

        return jsonify(estimate), 200

    except NovaError as e:
        logger.error(f"Nova error estimating cost: {e}")
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f"Error estimating cost: {e}\n{traceback.format_exc()}")
        return jsonify({'error': f'Internal error: {str(e)}'}), 500
