"""
AWS Nova video analysis routes.
Provides API endpoints for intelligent video comprehension using Amazon Nova models.
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.nova_service import NovaVideoService, NovaError
from app.services.nova_embeddings_service import NovaEmbeddingsService, NovaEmbeddingsError
from app.database import get_db
import json
import logging
from datetime import datetime
import traceback
import hashlib
from typing import Any, Dict, List, Optional, Tuple
import os

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


def get_nova_embeddings_service():
    """Get configured Nova embeddings service instance."""
    return NovaEmbeddingsService(
        region=current_app.config['AWS_REGION'],
        model_id=current_app.config.get('NOVA_EMBED_MODEL_ID', 'amazon.nova-embed-v1:0'),
        aws_access_key=current_app.config.get('AWS_ACCESS_KEY_ID'),
        aws_secret_key=current_app.config.get('AWS_SECRET_ACCESS_KEY'),
        request_format=current_app.config.get('NOVA_EMBED_REQUEST_FORMAT', 'input')
    )


def _ensure_json_list(value):
    """Normalize list-like values that may already be parsed."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return list(value)


def _ensure_json_dict(value):
    """Normalize dict-like values that may already be parsed."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _normalize_text(value: Any) -> str:
    """Normalize text for embedding input."""
    if value is None:
        return ''
    text = str(value)
    return ' '.join(text.split())


def _build_analysis_text(job: Dict[str, Any]) -> str:
    """Build a plain text representation of Nova analysis results."""
    parts: List[str] = []

    summary = job.get('summary_result')
    if summary:
        summary_data = summary if isinstance(summary, dict) else _ensure_json_dict(summary)
        summary_text = summary_data.get('text')
        if summary_text:
            parts.append(f"Summary: {_normalize_text(summary_text)}")

    chapters = job.get('chapters_result')
    if chapters:
        if isinstance(chapters, list):
            chapter_list = chapters
        else:
            chapters_data = chapters if isinstance(chapters, dict) else _ensure_json_dict(chapters)
            chapter_list = chapters_data.get('chapters', [])
        if isinstance(chapter_list, list) and chapter_list:
            chapter_lines = []
            for chapter in chapter_list:
                if not isinstance(chapter, dict):
                    continue
                title = _normalize_text(chapter.get('title') or chapter.get('name') or '')
                summary_text = _normalize_text(chapter.get('summary') or '')
                start_time = _normalize_text(chapter.get('start_time') or '')
                end_time = _normalize_text(chapter.get('end_time') or '')
                line = " | ".join([v for v in [title, summary_text, start_time, end_time] if v])
                if line:
                    chapter_lines.append(line)
            if chapter_lines:
                parts.append("Chapters: " + " || ".join(chapter_lines))

    elements = job.get('elements_result')
    if elements:
        elements_data = elements if isinstance(elements, dict) else _ensure_json_dict(elements)
        equipment = elements_data.get('equipment', [])
        topics = elements_data.get('topics_discussed', [])
        speakers = elements_data.get('speakers', [])

        if equipment:
            names = [_normalize_text(e.get('name')) for e in equipment if isinstance(e, dict)]
            names = [n for n in names if n]
            if names:
                parts.append("Equipment: " + ", ".join(names))
        if topics:
            names = [_normalize_text(t.get('topic')) for t in topics if isinstance(t, dict)]
            names = [n for n in names if n]
            if names:
                parts.append("Topics: " + ", ".join(names))
        if speakers:
            names = [_normalize_text(s.get('role') or s.get('speaker_id')) for s in speakers if isinstance(s, dict)]
            names = [n for n in names if n]
            if names:
                parts.append("Speakers: " + ", ".join(names))

    waterfall = job.get('waterfall_classification_result')
    if waterfall:
        waterfall_data = waterfall if isinstance(waterfall, dict) else _ensure_json_dict(waterfall)
        family = _normalize_text(waterfall_data.get('family') or '')
        tier = _normalize_text(waterfall_data.get('tier_level') or '')
        functional = _normalize_text(waterfall_data.get('functional_type') or '')
        subtype = _normalize_text(waterfall_data.get('sub_type') or '')
        evidence = waterfall_data.get('evidence') or []
        evidence_text = ''
        if isinstance(evidence, list):
            evidence_text = ", ".join([_normalize_text(e) for e in evidence if e])
        
        # Enhanced waterfall fields
        search_tags = waterfall_data.get('search_tags') or []
        product_keywords = waterfall_data.get('product_keywords') or []
        building_techniques = waterfall_data.get('building_techniques') or []
        
        details = " | ".join([v for v in [family, tier, functional, subtype] if v])
        if details:
            line = f"Waterfall Classification: {details}"
            if evidence_text:
                line += f" | Evidence: {evidence_text}"
            if search_tags:
                line += f" | Tags: {', '.join([_normalize_text(t) for t in search_tags])}"
            if product_keywords:
                line += f" | Products: {', '.join([_normalize_text(p) for p in product_keywords])}"
            if building_techniques:
                line += f" | Techniques: {', '.join([_normalize_text(t) for t in building_techniques])}"
            parts.append(line)

    search_metadata = job.get('search_metadata')
    if search_metadata:
        meta = search_metadata if isinstance(search_metadata, dict) else _ensure_json_dict(search_metadata)
        project = meta.get('project', {})
        location = meta.get('location', {})
        content = meta.get('content', {})
        
        meta_parts = []
        if project.get('customer_name') and project.get('customer_name') != 'unknown':
            meta_parts.append(f"Customer: {project['customer_name']}")
        if project.get('project_name') and project.get('project_name') != 'unknown':
            meta_parts.append(f"Project: {project['project_name']}")
        if location.get('city') and location.get('city') != 'unknown':
            loc = location['city']
            if location.get('state_region') and location.get('state_region') != 'unknown':
                loc += f", {location['state_region']}"
            meta_parts.append(f"Location: {loc}")
        if content.get('content_type') and content.get('content_type') != 'unknown':
            meta_parts.append(f"Type: {content['content_type']}")
            
        keywords = meta.get('keywords', [])
        if keywords:
            meta_parts.append(f"Keywords: {', '.join(keywords)}")
            
        if meta_parts:
            parts.append("Metadata: " + " | ".join(meta_parts))

    return "\n\n".join([p for p in parts if p])


def start_nova_analysis_internal(
    file_id: int,
    model: str = 'lite',
    analysis_types: Optional[List[str]] = None,
    options: Optional[Dict[str, Any]] = None,
    processing_mode: str = 'realtime'
) -> Tuple[Dict[str, Any], int]:
    """Run Nova analysis with explicit parameters (non-request entry point)."""
    analysis_types = analysis_types or ['summary']
    options = options or {}
    processing_mode = processing_mode or options.get('processing_mode', 'realtime')
    options['processing_mode'] = processing_mode

    # Validate inputs
    if not file_id:
        return {'error': 'file_id is required'}, 400

    if not isinstance(analysis_types, list) or not analysis_types:
        return {'error': 'analysis_types must be a non-empty array'}, 400

    valid_models = ['lite', 'pro', 'premier']
    if model not in valid_models:
        return {'error': f'model must be one of: {valid_models}'}, 400

    if processing_mode not in ('realtime', 'batch'):
        return {'error': 'processing_mode must be "realtime" or "batch"'}, 400

    valid_analysis_types = ['summary', 'chapters', 'elements', 'waterfall_classification', 'combined']
    invalid_types = [t for t in analysis_types if t not in valid_analysis_types]
    if invalid_types:
        return {
            'error': f'Invalid analysis types: {invalid_types}. Valid types: {valid_analysis_types}'
        }, 400
    if 'combined' in analysis_types:
        analysis_types = ['combined']
        options['combined'] = True

    # Get file from database
    db = get_db()
    file = db.get_file(file_id)

    if not file:
        return {'error': 'File not found'}, 404

    if file['file_type'] != 'video':
        return {'error': 'File must be a video'}, 400

    metadata = file.get('metadata', {}) or {}
    proxy_s3_key = metadata.get('proxy_s3_key')
    s3_key = proxy_s3_key or file.get('s3_key')
    if proxy_s3_key:
        options['proxy_s3_key'] = proxy_s3_key
        options['proxy_used'] = True
        options['source_s3_key'] = file.get('s3_key')

    if not s3_key or str(s3_key).startswith('local://'):
        local_path = file.get('local_path')
        if not local_path or not os.path.isfile(local_path):
            return {'error': 'File must be available locally to upload to S3 for Nova analysis.'}, 400

        from app.services.s3_service import S3Service

        filename = os.path.basename(local_path)
        prefix = 'proxies' if file.get('is_proxy') else 'uploads'
        s3_key = f'{prefix}/{filename}'

        s3_service = S3Service(
            bucket_name=current_app.config['S3_BUCKET_NAME'],
            region=current_app.config['AWS_REGION']
        )
        content_type = file.get('content_type') or 'video/mp4'
        with open(local_path, 'rb') as file_obj:
            s3_service.upload_file(file_obj, s3_key, content_type)

        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE files SET s3_key = ? WHERE id = ?', (s3_key, file_id))

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

            return {
                'nova_job_id': nova_job_id,
                'analysis_job_id': analysis_job_id,
                'status': 'IN_PROGRESS',
                'model': model,
                'analysis_types': analysis_types,
                'processing_mode': 'batch',
                'batch_job_arn': batch_response['batch_job_arn'],
                'estimated_cost': cost_estimate
            }, 202

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

        # Build analysis context
        file_with_context = db.get_file_with_transcript_summary(file_id) or {}
        file_tokens = NovaVideoService.normalize_file_context(
            file.get('filename'),
            file.get('local_path')
        )
        analysis_context = {
            **file_tokens,
            'filename': file.get('filename'),
            'file_path': file.get('local_path'),
            'transcript_summary': file_with_context.get('transcript_summary'),
            'duration_seconds': file.get('duration_seconds') or file.get('metadata', {}).get('duration_seconds')
        }

        # Run analysis
        logger.info(f"Starting Nova analysis for job {nova_job_id}, S3 key: {s3_key}")
        results = nova_service.analyze_video(
            s3_key=s3_key,
            model=model,
            analysis_types=analysis_types,
            options=options,
            context=analysis_context,
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

        if 'waterfall_classification' in results:
            update_data['waterfall_classification_result'] = json.dumps(results['waterfall_classification'])

        if 'search_metadata' in results:
            update_data['search_metadata'] = json.dumps(results['search_metadata'])

        # Store raw API responses for debugging/auditing
        if 'raw_responses' in results:
            update_data['raw_response'] = json.dumps(results['raw_responses'])

        # Update database
        db.update_nova_job(nova_job_id, update_data)
        db.update_nova_job_completed_at(nova_job_id)

        # Update analysis job status
        db.update_analysis_job(
            analysis_job_id,
            status='COMPLETED',
            results=results
        )

        logger.info(f"Nova analysis completed for job {nova_job_id}. Cost: ${results['totals']['cost_total_usd']:.4f}")

        return {
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
        }, 200

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

        return {
            'nova_job_id': nova_job_id,
            'analysis_job_id': analysis_job_id,
            'status': 'FAILED',
            'error': error_msg
        }, 500

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

        return {
            'nova_job_id': nova_job_id,
            'analysis_job_id': analysis_job_id,
            'status': 'FAILED',
            'error': error_msg
        }, 500

@bp.route('/analyze', methods=['POST'])
def start_nova_analysis():
    """
    Start Nova video analysis.

    Expected JSON:
        {
            "file_id": 123,
            "model": "lite",  # 'lite', 'pro', 'premier'
            "analysis_types": ["summary", "chapters", "elements", "waterfall_classification"],
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
        data = request.get_json() or {}
        payload, status_code = start_nova_analysis_internal(
            file_id=data.get('file_id'),
            model=data.get('model', 'lite'),
            analysis_types=data.get('analysis_types', ['summary']),
            options=data.get('options', {}),
            processing_mode=data.get('processing_mode', data.get('options', {}).get('processing_mode', 'realtime'))
        )
        return jsonify(payload), status_code
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
            'analysis_types': _ensure_json_list(job.get('analysis_types')),
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
                options = _ensure_json_dict(job.get('user_options'))
                results = nova_service.fetch_batch_results(
                    s3_prefix=job.get('batch_output_s3_prefix', ''),
                    model=job['model'],
                    analysis_types=_ensure_json_list(job.get('analysis_types')),
                    options=options,
                    record_prefix=options.get('batch_record_prefix')
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

                if 'waterfall_classification' in results:
                    update_data['waterfall_classification_result'] = json.dumps(results['waterfall_classification'])

                # Store raw API responses for debugging/auditing
                if 'raw_responses' in results:
                    update_data['raw_response'] = json.dumps(results['raw_responses'])

                db.update_nova_job(nova_job_id, update_data)
                db.update_nova_job_completed_at(nova_job_id)

                db.update_analysis_job(
                    job['analysis_job_id'],
                    status='COMPLETED',
                    results=results
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
            results['summary'] = _ensure_json_dict(job['summary_result'])

        if job['chapters_result']:
            results['chapters'] = _ensure_json_dict(job['chapters_result'])

        if job['elements_result']:
            results['elements'] = _ensure_json_dict(job['elements_result'])
        if job.get('waterfall_classification_result'):
            results['waterfall_classification'] = _ensure_json_dict(job['waterfall_classification_result'])

        response = {
            'nova_job_id': job['id'],
            'analysis_job_id': job['analysis_job_id'],
            'status': job['status'],
            'model': job['model'],
            'analysis_types': _ensure_json_list(job.get('analysis_types')),
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
                    "id": "lite",
                    "name": "Nova 2 Lite",
                    "context_tokens": 300000,
                    "max_video_minutes": 30,
                    "price_input_per_1k": 0.33,
                    "price_output_per_1k": 2.75,
                    "best_for": "General video understanding (recommended)"
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
        analysis_count = 1 if 'combined' in analysis_types else len(analysis_types)
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


@bp.route('/embeddings/generate', methods=['POST'])
def generate_embeddings():
    """
    Generate Nova embeddings for analysis results and/or a transcript.

    Expected JSON:
        {
            "nova_job_id": 123,          # required if embed_analysis is true
            "transcript_id": 456,        # required if embed_transcript is true
            "embed_analysis": true,
            "embed_transcript": true
        }
    """
    try:
        data = request.get_json() or {}
        nova_job_id = data.get('nova_job_id')
        transcript_id = data.get('transcript_id')
        embed_analysis = bool(data.get('embed_analysis', True))
        embed_transcript = bool(data.get('embed_transcript', True))

        if not embed_analysis and not embed_transcript:
            return jsonify({'error': 'At least one of embed_analysis or embed_transcript must be true.'}), 400

        db = get_db()
        analysis_text = None
        transcript_text = None
        file_id = None

        if embed_analysis:
            if not nova_job_id:
                return jsonify({'error': 'nova_job_id is required when embed_analysis is true.'}), 400
            job = db.get_nova_job(nova_job_id)
            if not job:
                return jsonify({'error': 'Nova job not found.'}), 404
            if job.get('status') != 'COMPLETED':
                return jsonify({'error': 'Nova job must be COMPLETED before embedding.'}), 400
            analysis_text = _build_analysis_text(job)
            if not analysis_text:
                return jsonify({'error': 'Nova job has no analysis text to embed.'}), 400

            analysis_job = db.get_analysis_job(job['analysis_job_id'])
            if analysis_job:
                file_id = analysis_job.get('file_id')

        if embed_transcript:
            if not transcript_id:
                return jsonify({'error': 'transcript_id is required when embed_transcript is true.'}), 400
            transcript = db.get_transcript(transcript_id)
            if not transcript:
                return jsonify({'error': 'Transcript not found.'}), 404
            if transcript.get('status') != 'COMPLETED':
                return jsonify({'error': 'Transcript must be COMPLETED before embedding.'}), 400
            transcript_text = _normalize_text(transcript.get('transcript_text'))
            if not transcript_text:
                return jsonify({'error': 'Transcript text is empty.'}), 400

            if file_id is None:
                file_path = transcript.get('file_path')
                if file_path:
                    file_record = db.get_file_by_local_path(file_path)
                    if file_record:
                        file_id = file_record.get('id')

        embeddings_service = get_nova_embeddings_service()
        model_name = embeddings_service.model_id
        results: Dict[str, Any] = {
            'model': model_name,
            'embeddings': {}
        }

        if embed_analysis and analysis_text:
            analysis_hash = hashlib.sha256(
                f"nova_analysis:{nova_job_id}:{model_name}:{analysis_text}".encode('utf-8')
            ).hexdigest()
            vector = embeddings_service.embed_text(analysis_text)
            embedding_id = db.create_nova_embedding(
                embedding_vector=vector,
                source_type='nova_analysis',
                source_id=nova_job_id,
                model_name=model_name,
                content_hash=analysis_hash,
                file_id=file_id
            )
            results['embeddings']['analysis_embedding_id'] = embedding_id

        if embed_transcript and transcript_text:
            transcript_hash = hashlib.sha256(
                f"transcript:{transcript_id}:{model_name}:{transcript_text}".encode('utf-8')
            ).hexdigest()
            vector = embeddings_service.embed_text(transcript_text)
            embedding_id = db.create_nova_embedding(
                embedding_vector=vector,
                source_type='transcript',
                source_id=transcript_id,
                model_name=model_name,
                content_hash=transcript_hash,
                file_id=file_id
            )
            results['embeddings']['transcript_embedding_id'] = embedding_id

        return jsonify(results), 201

    except NovaEmbeddingsError as e:
        logger.error(f"Embedding error: {e}")
        return jsonify({'error': str(e)}), 500
    except RuntimeError as e:
        logger.error(f"Embedding storage error: {e}")
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        logger.error(f"Error generating embeddings: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
