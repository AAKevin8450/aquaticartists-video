"""
Unified analysis routes for video and image analysis with multi-type support.
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.rekognition_video import get_rekognition_video_service, RekognitionError
from app.services.rekognition_image import get_rekognition_image_service, RekognitionImageError
from app.services.face_collection_service import get_face_collection_service, FaceCollectionError
from app.database import get_db
from app.models import AnalysisType
import uuid

bp = Blueprint('analysis', __name__, url_prefix='/api/analysis')


# Video analysis type mapping
VIDEO_ANALYSIS_MAP = {
    'label_detection': {
        'analysis_type': AnalysisType.VIDEO_LABELS,
        'method': 'start_label_detection',
        'params': {}
    },
    'face_detection': {
        'analysis_type': AnalysisType.VIDEO_FACES,
        'method': 'start_face_detection',
        'params': {'attributes': 'ALL'}
    },
    'celebrity_recognition': {
        'analysis_type': AnalysisType.VIDEO_CELEBRITIES,
        'method': 'start_celebrity_recognition',
        'params': {}
    },
    'content_moderation': {
        'analysis_type': AnalysisType.VIDEO_MODERATION,
        'method': 'start_content_moderation',
        'params': {}
    },
    'text_detection': {
        'analysis_type': AnalysisType.VIDEO_TEXT,
        'method': 'start_text_detection',
        'params': {}
    },
    'person_tracking': {
        'analysis_type': AnalysisType.VIDEO_PERSONS,
        'method': 'start_person_tracking',
        'params': {}
    },
    'face_search': {
        'analysis_type': AnalysisType.VIDEO_FACE_SEARCH,
        'method': 'start_face_search',
        'params': {}  # collection_id and face_match_threshold added at runtime
    },
    'shot_segmentation': {
        'analysis_type': AnalysisType.VIDEO_SEGMENTS,
        'method': 'start_segment_detection',
        'params': {'segment_types': ['TECHNICAL_CUE', 'SHOT']}
    }
}

# Image analysis type mapping
IMAGE_ANALYSIS_MAP = {
    'label_detection': {
        'analysis_type': AnalysisType.IMAGE_LABELS,
        'method': 'detect_labels',
        'params': {'max_labels': 100, 'min_confidence': 50.0}
    },
    'face_detection': {
        'analysis_type': AnalysisType.IMAGE_FACES,
        'method': 'detect_faces',
        'params': {'attributes': ['ALL']}
    },
    'celebrity_recognition': {
        'analysis_type': AnalysisType.IMAGE_CELEBRITIES,
        'method': 'recognize_celebrities',
        'params': {}
    },
    'content_moderation': {
        'analysis_type': AnalysisType.IMAGE_MODERATION,
        'method': 'detect_moderation_labels',
        'params': {'min_confidence': 50.0}
    },
    'text_detection': {
        'analysis_type': AnalysisType.IMAGE_TEXT,
        'method': 'detect_text',
        'params': {}
    },
    'ppe_detection': {
        'analysis_type': AnalysisType.IMAGE_PPE,
        'method': 'detect_protective_equipment',
        'params': {}
    },
    'face_search': {
        'analysis_type': AnalysisType.IMAGE_FACE_SEARCH,
        'method': 'search_faces_by_image',
        'params': {}  # collection_id added at runtime
    },
    'face_comparison': {
        'analysis_type': AnalysisType.IMAGE_FACE_COMPARE,
        'method': 'compare_faces',
        'params': {}  # special handling - needs two files
    }
}


@bp.route('/video/start', methods=['POST'])
def start_video_analysis():
    """
    Start video analysis for one or more analysis types.

    Expected JSON:
        {
            "file_id": 123,
            "analysis_types": ["label_detection", "face_detection", ...],
            "collection_id": "my-collection"  # Required if face_search is in analysis_types
        }

    Returns:
        {
            "job_ids": ["job-id-1", "job-id-2", ...],
            "job_db_ids": [1, 2, ...],
            "status": "SUBMITTED",
            "count": 2,
            "failed": []  # List of failed analysis types with error messages
        }
    """
    try:
        data = request.get_json()
        file_id = data.get('file_id')
        analysis_types = data.get('analysis_types', [])
        collection_id = data.get('collection_id')

        if not file_id:
            return jsonify({'error': 'file_id is required'}), 400

        if not analysis_types or not isinstance(analysis_types, list):
            return jsonify({'error': 'analysis_types must be a non-empty array'}), 400

        # Validate file
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        if file['file_type'] != 'video':
            return jsonify({'error': 'File is not a video'}), 400

        # Validate face_search requires collection_id
        if 'face_search' in analysis_types and not collection_id:
            return jsonify({'error': 'collection_id is required for face_search'}), 400

        # Start analysis for each type
        rekognition = get_rekognition_video_service(current_app)
        job_ids = []
        job_db_ids = []
        failed = []

        for analysis_type_str in analysis_types:
            if analysis_type_str not in VIDEO_ANALYSIS_MAP:
                failed.append({
                    'analysis_type': analysis_type_str,
                    'error': f'Unknown analysis type: {analysis_type_str}'
                })
                continue

            try:
                config = VIDEO_ANALYSIS_MAP[analysis_type_str]
                method_name = config['method']
                params = config['params'].copy()

                # Add special parameters for face_search
                if analysis_type_str == 'face_search':
                    params['collection_id'] = collection_id
                    params['face_match_threshold'] = data.get('face_match_threshold', 80.0)

                # Call the appropriate Rekognition method
                method = getattr(rekognition, method_name)
                job_id = method(file['s3_key'], **params)

                # Create job record in database
                job_db_id = db.create_job(
                    job_id=job_id,
                    file_id=file_id,
                    analysis_type=config['analysis_type'],
                    parameters=params
                )

                job_ids.append(job_id)
                job_db_ids.append(job_db_id)

            except (RekognitionError, Exception) as e:
                current_app.logger.error(f"Failed to start {analysis_type_str}: {e}")
                failed.append({
                    'analysis_type': analysis_type_str,
                    'error': str(e)
                })

        if not job_ids:
            return jsonify({
                'error': 'All analysis jobs failed to start',
                'failed': failed
            }), 500

        response = {
            'job_ids': job_ids,
            'job_db_ids': job_db_ids,
            'status': 'SUBMITTED',
            'count': len(job_ids),
            'message': f'{len(job_ids)} video analysis job(s) started successfully'
        }

        if failed:
            response['failed'] = failed
            response['message'] += f' ({len(failed)} failed)'

        return jsonify(response), 201

    except Exception as e:
        current_app.logger.error(f"Video analysis error: {e}")
        return jsonify({'error': 'Failed to start video analysis'}), 500


@bp.route('/image/analyze', methods=['POST'])
def analyze_image():
    """
    Analyze image for one or more analysis types.

    Expected JSON:
        {
            "file_id": 123,
            "analysis_types": ["label_detection", "face_detection", ...],
            "collection_id": "my-collection",  # Required if face_search is in analysis_types
            "target_file_id": 456  # Required if face_comparison is in analysis_types
        }

    Returns:
        {
            "job_id": "uuid",
            "job_db_id": 1,
            "status": "SUCCEEDED",
            "results": {
                "label_detection": {...},
                "face_detection": {...},
                ...
            },
            "failed": []  # List of failed analysis types with error messages
        }
    """
    try:
        data = request.get_json()
        file_id = data.get('file_id')
        analysis_types = data.get('analysis_types', [])
        collection_id = data.get('collection_id')
        target_file_id = data.get('target_file_id')

        if not file_id:
            return jsonify({'error': 'file_id is required'}), 400

        if not analysis_types or not isinstance(analysis_types, list):
            return jsonify({'error': 'analysis_types must be a non-empty array'}), 400

        # Validate file
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        if file['file_type'] != 'image':
            return jsonify({'error': 'File is not an image'}), 400

        # Validate face_search requires collection_id
        if 'face_search' in analysis_types and not collection_id:
            return jsonify({'error': 'collection_id is required for face_search'}), 400

        # Validate face_comparison requires target_file_id
        if 'face_comparison' in analysis_types and not target_file_id:
            return jsonify({'error': 'target_file_id is required for face_comparison'}), 400

        # Validate target file for face_comparison
        if 'face_comparison' in analysis_types:
            target_file = db.get_file(target_file_id)
            if not target_file:
                return jsonify({'error': 'Target file not found'}), 404
            if target_file['file_type'] != 'image':
                return jsonify({'error': 'Target file is not an image'}), 400

        # Perform analysis for each type
        rekognition = get_rekognition_image_service(current_app)
        results = {}
        failed = []

        for analysis_type_str in analysis_types:
            if analysis_type_str not in IMAGE_ANALYSIS_MAP:
                failed.append({
                    'analysis_type': analysis_type_str,
                    'error': f'Unknown analysis type: {analysis_type_str}'
                })
                continue

            try:
                config = IMAGE_ANALYSIS_MAP[analysis_type_str]
                method_name = config['method']
                params = config['params'].copy()

                # Special handling for face_search - use face_collection_service
                if analysis_type_str == 'face_search':
                    face_service = get_face_collection_service(current_app)
                    face_match_threshold = data.get('face_match_threshold', 80.0)
                    max_faces = data.get('max_faces', 10)
                    analysis_result = face_service.search_faces_by_image(
                        collection_id,
                        file['s3_key'],
                        face_match_threshold,
                        max_faces
                    )

                # Special handling for face_comparison
                elif analysis_type_str == 'face_comparison':
                    params['similarity_threshold'] = data.get('similarity_threshold', 80.0)
                    params['quality_filter'] = data.get('quality_filter', 'AUTO')
                    method = getattr(rekognition, method_name)
                    analysis_result = method(
                        file['s3_key'],
                        target_file['s3_key'],
                        params['similarity_threshold'],
                        params['quality_filter']
                    )

                # Standard analysis
                else:
                    method = getattr(rekognition, method_name)
                    analysis_result = method(file['s3_key'], **params)

                results[analysis_type_str] = analysis_result

            except (RekognitionImageError, FaceCollectionError, Exception) as e:
                current_app.logger.error(f"Failed to analyze {analysis_type_str}: {e}")
                failed.append({
                    'analysis_type': analysis_type_str,
                    'error': str(e)
                })

        if not results:
            return jsonify({
                'error': 'All analysis operations failed',
                'failed': failed
            }), 500

        # Create a single job record with aggregated results
        job_id = str(uuid.uuid4())
        job_db_id = db.create_job(
            job_id=job_id,
            file_id=file_id,
            analysis_type='multi_image_analysis',
            parameters={
                'analysis_types': analysis_types,
                'collection_id': collection_id,
                'target_file_id': target_file_id
            }
        )

        # Update with results immediately (synchronous)
        db.update_job_status(job_id, 'SUCCEEDED', results={'analyses': results})

        response = {
            'job_id': job_id,
            'job_db_id': job_db_id,
            'status': 'SUCCEEDED',
            'results': results,
            'count': len(results)
        }

        if failed:
            response['failed'] = failed

        return jsonify(response), 200

    except Exception as e:
        current_app.logger.error(f"Image analysis error: {e}")
        return jsonify({'error': 'Failed to analyze image'}), 500
