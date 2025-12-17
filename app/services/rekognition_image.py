"""
AWS Rekognition image analysis service.
Handles synchronous image analysis operations.
"""
import os
import boto3
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional, List
from functools import wraps


class RekognitionImageError(Exception):
    """Base exception for Rekognition image errors."""
    pass


def handle_aws_errors(func):
    """Decorator to handle AWS errors and convert to user-friendly messages."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            if error_code == 'InvalidS3ObjectException':
                raise RekognitionImageError("File not found or inaccessible in S3")
            elif error_code == 'InvalidParameterException':
                raise RekognitionImageError(f"Invalid parameters: {error_msg}")
            elif error_code == 'InvalidImageFormatException':
                raise RekognitionImageError("Unsupported image format. Use JPEG or PNG.")
            elif error_code == 'ImageTooLargeException':
                raise RekognitionImageError("Image exceeds maximum size limit (15MB)")
            elif error_code == 'ThrottlingException':
                raise RekognitionImageError("AWS rate limit exceeded. Please try again.")
            elif error_code == 'AccessDeniedException':
                raise RekognitionImageError("AWS permission denied. Check IAM policy.")
            else:
                raise RekognitionImageError(f"AWS error ({error_code}): {error_msg}")
    return wrapper


class RekognitionImageService:
    """Service for AWS Rekognition image analysis."""

    def __init__(self, bucket_name: str, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        """Initialize Rekognition image service."""
        self.bucket_name = bucket_name
        self.region = region

        # Initialize Rekognition client
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('rekognition', **session_kwargs)

    def _get_image_object(self, s3_key: str) -> Dict[str, Any]:
        """Helper to construct image S3 object reference."""
        return {'S3Object': {'Bucket': self.bucket_name, 'Name': s3_key}}

    # Label Detection
    @handle_aws_errors
    def detect_labels(self, s3_key: str, max_labels: int = 100,
                     min_confidence: float = 50.0, features: List[str] = None) -> Dict[str, Any]:
        """
        Detect labels in image.

        Args:
            s3_key: S3 key of the image
            max_labels: Maximum number of labels (1-1000)
            min_confidence: Minimum confidence threshold (0-100)
            features: List of features ['GENERAL_LABELS', 'IMAGE_PROPERTIES']

        Returns:
            Detection results dictionary
        """
        params = {
            'Image': self._get_image_object(s3_key),
            'MaxLabels': max_labels,
            'MinConfidence': min_confidence
        }

        if features:
            params['Features'] = features

        response = self.client.detect_labels(**params)
        return {
            'labels': response.get('Labels', []),
            'label_model_version': response.get('LabelModelVersion'),
            'image_properties': response.get('ImageProperties')
        }

    # Face Detection
    @handle_aws_errors
    def detect_faces(self, s3_key: str, attributes: List[str] = None) -> Dict[str, Any]:
        """
        Detect faces in image.

        Args:
            s3_key: S3 key of the image
            attributes: Face attributes to return ['ALL', 'DEFAULT']

        Returns:
            Face detection results dictionary
        """
        params = {
            'Image': self._get_image_object(s3_key)
        }

        if attributes is None:
            attributes = ['ALL']
        params['Attributes'] = attributes

        response = self.client.detect_faces(**params)
        return {
            'faces': response.get('FaceDetails', []),
            'face_count': len(response.get('FaceDetails', [])),
            'orientation_correction': response.get('OrientationCorrection')
        }

    # Face Comparison
    @handle_aws_errors
    def compare_faces(self, source_s3_key: str, target_s3_key: str,
                     similarity_threshold: float = 80.0,
                     quality_filter: str = 'AUTO') -> Dict[str, Any]:
        """
        Compare faces between two images.

        Args:
            source_s3_key: S3 key of the source image
            target_s3_key: S3 key of the target image
            similarity_threshold: Minimum similarity (0-100)
            quality_filter: Quality filter ('NONE', 'AUTO', 'LOW', 'MEDIUM', 'HIGH')

        Returns:
            Face comparison results dictionary
        """
        response = self.client.compare_faces(
            SourceImage=self._get_image_object(source_s3_key),
            TargetImage=self._get_image_object(target_s3_key),
            SimilarityThreshold=similarity_threshold,
            QualityFilter=quality_filter
        )

        return {
            'face_matches': response.get('FaceMatches', []),
            'unmatched_faces': response.get('UnmatchedFaces', []),
            'source_face': response.get('SourceImageFace'),
            'orientation_correction': response.get('SourceImageOrientationCorrection')
        }

    # Celebrity Recognition
    @handle_aws_errors
    def recognize_celebrities(self, s3_key: str) -> Dict[str, Any]:
        """
        Recognize celebrities in image.

        Args:
            s3_key: S3 key of the image

        Returns:
            Celebrity recognition results dictionary
        """
        response = self.client.recognize_celebrities(
            Image=self._get_image_object(s3_key)
        )

        return {
            'celebrities': response.get('CelebrityFaces', []),
            'unrecognized_faces': response.get('UnrecognizedFaces', []),
            'celebrity_count': len(response.get('CelebrityFaces', [])),
            'orientation_correction': response.get('OrientationCorrection')
        }

    # Content Moderation
    @handle_aws_errors
    def detect_moderation_labels(self, s3_key: str, min_confidence: float = 50.0) -> Dict[str, Any]:
        """
        Detect unsafe or inappropriate content in image.

        Args:
            s3_key: S3 key of the image
            min_confidence: Minimum confidence threshold (0-100)

        Returns:
            Moderation results dictionary
        """
        response = self.client.detect_moderation_labels(
            Image=self._get_image_object(s3_key),
            MinConfidence=min_confidence
        )

        return {
            'moderation_labels': response.get('ModerationLabels', []),
            'moderation_model_version': response.get('ModerationModelVersion'),
            'flagged_content': len(response.get('ModerationLabels', [])) > 0
        }

    # Text Detection (OCR)
    @handle_aws_errors
    def detect_text(self, s3_key: str, word_filter: Dict[str, Any] = None,
                   region_filter: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Detect text in image.

        Args:
            s3_key: S3 key of the image
            word_filter: Word filter configuration
            region_filter: Region of interest filter

        Returns:
            Text detection results dictionary
        """
        params = {
            'Image': self._get_image_object(s3_key)
        }

        # Build filters
        filters = {}
        if word_filter:
            filters['WordFilter'] = word_filter
        if region_filter:
            filters['RegionsOfInterest'] = region_filter
        if filters:
            params['Filters'] = filters

        response = self.client.detect_text(**params)

        # Separate lines and words
        text_detections = response.get('TextDetections', [])
        lines = [t for t in text_detections if t.get('Type') == 'LINE']
        words = [t for t in text_detections if t.get('Type') == 'WORD']

        # Extract full text
        full_text = ' '.join([t.get('DetectedText', '') for t in lines])

        return {
            'text_detections': text_detections,
            'lines': lines,
            'words': words,
            'full_text': full_text,
            'text_model_version': response.get('TextModelVersion')
        }

    # PPE Detection (Personal Protective Equipment)
    @handle_aws_errors
    def detect_protective_equipment(self, s3_key: str,
                                   summarization_attributes: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Detect personal protective equipment in image.

        Args:
            s3_key: S3 key of the image
            summarization_attributes: Summary configuration

        Returns:
            PPE detection results dictionary
        """
        params = {
            'Image': self._get_image_object(s3_key)
        }

        if summarization_attributes:
            params['SummarizationAttributes'] = summarization_attributes

        response = self.client.detect_protective_equipment(**params)

        return {
            'persons': response.get('Persons', []),
            'person_count': len(response.get('Persons', [])),
            'summary': response.get('Summary'),
            'ppe_model_version': response.get('ProtectiveEquipmentModelVersion')
        }

    # Custom Labels
    @handle_aws_errors
    def detect_custom_labels(self, s3_key: str, project_version_arn: str,
                            min_confidence: float = 50.0, max_results: int = 100) -> Dict[str, Any]:
        """
        Detect custom labels using a trained model.

        Args:
            s3_key: S3 key of the image
            project_version_arn: ARN of the custom labels project version
            min_confidence: Minimum confidence threshold (0-100)
            max_results: Maximum number of results

        Returns:
            Custom label detection results dictionary
        """
        response = self.client.detect_custom_labels(
            Image=self._get_image_object(s3_key),
            ProjectVersionArn=project_version_arn,
            MinConfidence=min_confidence,
            MaxResults=max_results
        )

        return {
            'custom_labels': response.get('CustomLabels', []),
            'label_count': len(response.get('CustomLabels', []))
        }

    # Image Quality Assessment (helper for face enrollment)
    @handle_aws_errors
    def assess_image_quality(self, s3_key: str) -> Dict[str, Any]:
        """
        Assess image quality for face enrollment.

        Args:
            s3_key: S3 key of the image

        Returns:
            Quality assessment dictionary
        """
        # Use face detection with quality checks
        response = self.client.detect_faces(
            Image=self._get_image_object(s3_key),
            Attributes=['ALL']
        )

        faces = response.get('FaceDetails', [])
        if not faces:
            return {
                'has_faces': False,
                'quality_score': 0,
                'suitable_for_enrollment': False
            }

        # Get quality metrics from first face
        first_face = faces[0]
        quality = first_face.get('Quality', {})
        brightness = quality.get('Brightness', 0)
        sharpness = quality.get('Sharpness', 0)

        # Simple quality score (average of brightness and sharpness)
        quality_score = (brightness + sharpness) / 2

        return {
            'has_faces': True,
            'face_count': len(faces),
            'quality_score': quality_score,
            'brightness': brightness,
            'sharpness': sharpness,
            'suitable_for_enrollment': quality_score > 50
        }


def get_rekognition_image_service(app=None) -> RekognitionImageService:
    """
    Factory function to create RekognitionImageService instance.

    Args:
        app: Flask app instance (optional)

    Returns:
        RekognitionImageService instance
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

    return RekognitionImageService(bucket_name, region, access_key, secret_key)
