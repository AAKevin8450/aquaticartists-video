"""
Face collection routes for managing Rekognition face collections.
"""
from flask import Blueprint, request, jsonify, current_app
from app.services.face_collection_service import get_face_collection_service, FaceCollectionError
from app.database import get_db
from app.utils.validators import validate_collection_id, ValidationError

bp = Blueprint('collections', __name__, url_prefix='/api/collections')


@bp.route('', methods=['GET'])
def list_collections():
    """
    List all face collections.

    Returns:
        {
            "collections": [...]
        }
    """
    try:
        face_service = get_face_collection_service(current_app)
        collection_ids = face_service.list_collections()

        # Get details for each collection
        collections = []
        for collection_id in collection_ids:
            try:
                details = face_service.describe_collection(collection_id)
                collections.append({
                    'collection_id': collection_id,
                    'face_count': details['face_count'],
                    'face_model_version': details['face_model_version'],
                    'created_timestamp': str(details.get('created_timestamp', ''))
                })
            except FaceCollectionError:
                # Collection may have been deleted, skip it
                continue

        return jsonify({'collections': collections}), 200

    except FaceCollectionError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"List collections error: {e}")
        return jsonify({'error': 'Failed to list collections'}), 500


@bp.route('', methods=['POST'])
def create_collection():
    """
    Create a new face collection.

    Expected JSON:
        {
            "collection_id": "my-collection"
        }
    """
    try:
        data = request.get_json()
        collection_id = data.get('collection_id')

        if not collection_id:
            return jsonify({'error': 'collection_id is required'}), 400

        validate_collection_id(collection_id)

        # Create collection in Rekognition
        face_service = get_face_collection_service(current_app)
        result = face_service.create_collection(collection_id)

        # Store in database
        db = get_db()
        db.create_collection(
            collection_id=collection_id,
            collection_arn=result['collection_arn'],
            metadata={'face_model_version': result.get('face_model_version')}
        )

        return jsonify({
            'collection_id': collection_id,
            'collection_arn': result['collection_arn'],
            'message': 'Collection created successfully'
        }), 201

    except ValidationError as e:
        return jsonify({'error': str(e)}), 400
    except FaceCollectionError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Create collection error: {e}")
        return jsonify({'error': 'Failed to create collection'}), 500


@bp.route('/<collection_id>', methods=['DELETE'])
def delete_collection(collection_id):
    """
    Delete a face collection.
    """
    try:
        # Delete from Rekognition
        face_service = get_face_collection_service(current_app)
        face_service.delete_collection(collection_id)

        # Delete from database
        db = get_db()
        db.delete_collection(collection_id)

        return jsonify({'message': 'Collection deleted successfully'}), 200

    except FaceCollectionError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Delete collection error: {e}")
        return jsonify({'error': 'Failed to delete collection'}), 500


@bp.route('/<collection_id>/faces', methods=['GET'])
def list_faces(collection_id):
    """
    List faces in a collection.
    """
    try:
        face_service = get_face_collection_service(current_app)
        result = face_service.list_faces(collection_id, max_results=100)

        return jsonify(result), 200

    except FaceCollectionError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"List faces error: {e}")
        return jsonify({'error': 'Failed to list faces'}), 500


@bp.route('/<collection_id>/faces', methods=['POST'])
def add_faces(collection_id):
    """
    Add faces from an image to the collection.

    Expected JSON:
        {
            "file_id": 123,
            "external_image_id": "person-1",
            "max_faces": 1
        }
    """
    try:
        data = request.get_json()
        file_id = data.get('file_id')
        external_image_id = data.get('external_image_id')
        max_faces = data.get('max_faces', 1)

        if not file_id:
            return jsonify({'error': 'file_id is required'}), 400

        # Get file
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        if file['file_type'] != 'image':
            return jsonify({'error': 'File must be an image'}), 400

        # Index faces
        face_service = get_face_collection_service(current_app)
        result = face_service.index_faces(
            collection_id,
            file['s3_key'],
            external_image_id=external_image_id,
            max_faces=max_faces
        )

        # Update collection face count in database
        collection = db.get_collection(collection_id)
        if collection:
            new_count = collection['face_count'] + result['indexed_count']
            db.update_collection_face_count(collection_id, new_count)

        return jsonify(result), 201

    except FaceCollectionError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Add faces error: {e}")
        return jsonify({'error': 'Failed to add faces'}), 500


@bp.route('/<collection_id>/faces/<face_id>', methods=['DELETE'])
def delete_face(collection_id, face_id):
    """
    Delete a face from the collection.
    """
    try:
        face_service = get_face_collection_service(current_app)
        result = face_service.delete_faces(collection_id, [face_id])

        # Update face count
        if result['deleted_count'] > 0:
            db = get_db()
            collection = db.get_collection(collection_id)
            if collection:
                new_count = max(0, collection['face_count'] - result['deleted_count'])
                db.update_collection_face_count(collection_id, new_count)

        return jsonify(result), 200

    except FaceCollectionError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Delete face error: {e}")
        return jsonify({'error': 'Failed to delete face'}), 500


@bp.route('/<collection_id>/search', methods=['POST'])
def search_faces(collection_id):
    """
    Search for faces in collection by providing an image.

    Expected JSON:
        {
            "file_id": 123,
            "max_faces": 10,
            "face_match_threshold": 80.0
        }
    """
    try:
        data = request.get_json()
        file_id = data.get('file_id')
        max_faces = data.get('max_faces', 10)
        face_match_threshold = data.get('face_match_threshold', 80.0)

        if not file_id:
            return jsonify({'error': 'file_id is required'}), 400

        # Get file
        db = get_db()
        file = db.get_file(file_id)

        if not file:
            return jsonify({'error': 'File not found'}), 404

        if file['file_type'] != 'image':
            return jsonify({'error': 'File must be an image'}), 400

        # Search faces
        face_service = get_face_collection_service(current_app)
        result = face_service.search_faces_by_image(
            collection_id,
            file['s3_key'],
            max_faces=max_faces,
            face_match_threshold=face_match_threshold
        )

        return jsonify(result), 200

    except FaceCollectionError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Search faces error: {e}")
        return jsonify({'error': 'Failed to search faces'}), 500
