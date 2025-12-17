"""
AWS Rekognition face collection management service.
"""
import os
import boto3
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional, List
from functools import wraps


class FaceCollectionError(Exception):
    """Base exception for face collection errors."""
    pass


def handle_aws_errors(func):
    """Decorator to handle AWS errors."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            if error_code == 'ResourceAlreadyExistsException':
                raise FaceCollectionError("Collection already exists")
            elif error_code == 'ResourceNotFoundException':
                raise FaceCollectionError("Collection not found")
            elif error_code == 'InvalidParameterException':
                raise FaceCollectionError(f"Invalid parameters: {error_msg}")
            elif error_code == 'AccessDeniedException':
                raise FaceCollectionError("AWS permission denied")
            elif error_code == 'ThrottlingException':
                raise FaceCollectionError("AWS rate limit exceeded. Please try again.")
            else:
                raise FaceCollectionError(f"AWS error ({error_code}): {error_msg}")
    return wrapper


class FaceCollectionService:
    """Service for AWS Rekognition face collection operations."""

    def __init__(self, bucket_name: str, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        """Initialize face collection service."""
        self.bucket_name = bucket_name
        self.region = region

        # Initialize Rekognition client
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('rekognition', **session_kwargs)

    @handle_aws_errors
    def create_collection(self, collection_id: str) -> Dict[str, Any]:
        """
        Create a new face collection.

        Args:
            collection_id: Unique collection identifier

        Returns:
            Creation result with collection ARN
        """
        response = self.client.create_collection(CollectionId=collection_id)
        return {
            'collection_id': collection_id,
            'collection_arn': response['CollectionArn'],
            'face_model_version': response.get('FaceModelVersion'),
            'status_code': response['StatusCode']
        }

    @handle_aws_errors
    def list_collections(self, max_results: int = 100) -> List[str]:
        """
        List all face collections.

        Args:
            max_results: Maximum number of collections to return

        Returns:
            List of collection IDs
        """
        collection_ids = []
        next_token = None

        while True:
            params = {'MaxResults': max_results}
            if next_token:
                params['NextToken'] = next_token

            response = self.client.list_collections(**params)
            collection_ids.extend(response.get('CollectionIds', []))

            next_token = response.get('NextToken')
            if not next_token:
                break

        return collection_ids

    @handle_aws_errors
    def describe_collection(self, collection_id: str) -> Dict[str, Any]:
        """
        Get details about a collection.

        Args:
            collection_id: Collection identifier

        Returns:
            Collection details dictionary
        """
        response = self.client.describe_collection(CollectionId=collection_id)
        return {
            'collection_arn': response.get('CollectionARN'),
            'face_model_version': response.get('FaceModelVersion'),
            'face_count': response.get('FaceCount', 0),
            'created_timestamp': response.get('CreationTimestamp')
        }

    @handle_aws_errors
    def delete_collection(self, collection_id: str) -> Dict[str, Any]:
        """
        Delete a face collection.

        Args:
            collection_id: Collection identifier

        Returns:
            Deletion result
        """
        response = self.client.delete_collection(CollectionId=collection_id)
        return {
            'status_code': response['StatusCode'],
            'success': response['StatusCode'] == 200
        }

    @handle_aws_errors
    def index_faces(self, collection_id: str, s3_key: str,
                   external_image_id: Optional[str] = None,
                   max_faces: int = 1,
                   quality_filter: str = 'AUTO',
                   detection_attributes: List[str] = None) -> Dict[str, Any]:
        """
        Add faces from image to collection.

        Args:
            collection_id: Collection identifier
            s3_key: S3 key of image
            external_image_id: Optional external ID for the image
            max_faces: Maximum faces to index from image
            quality_filter: Quality filter ('NONE', 'AUTO', 'LOW', 'MEDIUM', 'HIGH')
            detection_attributes: Face attributes to detect

        Returns:
            Indexing result with face records
        """
        params = {
            'CollectionId': collection_id,
            'Image': {'S3Object': {'Bucket': self.bucket_name, 'Name': s3_key}},
            'MaxFaces': max_faces,
            'QualityFilter': quality_filter
        }

        if external_image_id:
            params['ExternalImageId'] = external_image_id

        if detection_attributes:
            params['DetectionAttributes'] = detection_attributes

        response = self.client.index_faces(**params)

        return {
            'face_records': response.get('FaceRecords', []),
            'unindexed_faces': response.get('UnindexedFaces', []),
            'face_model_version': response.get('FaceModelVersion'),
            'indexed_count': len(response.get('FaceRecords', [])),
            'unindexed_count': len(response.get('UnindexedFaces', []))
        }

    @handle_aws_errors
    def list_faces(self, collection_id: str, max_results: int = 100) -> Dict[str, Any]:
        """
        List faces in a collection.

        Args:
            collection_id: Collection identifier
            max_results: Maximum number of faces to return

        Returns:
            Dictionary with faces and metadata
        """
        faces = []
        next_token = None

        while True:
            params = {
                'CollectionId': collection_id,
                'MaxResults': max_results
            }
            if next_token:
                params['NextToken'] = next_token

            response = self.client.list_faces(**params)
            faces.extend(response.get('Faces', []))

            next_token = response.get('NextToken')
            if not next_token:
                break

        return {
            'faces': faces,
            'face_count': len(faces),
            'face_model_version': response.get('FaceModelVersion')
        }

    @handle_aws_errors
    def delete_faces(self, collection_id: str, face_ids: List[str]) -> Dict[str, Any]:
        """
        Delete faces from collection.

        Args:
            collection_id: Collection identifier
            face_ids: List of face IDs to delete

        Returns:
            Deletion result
        """
        response = self.client.delete_faces(
            CollectionId=collection_id,
            FaceIds=face_ids
        )

        return {
            'deleted_faces': response.get('DeletedFaces', []),
            'deleted_count': len(response.get('DeletedFaces', [])),
            'unsuccessful_deletions': response.get('UnsuccessfulFaceDeletions', [])
        }

    @handle_aws_errors
    def search_faces(self, collection_id: str, face_id: str,
                    max_faces: int = 10,
                    face_match_threshold: float = 80.0) -> Dict[str, Any]:
        """
        Search for similar faces in collection by face ID.

        Args:
            collection_id: Collection identifier
            face_id: Face ID to search for
            max_faces: Maximum number of matches to return
            face_match_threshold: Minimum similarity threshold (0-100)

        Returns:
            Search results with face matches
        """
        response = self.client.search_faces(
            CollectionId=collection_id,
            FaceId=face_id,
            MaxFaces=max_faces,
            FaceMatchThreshold=face_match_threshold
        )

        return {
            'face_matches': response.get('FaceMatches', []),
            'match_count': len(response.get('FaceMatches', [])),
            'searched_face_id': response.get('SearchedFaceId'),
            'face_model_version': response.get('FaceModelVersion')
        }

    @handle_aws_errors
    def search_faces_by_image(self, collection_id: str, s3_key: str,
                             max_faces: int = 10,
                             face_match_threshold: float = 80.0,
                             quality_filter: str = 'AUTO') -> Dict[str, Any]:
        """
        Search for faces in collection by providing an image.

        Args:
            collection_id: Collection identifier
            s3_key: S3 key of image to search with
            max_faces: Maximum number of matches to return
            face_match_threshold: Minimum similarity threshold (0-100)
            quality_filter: Quality filter for input image

        Returns:
            Search results with face matches
        """
        response = self.client.search_faces_by_image(
            CollectionId=collection_id,
            Image={'S3Object': {'Bucket': self.bucket_name, 'Name': s3_key}},
            MaxFaces=max_faces,
            FaceMatchThreshold=face_match_threshold,
            QualityFilter=quality_filter
        )

        return {
            'face_matches': response.get('FaceMatches', []),
            'match_count': len(response.get('FaceMatches', [])),
            'searched_face': response.get('SearchedFaceBoundingBox'),
            'searched_face_confidence': response.get('SearchedFaceConfidence'),
            'face_model_version': response.get('FaceModelVersion')
        }

    @handle_aws_errors
    def get_face_details(self, collection_id: str, face_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Get details for specific faces in collection.

        Args:
            collection_id: Collection identifier
            face_ids: List of face IDs

        Returns:
            List of face details
        """
        # Note: Rekognition doesn't have a direct API for this,
        # so we list all faces and filter
        all_faces = self.list_faces(collection_id)['faces']
        return [face for face in all_faces if face['FaceId'] in face_ids]


def get_face_collection_service(app=None) -> FaceCollectionService:
    """
    Factory function to create FaceCollectionService instance.

    Args:
        app: Flask app instance (optional)

    Returns:
        FaceCollectionService instance
    """
    if app:
        bucket_name = app.config['S3_BUCKET_NAME']
        region = app.config['AWS_REGION']
        access_key = app.config.get('AWS_ACCESS_KEY_ID')
        secret_key = app.config.get('AWS_SECRET_ACCESS_KEY')
    else:
        bucket_name = os.getenv('S3_BUCKET_NAME')
        region = os.getenv('AWS_REGION', 'us-east-1')
        access_key = os.getenv('AWS_ACCESS_KEY_ID')
        secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')

    return FaceCollectionService(bucket_name, region, access_key, secret_key)
