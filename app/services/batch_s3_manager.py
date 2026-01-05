"""
Service for managing S3 files during batch processing.
Handles copying files with sanitized names and cleanup after processing.
"""
import logging
from typing import List, Dict, Optional
from botocore.exceptions import ClientError

from app.utils.filename_sanitizer import sanitize_filename

logger = logging.getLogger(__name__)


class BatchS3Manager:
    """
    Manages S3 operations for Nova batch processing.

    Responsibilities:
    1. Copy proxy files to batch folder with sanitized filenames
    2. Upload JSONL manifest files
    3. Clean up batch folders after successful processing
    """

    def __init__(self, s3_client, bucket_name: str):
        """
        Initialize the manager.

        Args:
            s3_client: boto3 S3 client instance
            bucket_name: Name of the S3 bucket
        """
        self.s3 = s3_client
        self.bucket = bucket_name

    def prepare_batch_files(
        self,
        proxy_s3_keys: List[str],
        batch_folder: str
    ) -> Dict[str, str]:
        """
        Copy proxy files to batch folder with sanitized filenames.

        Creates sanitized copies in: {batch_folder}/files/{sanitized_filename}

        Args:
            proxy_s3_keys: List of original proxy S3 keys
                Example: ["proxy_video/Video Nov 14 2025_22153_720p15.mov"]
            batch_folder: Target batch folder
                Example: "nova_batch/job_20260105_123456_001"

        Returns:
            Dict mapping original_key -> sanitized_key
                Example: {
                    "proxy_video/Video Nov 14 2025_22153_720p15.mov":
                    "nova_batch/job_20260105_123456_001/files/Video_Nov_14_2025_22153_720p15.mov"
                }

        Raises:
            Exception: If any file copy fails
        """
        key_mapping = {}
        files_folder = f"{batch_folder}/files"

        for original_key in proxy_s3_keys:
            # Extract filename from path and sanitize
            original_filename = original_key.rsplit('/', 1)[-1]
            sanitized_filename = sanitize_filename(original_filename)
            sanitized_key = f"{files_folder}/{sanitized_filename}"

            # Copy object to new location with sanitized name
            try:
                self.s3.copy_object(
                    Bucket=self.bucket,
                    CopySource={'Bucket': self.bucket, 'Key': original_key},
                    Key=sanitized_key
                )
                key_mapping[original_key] = sanitized_key
                logger.debug(f"Copied {original_key} -> {sanitized_key}")
            except ClientError as e:
                logger.error(f"Failed to copy {original_key} to {sanitized_key}: {e}")
                raise Exception(f"Failed to prepare batch file: {original_key}") from e

        logger.info(f"Prepared {len(key_mapping)} files in {batch_folder}")
        return key_mapping

    def upload_manifest(
        self,
        manifest_content: str,
        batch_folder: str
    ) -> str:
        """
        Upload the JSONL manifest file to the batch folder.

        Args:
            manifest_content: JSONL content (newline-separated JSON records)
            batch_folder: Target batch folder

        Returns:
            S3 key of the uploaded manifest
                Example: "nova_batch/job_20260105_123456_001/manifest.jsonl"
        """
        manifest_key = f"{batch_folder}/manifest.jsonl"

        self.s3.put_object(
            Bucket=self.bucket,
            Key=manifest_key,
            Body=manifest_content.encode('utf-8'),
            ContentType='application/jsonl'
        )

        logger.info(f"Uploaded manifest to {manifest_key}")
        return manifest_key

    def cleanup_batch_folder(self, batch_folder: str) -> Dict[str, int]:
        """
        Delete all files in a batch folder and its output folder.

        Cleans up:
        - {batch_folder}/* (manifest and copied files)
        - nova/batch/output/{batch_folder}/* (output results)

        Args:
            batch_folder: Folder to clean up
                Example: "nova_batch/job_20260105_123456_001"

        Returns:
            Dict with cleanup stats:
                {'objects_deleted': int, 'bytes_freed': int}
        """
        stats = {'objects_deleted': 0, 'bytes_freed': 0}

        # Clean both input and output folders
        folders_to_clean = [
            batch_folder,
            f"nova/batch/output/{batch_folder}"
        ]

        for folder in folders_to_clean:
            folder_stats = self._delete_folder_contents(folder)
            stats['objects_deleted'] += folder_stats['objects_deleted']
            stats['bytes_freed'] += folder_stats['bytes_freed']

        logger.info(
            f"Cleaned up {batch_folder}: "
            f"{stats['objects_deleted']} objects, "
            f"{stats['bytes_freed'] / 1024 / 1024:.2f} MB freed"
        )
        return stats

    def _delete_folder_contents(self, prefix: str) -> Dict[str, int]:
        """Delete all objects with the given prefix."""
        stats = {'objects_deleted': 0, 'bytes_freed': 0}

        paginator = self.s3.get_paginator('list_objects_v2')

        try:
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)

            for page in pages:
                if 'Contents' not in page:
                    continue

                # Collect objects to delete (max 1000 per request)
                objects = []
                for obj in page['Contents']:
                    objects.append({'Key': obj['Key']})
                    stats['bytes_freed'] += obj['Size']

                if objects:
                    self.s3.delete_objects(
                        Bucket=self.bucket,
                        Delete={'Objects': objects}
                    )
                    stats['objects_deleted'] += len(objects)

        except ClientError as e:
            logger.warning(f"Error cleaning folder {prefix}: {e}")

        return stats

    def get_folder_size(self, folder: str) -> int:
        """
        Get total size of all objects in a folder.

        Args:
            folder: S3 prefix to measure

        Returns:
            Total size in bytes
        """
        total_size = 0
        paginator = self.s3.get_paginator('list_objects_v2')

        try:
            pages = paginator.paginate(Bucket=self.bucket, Prefix=folder)
            for page in pages:
                if 'Contents' in page:
                    total_size += sum(obj['Size'] for obj in page['Contents'])
        except ClientError as e:
            logger.warning(f"Error getting folder size for {folder}: {e}")

        return total_size

    def verify_files_exist(self, s3_keys: List[str]) -> Dict[str, bool]:
        """
        Check which files exist in S3.

        Args:
            s3_keys: List of S3 keys to check

        Returns:
            Dict mapping key -> exists (True/False)
        """
        results = {}
        for key in s3_keys:
            try:
                self.s3.head_object(Bucket=self.bucket, Key=key)
                results[key] = True
            except ClientError:
                results[key] = False
        return results
