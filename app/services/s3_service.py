"""
AWS S3 service for file upload and management.
"""
import os
import boto3
import uuid
from pathlib import Path
from botocore.exceptions import ClientError
from werkzeug.utils import secure_filename
from typing import Dict, Any, Optional, List


class S3Error(Exception):
    """Base exception for S3 errors."""
    pass


class S3Service:
    """Service for AWS S3 operations."""

    def __init__(self, bucket_name: str, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        """Initialize S3 service."""
        self.bucket_name = bucket_name
        self.region = region

        # Initialize S3 client
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.s3_client = boto3.client('s3', **session_kwargs)

    def generate_presigned_post(self, filename: str, content_type: str,
                               max_size_mb: int = 100) -> Dict[str, Any]:
        """
        Generate presigned POST data for direct browser-to-S3 upload.

        Args:
            filename: Original filename
            content_type: MIME type of file
            max_size_mb: Maximum file size in MB

        Returns:
            Dictionary with 'url', 'fields', and 's3_key'
        """
        # Generate unique S3 key
        file_ext = Path(filename).suffix
        safe_filename = secure_filename(filename)
        s3_key = f"uploads/{uuid.uuid4()}/{safe_filename}"

        # Define upload conditions
        conditions = [
            {"bucket": self.bucket_name},
            {"key": s3_key},
            {"Content-Type": content_type},
            ["content-length-range", 0, max_size_mb * 1024 * 1024]
        ]

        try:
            response = self.s3_client.generate_presigned_post(
                Bucket=self.bucket_name,
                Key=s3_key,
                Fields={"Content-Type": content_type},
                Conditions=conditions,
                ExpiresIn=3600  # 1 hour expiration
            )

            return {
                'url': response['url'],
                'fields': response['fields'],
                's3_key': s3_key
            }
        except ClientError as e:
            raise S3Error(f"Failed to generate presigned POST: {e}")

    def upload_file(self, file_obj, s3_key: str, content_type: str) -> bool:
        """
        Upload file directly to S3 (fallback method).

        Args:
            file_obj: File object to upload
            s3_key: S3 key for the file
            content_type: MIME type of file

        Returns:
            True if successful
        """
        try:
            self.s3_client.upload_fileobj(
                file_obj,
                self.bucket_name,
                s3_key,
                ExtraArgs={'ContentType': content_type}
            )
            return True
        except ClientError as e:
            raise S3Error(f"Failed to upload file: {e}")

    def generate_presigned_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """
        Generate presigned URL for viewing/downloading a file.

        Args:
            s3_key: S3 key of the file
            expires_in: URL expiration time in seconds

        Returns:
            Presigned URL string
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            raise S3Error(f"Failed to generate presigned URL: {e}")

    def list_files(self, prefix: str = '', max_keys: int = 1000) -> List[Dict[str, Any]]:
        """
        List files in S3 bucket.

        Args:
            prefix: Prefix to filter files
            max_keys: Maximum number of files to return

        Returns:
            List of file metadata dictionaries
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )

            files = []
            for obj in response.get('Contents', []):
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                    'etag': obj['ETag']
                })
            return files
        except ClientError as e:
            raise S3Error(f"Failed to list files: {e}")

    def get_file_metadata(self, s3_key: str) -> Dict[str, Any]:
        """
        Get metadata for a specific file.

        Args:
            s3_key: S3 key of the file

        Returns:
            File metadata dictionary
        """
        try:
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return {
                'size': response['ContentLength'],
                'content_type': response.get('ContentType', ''),
                'last_modified': response['LastModified'].isoformat(),
                'etag': response['ETag'],
                'metadata': response.get('Metadata', {})
            }
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise S3Error(f"File not found: {s3_key}")
            raise S3Error(f"Failed to get file metadata: {e}")

    def delete_file(self, s3_key: str) -> bool:
        """
        Delete file from S3.

        Args:
            s3_key: S3 key of the file

        Returns:
            True if successful
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            return True
        except ClientError as e:
            raise S3Error(f"Failed to delete file: {e}")

    def file_exists(self, s3_key: str) -> bool:
        """
        Check if file exists in S3.

        Args:
            s3_key: S3 key of the file

        Returns:
            True if file exists
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise S3Error(f"Failed to check file existence: {e}")


def get_s3_service(app=None) -> S3Service:
    """
    Factory function to create S3Service instance.

    Args:
        app: Flask app instance (optional)

    Returns:
        S3Service instance
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

    return S3Service(bucket_name, region, access_key, secret_key)
