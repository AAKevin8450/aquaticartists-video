"""
Image analysis routes for Amazon Rekognition image operations.
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.rekognition_image import get_rekognition_image_service, RekognitionImageError
from app.database import get_db
from app.models import AnalysisType
import uuid

bp = Blueprint('image_analysis', __name__, url_prefix='/api/image')


def _analyze_image(file_id, analysis_type, analysis_func, **kwargs):
    """
    Helper function to perform image analysis.

    Args:
        file_id: Database file ID
        analysis_type: Analysis type string
        analysis_func: Function to perform the analysis
        **kwargs: Additional parameters for analysis function

    Returns:
        tuple: (response_dict, status_code)
    """
    try:
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return {'error': 'File not found'}, 404

        if file['file_type'] != 'image':
            return {'error': 'File is not an image'}, 400

        # Perform analysis
        rekognition = get_rekognition_image_service(current_app)
        results = analysis_func(file['s3_key'], **kwargs)

        # Create job record with immediate results
        job_id = str(uuid.uuid4())
        job_db_id = db.create_job(
            job_id=job_id,
            file_id=file_id,
            analysis_type=analysis_type,
            parameters=kwargs
        )

        # Update with results immediately (synchronous)
        db.update_job_status(job_id, 'COMPLETED', results=results)

        return {
            'job_id': job_id,
            'job_db_id': job_db_id,
            'status': 'COMPLETED',
            'results': results
        }, 200

    except RekognitionImageError as e:
        return {'error': str(e)}, 400
    except Exception as e:
        current_app.logger.error(f"Image analysis error: {e}")
        return {'error': 'Failed to analyze image'}, 500


@bp.route('/labels', methods=['POST'])
def detect_labels():
    """
    Detect labels in image.

    Expected JSON:
        {
            "file_id": 123,
            "max_labels": 100,
            "min_confidence": 50.0,
            "features": ["GENERAL_LABELS", "IMAGE_PROPERTIES"]
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    max_labels = data.get('max_labels', 100)
    min_confidence = data.get('min_confidence', 50.0)
    features = data.get('features')

    rekognition = get_rekognition_image_service(current_app)
    response, status = _analyze_image(
        file_id,
        AnalysisType.IMAGE_LABELS,
        rekognition.detect_labels,
        max_labels=max_labels,
        min_confidence=min_confidence,
        features=features
    )
    return jsonify(response), status


@bp.route('/faces', methods=['POST'])
def detect_faces():
    """
    Detect faces in image.

    Expected JSON:
        {
            "file_id": 123,
            "attributes": ["ALL"]
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    attributes = data.get('attributes', ['ALL'])

    rekognition = get_rekognition_image_service(current_app)
    response, status = _analyze_image(
        file_id,
        AnalysisType.IMAGE_FACES,
        rekognition.detect_faces,
        attributes=attributes
    )
    return jsonify(response), status


@bp.route('/face-compare', methods=['POST'])
def compare_faces():
    """
    Compare faces between two images.

    Expected JSON:
        {
            "source_file_id": 123,
            "target_file_id": 456,
            "similarity_threshold": 80.0,
            "quality_filter": "AUTO"
        }
    """
    try:
        data = request.get_json()
        source_file_id = data.get('source_file_id')
        target_file_id = data.get('target_file_id')
        similarity_threshold = data.get('similarity_threshold', 80.0)
        quality_filter = data.get('quality_filter', 'AUTO')

        if not source_file_id or not target_file_id:
            return jsonify({'error': 'source_file_id and target_file_id are required'}), 400

        db = get_db()
        source_file = db.get_file(source_file_id)
        target_file = db.get_file(target_file_id)

        if not source_file or not target_file:
            return jsonify({'error': 'One or both files not found'}), 404

        if source_file['file_type'] != 'image' or target_file['file_type'] != 'image':
            return jsonify({'error': 'Both files must be images'}), 400

        # Perform comparison
        rekognition = get_rekognition_image_service(current_app)
        results = rekognition.compare_faces(
            source_file['s3_key'],
            target_file['s3_key'],
            similarity_threshold,
            quality_filter
        )

        # Create job record
        job_id = str(uuid.uuid4())
        job_db_id = db.create_job(
            job_id=job_id,
            file_id=source_file_id,
            analysis_type=AnalysisType.IMAGE_FACE_COMPARE,
            parameters={
                'target_file_id': target_file_id,
                'similarity_threshold': similarity_threshold,
                'quality_filter': quality_filter
            }
        )

        db.update_job_status(job_id, 'COMPLETED', results=results)

        return jsonify({
            'job_id': job_id,
            'job_db_id': job_db_id,
            'status': 'COMPLETED',
            'results': results
        }), 200

    except RekognitionImageError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Face comparison error: {e}")
        return jsonify({'error': 'Failed to compare faces'}), 500


@bp.route('/celebrities', methods=['POST'])
def recognize_celebrities():
    """
    Recognize celebrities in image.

    Expected JSON:
        {
            "file_id": 123
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')

    rekognition = get_rekognition_image_service(current_app)
    response, status = _analyze_image(
        file_id,
        AnalysisType.IMAGE_CELEBRITIES,
        rekognition.recognize_celebrities
    )
    return jsonify(response), status


@bp.route('/moderation', methods=['POST'])
def detect_moderation_labels():
    """
    Detect moderation labels in image.

    Expected JSON:
        {
            "file_id": 123,
            "min_confidence": 50.0
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    min_confidence = data.get('min_confidence', 50.0)

    rekognition = get_rekognition_image_service(current_app)
    response, status = _analyze_image(
        file_id,
        AnalysisType.IMAGE_MODERATION,
        rekognition.detect_moderation_labels,
        min_confidence=min_confidence
    )
    return jsonify(response), status


@bp.route('/text', methods=['POST'])
def detect_text():
    """
    Detect text in image.

    Expected JSON:
        {
            "file_id": 123,
            "word_filter": {...},
            "region_filter": {...}
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    word_filter = data.get('word_filter')
    region_filter = data.get('region_filter')

    rekognition = get_rekognition_image_service(current_app)
    response, status = _analyze_image(
        file_id,
        AnalysisType.IMAGE_TEXT,
        rekognition.detect_text,
        word_filter=word_filter,
        region_filter=region_filter
    )
    return jsonify(response), status


@bp.route('/ppe', methods=['POST'])
def detect_protective_equipment():
    """
    Detect protective equipment in image.

    Expected JSON:
        {
            "file_id": 123,
            "summarization_attributes": {...}
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    summarization_attributes = data.get('summarization_attributes')

    rekognition = get_rekognition_image_service(current_app)
    response, status = _analyze_image(
        file_id,
        AnalysisType.IMAGE_PPE,
        rekognition.detect_protective_equipment,
        summarization_attributes=summarization_attributes
    )
    return jsonify(response), status


@bp.route('/custom-labels', methods=['POST'])
def detect_custom_labels():
    """
    Detect custom labels in image.

    Expected JSON:
        {
            "file_id": 123,
            "project_version_arn": "arn:aws:...",
            "min_confidence": 50.0,
            "max_results": 100
        }
    """
    data = request.get_json()
    file_id = data.get('file_id')
    project_version_arn = data.get('project_version_arn')
    min_confidence = data.get('min_confidence', 50.0)
    max_results = data.get('max_results', 100)

    if not project_version_arn:
        return jsonify({'error': 'project_version_arn is required'}), 400

    rekognition = get_rekognition_image_service(current_app)
    response, status = _analyze_image(
        file_id,
        AnalysisType.IMAGE_CUSTOM_LABELS,
        rekognition.detect_custom_labels,
        project_version_arn=project_version_arn,
        min_confidence=min_confidence,
        max_results=max_results
    )
    return jsonify(response), status
