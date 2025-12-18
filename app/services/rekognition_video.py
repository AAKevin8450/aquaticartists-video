"""
AWS Rekognition video analysis service.
Handles async video analysis jobs with polling.
"""
import os
import boto3
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional, List
from functools import wraps


class RekognitionError(Exception):
    """Base exception for Rekognition errors."""
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
                raise RekognitionError("File not found or inaccessible in S3")
            elif error_code == 'InvalidParameterException':
                raise RekognitionError(f"Invalid parameters: {error_msg}")
            elif error_code == 'ThrottlingException':
                raise RekognitionError("AWS rate limit exceeded. Please try again in a moment.")
            elif error_code == 'ProvisionedThroughputExceededException':
                raise RekognitionError("Service capacity exceeded. Please try again later.")
            elif error_code == 'VideoTooLargeException':
                raise RekognitionError("Video file exceeds maximum size limit")
            elif error_code == 'AccessDeniedException':
                raise RekognitionError("AWS permission denied. Check IAM policy.")
            else:
                raise RekognitionError(f"AWS error ({error_code}): {error_msg}")
    return wrapper


class RekognitionVideoService:
    """Service for AWS Rekognition video analysis."""

    def __init__(self, bucket_name: str, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        """Initialize Rekognition video service."""
        self.bucket_name = bucket_name
        self.region = region

        # Initialize Rekognition client
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('rekognition', **session_kwargs)

    def _get_video_object(self, s3_key: str) -> Dict[str, Any]:
        """Helper to construct video S3 object reference."""
        return {'S3Object': {'Bucket': self.bucket_name, 'Name': s3_key}}

    # Label Detection
    @handle_aws_errors
    def start_label_detection(self, s3_key: str, min_confidence: float = 50.0,
                             max_labels: int = 1000) -> str:
        """
        Start label detection job for video.

        Args:
            s3_key: S3 key of the video
            min_confidence: Minimum confidence threshold (0-100)
            max_labels: Maximum number of labels to return

        Returns:
            JobId string
        """
        response = self.client.start_label_detection(
            Video=self._get_video_object(s3_key),
            MinConfidence=min_confidence,
            Features=['GENERAL_LABELS']
        )
        return response['JobId']

    @handle_aws_errors
    def get_label_detection(self, job_id: str) -> Dict[str, Any]:
        """Get label detection results."""
        return self._get_paginated_results(
            self.client.get_label_detection,
            job_id,
            'Labels'
        )

    # Face Detection
    @handle_aws_errors
    def start_face_detection(self, s3_key: str, attributes: str = 'ALL') -> str:
        """
        Start face detection job for video.

        Args:
            s3_key: S3 key of the video
            attributes: 'DEFAULT' or 'ALL' for detailed attributes

        Returns:
            JobId string
        """
        response = self.client.start_face_detection(
            Video=self._get_video_object(s3_key),
            FaceAttributes=attributes
        )
        return response['JobId']

    @handle_aws_errors
    def get_face_detection(self, job_id: str) -> Dict[str, Any]:
        """Get face detection results."""
        return self._get_paginated_results(
            self.client.get_face_detection,
            job_id,
            'Faces'
        )

    # Celebrity Recognition
    @handle_aws_errors
    def start_celebrity_recognition(self, s3_key: str) -> str:
        """
        Start celebrity recognition job for video.

        Args:
            s3_key: S3 key of the video

        Returns:
            JobId string
        """
        response = self.client.start_celebrity_recognition(
            Video=self._get_video_object(s3_key)
        )
        return response['JobId']

    @handle_aws_errors
    def get_celebrity_recognition(self, job_id: str) -> Dict[str, Any]:
        """Get celebrity recognition results."""
        return self._get_paginated_results(
            self.client.get_celebrity_recognition,
            job_id,
            'Celebrities'
        )

    # Content Moderation
    @handle_aws_errors
    def start_content_moderation(self, s3_key: str, min_confidence: float = 50.0) -> str:
        """
        Start content moderation job for video.

        Args:
            s3_key: S3 key of the video
            min_confidence: Minimum confidence threshold (0-100)

        Returns:
            JobId string
        """
        response = self.client.start_content_moderation(
            Video=self._get_video_object(s3_key),
            MinConfidence=min_confidence
        )
        return response['JobId']

    @handle_aws_errors
    def get_content_moderation(self, job_id: str) -> Dict[str, Any]:
        """Get content moderation results."""
        return self._get_paginated_results(
            self.client.get_content_moderation,
            job_id,
            'ModerationLabels'
        )

    # Text Detection
    @handle_aws_errors
    def start_text_detection(self, s3_key: str, min_confidence: float = 50.0) -> str:
        """
        Start text detection job for video.

        Args:
            s3_key: S3 key of the video
            min_confidence: Minimum confidence threshold (0-100)

        Returns:
            JobId string
        """
        filters = {
            'WordFilter': {
                'MinConfidence': min_confidence
            }
        }
        response = self.client.start_text_detection(
            Video=self._get_video_object(s3_key),
            Filters=filters
        )
        return response['JobId']

    @handle_aws_errors
    def get_text_detection(self, job_id: str) -> Dict[str, Any]:
        """Get text detection results."""
        return self._get_paginated_results(
            self.client.get_text_detection,
            job_id,
            'TextDetections'
        )

    # Segment Detection
    @handle_aws_errors
    def start_segment_detection(self, s3_key: str, segment_types: List[str] = None) -> str:
        """
        Start segment detection job for video.

        Args:
            s3_key: S3 key of the video
            segment_types: List of segment types ['TECHNICAL_CUE', 'SHOT']

        Returns:
            JobId string
        """
        if segment_types is None:
            segment_types = ['TECHNICAL_CUE', 'SHOT']

        response = self.client.start_segment_detection(
            Video=self._get_video_object(s3_key),
            SegmentTypes=segment_types
        )
        return response['JobId']

    @handle_aws_errors
    def get_segment_detection(self, job_id: str) -> Dict[str, Any]:
        """Get segment detection results."""
        result = self._get_paginated_results(
            self.client.get_segment_detection,
            job_id,
            'Segments'
        )
        # Also include TechnicalCueSegments and ShotSegments if available
        response = self.client.get_segment_detection(JobId=job_id)
        result['TechnicalCueSegments'] = response.get('SelectedSegmentTypes', {}).get('TechnicalCueSegment', [])
        result['ShotSegments'] = response.get('SelectedSegmentTypes', {}).get('ShotSegment', [])
        return result

    # Person Tracking
    @handle_aws_errors
    def start_person_tracking(self, s3_key: str) -> str:
        """
        Start person tracking job for video.

        Args:
            s3_key: S3 key of the video

        Returns:
            JobId string
        """
        response = self.client.start_person_tracking(
            Video=self._get_video_object(s3_key)
        )
        return response['JobId']

    @handle_aws_errors
    def get_person_tracking(self, job_id: str) -> Dict[str, Any]:
        """Get person tracking results."""
        return self._get_paginated_results(
            self.client.get_person_tracking,
            job_id,
            'Persons'
        )

    # Face Search (requires collection)
    @handle_aws_errors
    def start_face_search(self, s3_key: str, collection_id: str,
                         face_match_threshold: float = 80.0) -> str:
        """
        Start face search job for video against a face collection.

        Args:
            s3_key: S3 key of the video
            collection_id: Face collection ID to search against
            face_match_threshold: Minimum similarity threshold (0-100)

        Returns:
            JobId string
        """
        response = self.client.start_face_search(
            Video=self._get_video_object(s3_key),
            CollectionId=collection_id,
            FaceMatchThreshold=face_match_threshold
        )
        return response['JobId']

    @handle_aws_errors
    def get_face_search(self, job_id: str) -> Dict[str, Any]:
        """Get face search results."""
        return self._get_paginated_results(
            self.client.get_face_search,
            job_id,
            'Persons'
        )

    # Generic job status checker
    @handle_aws_errors
    def get_job_status(self, job_id: str, job_type: str = 'LabelDetection') -> Dict[str, Any]:
        """
        Get job status and results if complete.

        Args:
            job_id: AWS Rekognition job ID
            job_type: Type of job (LabelDetection, FaceDetection, etc.)

        Returns:
            Dictionary with status, results (if complete), and error (if failed)
        """
        # Map job types to getter methods
        getter_map = {
            'LabelDetection': self.client.get_label_detection,
            'FaceDetection': self.client.get_face_detection,
            'CelebrityRecognition': self.client.get_celebrity_recognition,
            'ContentModeration': self.client.get_content_moderation,
            'TextDetection': self.client.get_text_detection,
            'SegmentDetection': self.client.get_segment_detection,
            'PersonTracking': self.client.get_person_tracking,
            'FaceSearch': self.client.get_face_search,
        }

        get_method = getter_map.get(job_type)
        if not get_method:
            raise RekognitionError(f"Unknown job type: {job_type}")

        # Get initial response
        response = get_method(JobId=job_id, MaxResults=1)
        status = response['JobStatus']

        if status == 'SUCCEEDED':
            # Get full paginated results
            result_key_map = {
                'LabelDetection': 'Labels',
                'FaceDetection': 'Faces',
                'CelebrityRecognition': 'Celebrities',
                'ContentModeration': 'ModerationLabels',
                'TextDetection': 'TextDetections',
                'SegmentDetection': 'Segments',
                'PersonTracking': 'Persons',
                'FaceSearch': 'Persons',
            }
            result_key = result_key_map.get(job_type, 'Results')
            full_results = self._get_paginated_results(get_method, job_id, result_key)
            return {
                'status': status,
                'results': full_results.get('results', []),
                'video_metadata': full_results.get('video_metadata', {})
            }
        elif status == 'FAILED':
            return {
                'status': status,
                'error': response.get('StatusMessage', 'Unknown error occurred')
            }
        else:  # IN_PROGRESS or SUBMITTED
            return {'status': status}

    def _get_paginated_results(self, get_method, job_id: str, result_key: str) -> Dict[str, Any]:
        """
        Helper to paginate through all results.

        Args:
            get_method: Boto3 method to call
            job_id: Job ID
            result_key: Key in response containing results

        Returns:
            Combined results dictionary
        """
        results = []
        next_token = None
        video_metadata = None

        while True:
            params = {'JobId': job_id, 'MaxResults': 1000}
            if next_token:
                params['NextToken'] = next_token

            response = get_method(**params)

            # Collect results
            if result_key in response:
                results.extend(response[result_key])

            # Save video metadata from first response
            if video_metadata is None:
                vm = response.get('VideoMetadata', {})
                # Handle case where VideoMetadata is a list (segment detection) or dict (other types)
                if isinstance(vm, list) and len(vm) > 0:
                    vm = vm[0]
                elif not isinstance(vm, dict):
                    vm = {}

                video_metadata = {
                    'codec': vm.get('Codec'),
                    'duration_millis': vm.get('DurationMillis'),
                    'format': vm.get('Format'),
                    'frame_rate': vm.get('FrameRate'),
                    'frame_height': vm.get('FrameHeight'),
                    'frame_width': vm.get('FrameWidth'),
                }

            # Check for more results
            next_token = response.get('NextToken')
            if not next_token:
                break

        return {
            'results': results,
            'video_metadata': video_metadata,
            'result_count': len(results)
        }


def get_rekognition_video_service(app=None) -> RekognitionVideoService:
    """
    Factory function to create RekognitionVideoService instance.

    Args:
        app: Flask app instance (optional)

    Returns:
        RekognitionVideoService instance
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

    return RekognitionVideoService(bucket_name, region, access_key, secret_key)
