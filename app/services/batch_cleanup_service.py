"""Service for cleaning up old batch processing files from S3."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class BatchCleanupService:
    """Handles cleanup of old batch processing artifacts."""

    def __init__(self, s3_client, bucket_name: str, db):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.db = db

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

        # Check input prefix
        input_prefix = 'nova/batch/input/'
        paginator = self.s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=input_prefix):
            for obj in page.get('Contents', []):
                stats['input_files']['count'] += 1
                stats['input_files']['total_bytes'] += obj.get('Size', 0)

        # Check output prefix
        output_prefix = 'nova/batch/output/'
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=output_prefix):
            for obj in page.get('Contents', []):
                stats['output_files']['count'] += 1
                stats['output_files']['total_bytes'] += obj.get('Size', 0)

        return stats
