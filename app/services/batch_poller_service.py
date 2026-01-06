"""
Background service for polling Bedrock batch jobs and processing completed ones.

This service runs in a background thread and:
1. Polls pending Bedrock batch jobs every 60 seconds
2. Fetches results automatically when jobs complete
3. Cleans up S3 files after successful result storage
"""
import logging
import threading
import time
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class BatchPollerService:
    """Background service for polling Bedrock batch jobs."""

    def __init__(self, app):
        """
        Initialize the batch poller service.

        Args:
            app: Flask application instance
        """
        self.app = app
        self.running = False
        self.thread = None

        # Configuration from environment variables
        self.enabled = os.getenv('BATCH_POLLER_ENABLED', 'true').lower() == 'true'
        self.poll_interval = int(os.getenv('BATCH_POLLER_INTERVAL', '60'))
        self.batch_check_interval = int(os.getenv('BATCH_CHECK_INTERVAL', '30'))
        self.auto_cleanup = os.getenv('BATCH_AUTO_CLEANUP', 'true').lower() == 'true'
        self.max_retries = int(os.getenv('BATCH_RESULT_FETCH_MAX_RETRIES', '3'))

        # Stats tracking
        self.stats = {
            'polls_count': 0,
            'jobs_checked': 0,
            'jobs_completed': 0,
            'jobs_failed': 0,
            'results_fetched': 0,
            'cleanups_performed': 0,
            'last_poll_time': None,
            'errors': []
        }

    def start(self):
        """Start the background poller thread."""
        if not self.enabled:
            logger.info("Batch poller is disabled (BATCH_POLLER_ENABLED=false)")
            return

        if self.running:
            logger.warning("Batch poller is already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        logger.info(
            f"Batch poller started (interval={self.poll_interval}s, "
            f"check_interval={self.batch_check_interval}s, auto_cleanup={self.auto_cleanup})"
        )

    def stop(self):
        """Stop the background poller gracefully."""
        if not self.running:
            return

        logger.info("Stopping batch poller...")
        self.running = False

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

        logger.info("Batch poller stopped")

    def get_stats(self) -> Dict[str, Any]:
        """Get current poller statistics."""
        return {
            **self.stats,
            'running': self.running,
            'enabled': self.enabled,
            'poll_interval': self.poll_interval,
            'batch_check_interval': self.batch_check_interval,
            'auto_cleanup': self.auto_cleanup,
        }

    def _poll_loop(self):
        """Main polling loop - runs in background thread."""
        logger.info("Batch poller loop started")

        # On startup, check for orphaned jobs (completed while app was down)
        try:
            self._check_orphaned_jobs()
        except Exception as e:
            logger.error(f"Error checking orphaned jobs on startup: {e}", exc_info=True)

        while self.running:
            try:
                self._poll_cycle()
            except Exception as e:
                logger.error(f"Error in poll cycle: {e}", exc_info=True)
                self.stats['errors'].append({
                    'time': datetime.utcnow().isoformat(),
                    'error': str(e)
                })
                # Keep only last 10 errors
                self.stats['errors'] = self.stats['errors'][-10:]

            # Sleep in small increments to allow faster shutdown
            for _ in range(self.poll_interval):
                if not self.running:
                    break
                time.sleep(1)

        logger.info("Batch poller loop exited")

    def _poll_cycle(self):
        """Execute one poll cycle."""
        with self.app.app_context():
            from app.database import get_db

            db = get_db()
            self.stats['polls_count'] += 1
            self.stats['last_poll_time'] = datetime.utcnow().isoformat()

            # Get pending jobs
            pending_jobs = db.get_pending_batch_jobs_for_polling(self.batch_check_interval)

            if not pending_jobs:
                logger.debug(f"No pending batch jobs to check (poll #{self.stats['polls_count']})")
                return

            logger.info(f"Checking {len(pending_jobs)} pending batch jobs")

            for job in pending_jobs:
                if not self.running:
                    break

                try:
                    self._check_and_process_job(job)
                    self.stats['jobs_checked'] += 1
                except Exception as e:
                    logger.error(
                        f"Error processing job {job.get('batch_job_arn')}: {e}",
                        exc_info=True
                    )

    def _check_orphaned_jobs(self):
        """Check for jobs that may have completed while app was down."""
        logger.info("Checking for orphaned batch jobs from previous session...")

        with self.app.app_context():
            from app.database import get_db

            db = get_db()

            # Get all non-terminal jobs (IN_PROGRESS or SUBMITTED)
            pending_jobs = db.get_pending_bedrock_batch_jobs()

            if not pending_jobs:
                logger.info("No orphaned jobs found")
                return

            logger.info(f"Found {len(pending_jobs)} potentially orphaned jobs, checking status...")

            for job in pending_jobs:
                try:
                    self._check_and_process_job(job)
                except Exception as e:
                    logger.error(
                        f"Error checking orphaned job {job.get('batch_job_arn')}: {e}",
                        exc_info=True
                    )

    def _check_and_process_job(self, batch_job: Dict[str, Any]) -> bool:
        """
        Check single job status and process if completed.

        Args:
            batch_job: Batch job record from database

        Returns:
            True if job was processed successfully, False otherwise
        """
        from app.database import get_db
        from app.services.nova_service import NovaVideoService
        import boto3

        db = get_db()
        batch_job_arn = batch_job['batch_job_arn']

        try:
            # Initialize Bedrock client
            bedrock = boto3.client('bedrock', region_name=os.getenv('AWS_REGION', 'us-east-1'))

            # Check job status
            response = bedrock.get_model_invocation_job(jobIdentifier=batch_job_arn)
            bedrock_status = response.get('status')

            logger.debug(f"Job {batch_job_arn}: Bedrock status = {bedrock_status}")

            # Update last_checked_at
            db.mark_bedrock_batch_checked(batch_job_arn)

            # Map Bedrock status to internal status
            if bedrock_status in ['Submitted', 'Validating', 'Scheduled', 'InProgress']:
                # Still running, update status if needed
                if batch_job['status'] != 'IN_PROGRESS':
                    db.update_bedrock_batch_job(batch_job_arn, {'status': 'IN_PROGRESS'})
                    logger.info(f"Job {batch_job_arn}: Status updated to IN_PROGRESS")
                return False

            elif bedrock_status == 'Completed':
                # Job completed! Fetch results
                logger.info(f"Job {batch_job_arn}: COMPLETED - fetching results")

                success = self._fetch_and_store_results(batch_job)

                if success:
                    self.stats['jobs_completed'] += 1
                    self.stats['results_fetched'] += 1

                    # Mark batch job as completed
                    db.update_bedrock_batch_job(batch_job_arn, {
                        'status': 'COMPLETED',
                        'completed_at': datetime.utcnow().isoformat()
                    })

                    # Trigger cleanup if enabled
                    if self.auto_cleanup and batch_job.get('s3_folder'):
                        cleanup_success = self._cleanup_batch_files(batch_job)
                        if cleanup_success:
                            self.stats['cleanups_performed'] += 1

                    return True
                else:
                    # Result fetching failed - mark for retry or failure
                    return False

            elif bedrock_status in ['Failed', 'Stopped', 'Expired']:
                # Job failed
                logger.warning(f"Job {batch_job_arn}: Failed with status {bedrock_status}")

                failure_message = response.get('message', f"Job {bedrock_status.lower()}")
                db.update_bedrock_batch_job(batch_job_arn, {
                    'status': 'FAILED',
                    'failure_message': failure_message,
                    'completed_at': datetime.utcnow().isoformat()
                })

                # Update linked nova_jobs to FAILED status
                nova_job_ids = batch_job.get('nova_job_ids', [])
                for nova_job_id in nova_job_ids:
                    db.update_nova_job(nova_job_id, {
                        'status': 'FAILED',
                        'batch_status': 'FAILED',
                        'error_message': failure_message
                    })

                self.stats['jobs_failed'] += 1
                return False

            else:
                logger.warning(f"Job {batch_job_arn}: Unknown status {bedrock_status}")
                return False

        except Exception as e:
            # Classify errors
            error_str = str(e)

            if 'ResourceNotFoundException' in error_str:
                # Job doesn't exist in Bedrock - mark as failed
                logger.error(f"Job {batch_job_arn}: Not found in Bedrock, marking as FAILED")
                db.update_bedrock_batch_job(batch_job_arn, {
                    'status': 'FAILED',
                    'failure_message': 'Job not found in Bedrock',
                    'completed_at': datetime.utcnow().isoformat()
                })
                return False

            elif any(x in error_str for x in ['ThrottlingException', 'ServiceUnavailable']):
                # Transient error - will retry next cycle
                logger.warning(f"Job {batch_job_arn}: Transient error, will retry: {error_str}")
                return False

            else:
                # Unknown error - log and continue
                logger.error(f"Job {batch_job_arn}: Error checking status: {e}", exc_info=True)
                db.increment_fetch_attempts(batch_job_arn, error=error_str)
                return False

    def _fetch_and_store_results(self, batch_job: Dict[str, Any]) -> bool:
        """
        Fetch results from S3 and update database.

        Args:
            batch_job: Batch job record from database

        Returns:
            True if results fetched successfully, False otherwise
        """
        from app.database import get_db
        from app.services.nova_service import NovaVideoService
        import boto3

        db = get_db()
        batch_job_arn = batch_job['batch_job_arn']
        nova_job_ids = batch_job.get('nova_job_ids', [])

        if not nova_job_ids:
            logger.warning(f"Job {batch_job_arn}: No nova_job_ids to process")
            return False

        try:
            # Initialize Nova service with required parameters
            bucket_name = os.getenv('S3_BUCKET_NAME')
            region = os.getenv('AWS_REGION', 'us-east-1')
            nova_service = NovaVideoService(bucket_name=bucket_name, region=region)

            # Get S3 output location
            s3_folder = batch_job.get('s3_folder')
            if s3_folder:
                output_s3_prefix = f"nova/batch/output/{s3_folder}/"
            else:
                output_s3_prefix = batch_job.get('output_s3_prefix')

            logger.info(
                f"Job {batch_job_arn}: Fetching results for {len(nova_job_ids)} files "
                f"from {output_s3_prefix}"
            )

            # Process each nova_job
            success_count = 0
            fail_count = 0

            for nova_job_id in nova_job_ids:
                try:
                    # Get nova_job details
                    nova_job = db.get_nova_job(nova_job_id)
                    if not nova_job:
                        logger.error(f"Nova job {nova_job_id} not found")
                        fail_count += 1
                        continue

                    # Skip if already completed
                    if nova_job.get('status') == 'COMPLETED':
                        logger.debug(f"Nova job {nova_job_id} already completed, skipping")
                        success_count += 1
                        continue

                    # Parse options and analysis types
                    import json as json_module

                    # Handle both string and already-parsed values
                    analysis_types = nova_job.get('analysis_types', [])
                    if isinstance(analysis_types, str):
                        analysis_types = json_module.loads(analysis_types)

                    user_options = nova_job.get('user_options', {})
                    if isinstance(user_options, str):
                        user_options = json_module.loads(user_options)

                    # Fetch batch results from S3
                    results = nova_service.fetch_batch_results(
                        s3_prefix=nova_job['batch_output_s3_prefix'],
                        model=nova_job['model'],
                        analysis_types=analysis_types,
                        options=user_options,
                        record_prefix=user_options.get('batch_record_prefix')
                    )

                    # Update nova_job with results
                    update_data = {
                        'status': 'COMPLETED',
                        'progress_percent': 100,
                        'tokens_total': results['totals']['tokens_total'],
                        'processing_time_seconds': results['totals']['processing_time_seconds'],
                        'cost_usd': results['totals']['cost_total_usd'],
                        'batch_status': 'COMPLETED',
                        'completed_at': datetime.utcnow().isoformat()
                    }

                    if 'summary' in results:
                        update_data['summary_result'] = json_module.dumps(results['summary'])
                        update_data['tokens_input'] = results['summary'].get('tokens_input', 0)
                        update_data['tokens_output'] = results['summary'].get('tokens_output', 0)

                    if 'chapters' in results:
                        update_data['chapters_result'] = json_module.dumps(results['chapters'])

                    if 'elements' in results:
                        update_data['elements_result'] = json_module.dumps(results['elements'])

                    if 'waterfall_classification' in results:
                        update_data['waterfall_classification_result'] = json_module.dumps(results['waterfall_classification'])

                    if 'search_metadata' in results:
                        update_data['search_metadata'] = json_module.dumps(results['search_metadata'])

                    db.update_nova_job(nova_job_id, update_data)

                    # Update analysis_job
                    db.update_analysis_job(
                        nova_job['analysis_job_id'],
                        status='COMPLETED',
                        results=results
                    )

                    success_count += 1
                    logger.debug(f"Successfully processed results for nova_job {nova_job_id}")

                except Exception as e:
                    logger.error(
                        f"Error fetching results for nova_job {nova_job_id}: {e}",
                        exc_info=True
                    )
                    # Update job as failed
                    try:
                        db.update_nova_job(nova_job_id, {
                            'status': 'FAILED',
                            'error_message': f'Failed to fetch batch results: {str(e)}',
                            'batch_status': 'RESULT_FETCH_FAILED'
                        })
                        db.update_analysis_job(
                            nova_job.get('analysis_job_id') if 'nova_job' in locals() and nova_job else None,
                            status='FAILED',
                            error_message=f'Failed to fetch batch results: {str(e)}'
                        )
                    except Exception as update_error:
                        logger.error(f"Failed to update job status: {update_error}")
                    fail_count += 1

            logger.info(
                f"Job {batch_job_arn}: Results fetched - "
                f"{success_count} succeeded, {fail_count} failed"
            )

            # Mark results as fetched
            db.mark_results_fetched(batch_job_arn)

            # Return True if all succeeded
            return fail_count == 0

        except Exception as e:
            logger.error(f"Job {batch_job_arn}: Error fetching results: {e}", exc_info=True)
            db.increment_fetch_attempts(batch_job_arn, error=str(e))

            # Check if max retries exceeded
            attempts = batch_job.get('results_fetch_attempts', 0) + 1
            if attempts >= self.max_retries:
                logger.error(
                    f"Job {batch_job_arn}: Max retries ({self.max_retries}) exceeded, "
                    "marking as RESULT_FETCH_FAILED"
                )
                db.update_bedrock_batch_job(batch_job_arn, {
                    'status': 'RESULT_FETCH_FAILED'
                })

            return False

    def _cleanup_batch_files(self, batch_job: Dict[str, Any]) -> bool:
        """
        Delete S3 batch files after successful result storage.

        Args:
            batch_job: Batch job record from database

        Returns:
            True if cleanup successful, False otherwise
        """
        from app.database import get_db
        from app.services.batch_s3_manager import BatchS3Manager
        import boto3

        db = get_db()
        batch_job_arn = batch_job['batch_job_arn']
        s3_folder = batch_job.get('s3_folder')

        if not s3_folder:
            logger.debug(f"Job {batch_job_arn}: No s3_folder, skipping cleanup")
            return False

        try:
            # Initialize S3 manager
            s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
            bucket_name = os.getenv('S3_BUCKET_NAME')
            s3_manager = BatchS3Manager(s3_client, bucket_name)

            # Cleanup batch folder
            stats = s3_manager.cleanup_batch_folder(s3_folder)

            logger.info(
                f"Job {batch_job_arn}: Cleanup completed - "
                f"{stats['objects_deleted']} objects, "
                f"{stats['bytes_freed'] / 1024 / 1024:.2f} MB freed"
            )

            # Mark cleanup complete
            job_id = batch_job['id']
            db.mark_batch_job_cleaned(job_id)

            return True

        except Exception as e:
            logger.error(f"Job {batch_job_arn}: Cleanup failed: {e}", exc_info=True)
            # Don't fail the job if cleanup fails - can be retried manually
            return False
