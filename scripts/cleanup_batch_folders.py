#!/usr/bin/env python
"""
Script to clean up S3 folders from completed batch jobs.

This script cleans up the isolated S3 folders created by the multi-chunk batch
processing architecture. It removes:
- nova_batch/job_TIMESTAMP_NNN/* (copied proxy files with sanitized names)
- nova/batch/output/nova_batch/job_TIMESTAMP_NNN/* (batch output results)

Only cleans jobs that:
1. Have status = 'COMPLETED'
2. Have s3_folder set (new multi-job format)
3. Haven't been cleaned up yet (cleanup_completed_at IS NULL)

Usage:
    # Preview what would be deleted (dry-run mode)
    python -m scripts.cleanup_batch_folders

    # Actually delete files
    python -m scripts.cleanup_batch_folders --no-dry-run

Examples:
    python -m scripts.cleanup_batch_folders --dry-run
    python -m scripts.cleanup_batch_folders --no-dry-run
"""
import argparse
import sys
import os
import logging

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.database import get_db
from app.services.batch_cleanup_service import BatchCleanupService
from app.services.batch_s3_manager import BatchS3Manager
import boto3

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Clean up S3 folders from completed Nova batch jobs'
    )
    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Actually delete files (default is dry-run mode)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='Preview what would be deleted without deleting (default)'
    )
    args = parser.parse_args()

    # --no-dry-run overrides --dry-run
    dry_run = not args.no_dry_run

    app = create_app()
    with app.app_context():
        db = get_db()

        # Initialize S3 client
        s3_client = boto3.client(
            's3',
            region_name=app.config['AWS_REGION'],
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        bucket_name = app.config['S3_BUCKET_NAME']

        # Initialize BatchS3Manager for cleanup
        batch_s3_manager = BatchS3Manager(s3_client, bucket_name)

        # Initialize cleanup service
        cleanup_service = BatchCleanupService(
            s3_client=s3_client,
            bucket_name=bucket_name,
            db=db,
            batch_s3_manager=batch_s3_manager
        )

        # Print header
        print()
        print("=" * 60)
        if dry_run:
            print("DRY RUN - No files will be deleted")
        else:
            print("LIVE MODE - Files will be permanently deleted")
        print("=" * 60)
        print()

        # Run cleanup
        stats = cleanup_service.cleanup_completed_batch_jobs(dry_run=dry_run)

        # Print results
        print()
        print("=" * 60)
        print("CLEANUP SUMMARY")
        print("=" * 60)
        print(f"Jobs processed:   {stats['jobs_processed']}")
        print(f"Jobs cleaned:     {stats['jobs_cleaned']}")
        print(f"Objects deleted:  {stats['objects_deleted']}")
        print(f"Space freed:      {stats['bytes_freed'] / 1024 / 1024:.2f} MB")

        if stats['errors']:
            print()
            print("ERRORS:")
            for error in stats['errors']:
                print(f"  - {error}")

        print("=" * 60)
        print()

        if dry_run and stats['jobs_cleaned'] > 0:
            print("To actually delete these files, run with --no-dry-run")
            print()


if __name__ == '__main__':
    main()
