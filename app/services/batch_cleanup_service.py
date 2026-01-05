"""Service for cleaning up old batch processing files from S3."""
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.batch_s3_manager import BatchS3Manager

logger = logging.getLogger(__name__)


class BatchCleanupService:
    """Handles cleanup of old batch processing artifacts."""

    def __init__(self, s3_client, bucket_name: str, db, batch_s3_manager: Optional['BatchS3Manager'] = None):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.db = db
        self.batch_s3_manager = batch_s3_manager

    def cleanup_old_batch_files(self, days_old: int = 7, dry_run: bool = True) -> Dict[str, Any]:
        """
        Clean up S3 files for completed batch jobs older than specified days.

        Args:
            days_old: Minimum age in days for jobs to be cleaned up
            dry_run: If True, only report what would be deleted

        Returns:
            Summary of cleanup operation
        """
        results = {
            'jobs_processed': 0,
            'input_files_deleted': 0,
            'output_files_deleted': 0,
            'errors': [],
            'dry_run': dry_run
        }

        old_jobs = self.db.get_old_bedrock_batch_jobs(days_old)
        logger.info(f"Found {len(old_jobs)} old batch jobs to clean up")

        for job in old_jobs:
            try:
                # Delete input file
                input_key = job.get('input_s3_key')
                if input_key:
                    if dry_run:
                        logger.info(f"[DRY RUN] Would delete input: {input_key}")
                    else:
                        self.s3_client.delete_object(Bucket=self.bucket_name, Key=input_key)
                        logger.info(f"Deleted input file: {input_key}")
                    results['input_files_deleted'] += 1

                # Delete output files (prefix-based)
                output_prefix = job.get('output_s3_prefix')
                if output_prefix:
                    # List and delete all objects under the prefix
                    paginator = self.s3_client.get_paginator('list_objects_v2')
                    for page in paginator.paginate(Bucket=self.bucket_name, Prefix=output_prefix):
                        for obj in page.get('Contents', []):
                            if dry_run:
                                logger.info(f"[DRY RUN] Would delete output: {obj['Key']}")
                            else:
                                self.s3_client.delete_object(Bucket=self.bucket_name, Key=obj['Key'])
                                logger.info(f"Deleted output file: {obj['Key']}")
                            results['output_files_deleted'] += 1

                # Optionally delete the database record
                if not dry_run:
                    self.db.delete_bedrock_batch_job(job['batch_job_arn'])

                results['jobs_processed'] += 1

            except Exception as e:
                error_msg = f"Error cleaning up job {job.get('batch_job_arn')}: {str(e)}"
                logger.error(error_msg)
                results['errors'].append(error_msg)

        return results

    def get_batch_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics for batch files in S3."""
        stats = {
            'input_files': {'count': 0, 'total_bytes': 0},
            'output_files': {'count': 0, 'total_bytes': 0}
        }

        # Check bucket root for batch input files (pattern: batch_input_*.jsonl)
        # Input files are now at bucket root instead of nested folder
        paginator = self.s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix='batch_input_'):
            for obj in page.get('Contents', []):
                if obj['Key'].endswith('.jsonl'):
                    stats['input_files']['count'] += 1
                    stats['input_files']['total_bytes'] += obj.get('Size', 0)

        # Check output prefix (from config or default)
        output_prefix = os.getenv('NOVA_BATCH_OUTPUT_PREFIX', 'nova/batch/output/')
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=output_prefix):
            for obj in page.get('Contents', []):
                stats['output_files']['count'] += 1
                stats['output_files']['total_bytes'] += obj.get('Size', 0)

        return stats

    def cleanup_completed_batch_jobs(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Clean up S3 folders for all completed batch jobs that have s3_folder set.

        This method handles the new multi-chunk batch architecture where files
        are copied to isolated S3 folders (nova_batch/job_TIMESTAMP_NNN/).

        Only cleans up jobs that:
        1. Have status = 'COMPLETED'
        2. Have s3_folder set (new multi-job format)
        3. Haven't been cleaned up yet (cleanup_completed_at IS NULL)

        Args:
            dry_run: If True, only report what would be cleaned without deleting

        Returns:
            Dict with cleanup stats:
            {
                'jobs_processed': int,
                'jobs_cleaned': int,
                'objects_deleted': int,
                'bytes_freed': int,
                'errors': List[str]
            }
        """
        stats = {
            'jobs_processed': 0,
            'jobs_cleaned': 0,
            'objects_deleted': 0,
            'bytes_freed': 0,
            'errors': []
        }

        jobs = self.db.get_cleanable_batch_jobs()
        stats['jobs_processed'] = len(jobs)

        logger.info(f"Found {len(jobs)} completed batch jobs ready for cleanup")

        for job in jobs:
            job_id = job['id']
            s3_folder = job.get('s3_folder')

            if not s3_folder:
                continue

            try:
                if dry_run:
                    # Just calculate what would be deleted
                    size = self._get_folder_size(s3_folder)
                    output_size = self._get_folder_size(f"nova/batch/output/{s3_folder}")
                    stats['bytes_freed'] += size + output_size
                    stats['jobs_cleaned'] += 1
                    logger.info(f"[DRY RUN] Would clean {s3_folder}: {(size + output_size) / 1024 / 1024:.2f} MB")
                else:
                    # Actually delete the files
                    if self.batch_s3_manager:
                        cleanup_result = self.batch_s3_manager.cleanup_batch_folder(s3_folder)
                        stats['objects_deleted'] += cleanup_result['objects_deleted']
                        stats['bytes_freed'] += cleanup_result['bytes_freed']
                    else:
                        # Fallback to direct S3 cleanup
                        cleanup_result = self._cleanup_folder(s3_folder)
                        cleanup_result.update(self._cleanup_folder(f"nova/batch/output/{s3_folder}"))
                        stats['objects_deleted'] += cleanup_result['objects_deleted']
                        stats['bytes_freed'] += cleanup_result['bytes_freed']

                    # Mark as cleaned in database
                    self.db.mark_batch_job_cleaned(job_id)
                    stats['jobs_cleaned'] += 1

                    logger.info(f"Cleaned batch job {job_id}, folder {s3_folder}")

            except Exception as e:
                error_msg = f"Failed to clean job {job_id} ({s3_folder}): {e}"
                logger.error(error_msg)
                stats['errors'].append(error_msg)

        return stats

    def _get_folder_size(self, prefix: str) -> int:
        """Get total size of all objects with the given prefix."""
        total_size = 0
        paginator = self.s3_client.get_paginator('list_objects_v2')

        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                for obj in page.get('Contents', []):
                    total_size += obj.get('Size', 0)
        except Exception as e:
            logger.warning(f"Error getting folder size for {prefix}: {e}")

        return total_size

    def _cleanup_folder(self, prefix: str) -> Dict[str, int]:
        """Delete all objects with the given prefix."""
        stats = {'objects_deleted': 0, 'bytes_freed': 0}

        paginator = self.s3_client.get_paginator('list_objects_v2')

        try:
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                if 'Contents' not in page:
                    continue

                # Collect objects to delete (max 1000 per request)
                objects = []
                for obj in page['Contents']:
                    objects.append({'Key': obj['Key']})
                    stats['bytes_freed'] += obj.get('Size', 0)

                if objects:
                    self.s3_client.delete_objects(
                        Bucket=self.bucket_name,
                        Delete={'Objects': objects}
                    )
                    stats['objects_deleted'] += len(objects)

        except Exception as e:
            logger.warning(f"Error cleaning folder {prefix}: {e}")

        return stats
