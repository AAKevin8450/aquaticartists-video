"""
Video analysis routes for Amazon Rekognition video operations.
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.rekognition_video import get_rekognition_video_service, RekognitionError
from app.database import get_db
from app.models import AnalysisType
from app.utils.validators import validate_confidence, ValidationError
import uuid

bp = Blueprint('video_analysis', __name__, url_prefix='/api/video')


def _start_analysis(file_id, analysis_type, start_func, **kwargs):
    """
    Helper function to start video analysis jobs.

    Args:
        file_id: Database file ID
        analysis_type: Analysis type string
        start_func: Function to start the analysis
        **kwargs: Additional parameters for start function

    Returns:
        tuple: (response_dict, status_code)
    """
    try:
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return {'error': 'File not found'}, 404

        if file['file_type'] != 'video':
            return {'error': 'File is not a video'}, 400

        # Start Rekognition job
        rekognition = get_rekognition_video_service(current_app)
        job_id = start_func(file['s3_key'], **kwargs)

        # Create job record in database
        job_db_id = db.create_job(
            job_id=job_id,
            file_id=file_id,
            analysis_type=analysis_type,
            parameters=kwargs
        )

        return {
            'job_id': job_id,
            'job_db_id': job_db_id,
            'status': 'SUBMITTED',
            'message': f'{analysis_type} job started successfully'
        }, 201

    except RekognitionError as e:
        return {'error': str(e)}, 400
    except Exception as e:
        current_app.logger.error(f"Start analysis error: {e}")
        return {'error': 'Failed to start analysis'}, 500


@bp.route('/labels/start', methods=['POST'])
def start_label_detection():
    """
    Start label detection for video.

    Expected JSON:
        {
            "file_id": 123,
            "min_confidence": 50.0,
            "max_labels": 1000
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    min_confidence = data.get('min_confidence', 50.0)
    max_labels = data.get('max_labels', 1000)

    rekognition = get_rekognition_video_service(current_app)
    response, status = _start_analysis(
        file_id,
        AnalysisType.VIDEO_LABELS,
        rekognition.start_label_detection,
        min_confidence=min_confidence,
        max_labels=max_labels
    )
    return jsonify(response), status


@bp.route('/faces/start', methods=['POST'])
def start_face_detection():
    """
    Start face detection for video.

    Expected JSON:
        {
            "file_id": 123,
            "attributes": "ALL"  # or "DEFAULT"
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    attributes = data.get('attributes', 'ALL')

    rekognition = get_rekognition_video_service(current_app)
    response, status = _start_analysis(
        file_id,
        AnalysisType.VIDEO_FACES,
        rekognition.start_face_detection,
        attributes=attributes
    )
    return jsonify(response), status


@bp.route('/celebrities/start', methods=['POST'])
def start_celebrity_recognition():
    """
    Start celebrity recognition for video.

    Expected JSON:
        {
            "file_id": 123
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')

    rekognition = get_rekognition_video_service(current_app)
    response, status = _start_analysis(
        file_id,
        AnalysisType.VIDEO_CELEBRITIES,
        rekognition.start_celebrity_recognition
    )
    return jsonify(response), status


@bp.route('/moderation/start', methods=['POST'])
def start_content_moderation():
    """
    Start content moderation for video.

    Expected JSON:
        {
            "file_id": 123,
            "min_confidence": 50.0
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    min_confidence = data.get('min_confidence', 50.0)

    rekognition = get_rekognition_video_service(current_app)
    response, status = _start_analysis(
        file_id,
        AnalysisType.VIDEO_MODERATION,
        rekognition.start_content_moderation,
        min_confidence=min_confidence
    )
    return jsonify(response), status


@bp.route('/text/start', methods=['POST'])
def start_text_detection():
    """
    Start text detection for video.

    Expected JSON:
        {
            "file_id": 123,
            "min_confidence": 50.0
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    min_confidence = data.get('min_confidence', 50.0)

    rekognition = get_rekognition_video_service(current_app)
    response, status = _start_analysis(
        file_id,
        AnalysisType.VIDEO_TEXT,
        rekognition.start_text_detection,
        min_confidence=min_confidence
    )
    return jsonify(response), status


@bp.route('/segments/start', methods=['POST'])
def start_segment_detection():
    """
    Start segment detection for video.

    Expected JSON:
        {
            "file_id": 123,
            "segment_types": ["TECHNICAL_CUE", "SHOT"]
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    segment_types = data.get('segment_types', ['TECHNICAL_CUE', 'SHOT'])

    rekognition = get_rekognition_video_service(current_app)
    response, status = _start_analysis(
        file_id,
        AnalysisType.VIDEO_SEGMENTS,
        rekognition.start_segment_detection,
        segment_types=segment_types
    )
    return jsonify(response), status


@bp.route('/persons/start', methods=['POST'])
def start_person_tracking():
    """
    Start person tracking for video.

    Expected JSON:
        {
            "file_id": 123
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')

    rekognition = get_rekognition_video_service(current_app)
    response, status = _start_analysis(
        file_id,
        AnalysisType.VIDEO_PERSONS,
        rekognition.start_person_tracking
    )
    return jsonify(response), status


@bp.route('/face-search/start', methods=['POST'])
def start_face_search():
    """
    Start face search for video against a face collection.

    Expected JSON:
        {
            "file_id": 123,
            "collection_id": "my-collection",
            "face_match_threshold": 80.0
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    collection_id = data.get('collection_id')
    face_match_threshold = data.get('face_match_threshold', 80.0)

    if not collection_id:
        return jsonify({'error': 'collection_id is required'}), 400

    rekognition = get_rekognition_video_service(current_app)
    response, status = _start_analysis(
        file_id,
        AnalysisType.VIDEO_FACE_SEARCH,
        rekognition.start_face_search,
        collection_id=collection_id,
        face_match_threshold=face_match_threshold
    )
    return jsonify(response), status


@bp.route('/job/<job_id>/status', methods=['GET'])
def get_job_status(job_id):
    """
    Get status of a video analysis job.

    Returns:
        {
            "status": "IN_PROGRESS" | "SUCCEEDED" | "FAILED",
            "results": {...},  # if SUCCEEDED
            "error": "..."     # if FAILED
        }
    """
    try:
        db = get_db()
        job = db.get_job(job_id)

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        # If job already completed, return cached results
        if job['status'] in ('SUCCEEDED', 'FAILED'):
            response = {
                'status': job['status'],
                'results': job.get('results'),
                'error': job.get('error_message')
            }
            return jsonify(response), 200

        # Check job status from AWS
        rekognition = get_rekognition_video_service(current_app)

        # Map analysis type to Rekognition job type
        job_type_map = {
            AnalysisType.VIDEO_LABELS: 'LabelDetection',
            AnalysisType.VIDEO_FACES: 'FaceDetection',
            AnalysisType.VIDEO_CELEBRITIES: 'CelebrityRecognition',
            AnalysisType.VIDEO_MODERATION: 'ContentModeration',
            AnalysisType.VIDEO_TEXT: 'TextDetection',
            AnalysisType.VIDEO_SEGMENTS: 'SegmentDetection',
            AnalysisType.VIDEO_PERSONS: 'PersonTracking',
            AnalysisType.VIDEO_FACE_SEARCH: 'FaceSearch',
        }

        job_type = job_type_map.get(job['analysis_type'], 'LabelDetection')
        status_response = rekognition.get_job_status(job_id, job_type)

        # Update database if job completed
        if status_response['status'] in ('SUCCEEDED', 'FAILED'):
            db.update_job_status(
                job_id,
                status_response['status'],
                results=status_response.get('results'),
                error_message=status_response.get('error')
            )

        return jsonify(status_response), 200

    except RekognitionError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Get job status error: {e}")
        return jsonify({'error': 'Failed to get job status'}), 500


@bp.route('/<analysis_type>/<job_id>', methods=['GET'])
def get_analysis_results(analysis_type, job_id):
    """
    Get results for a specific analysis type and job.

    Returns cached results from database if available.
    """
    try:
        db = get_db()
        job = db.get_job(job_id)

        if not job:
            return jsonify({'error': 'Job not found'}), 404

        if job['status'] != 'SUCCEEDED':
            return jsonify({
                'error': f"Job not complete. Current status: {job['status']}"
            }), 400

        return jsonify({
            'job_id': job_id,
            'analysis_type': job['analysis_type'],
            'status': job['status'],
            'results': job['results'],
            'started_at': job['started_at'],
            'completed_at': job['completed_at']
        }), 200

    except Exception as e:
        current_app.logger.error(f"Get results error: {e}")
        return jsonify({'error': 'Failed to get results'}), 500
