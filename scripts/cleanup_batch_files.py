#!/usr/bin/env python
"""Script to clean up old batch processing files from S3."""
import argparse
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.database import get_db
from app.services.batch_cleanup_service import BatchCleanupService
import boto3


def main():
    parser = argparse.ArgumentParser(description='Clean up old Nova batch files from S3')
    parser.add_argument('--days', type=int, default=7,
                        help='Delete files older than this many days (default: 7)')
    parser.add_argument('--no-dry-run', action='store_true',
                        help='Actually delete files (default is dry-run mode)')
    parser.add_argument('--stats', action='store_true',
                        help='Only show storage statistics, do not delete')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db = get_db()

        s3_client = boto3.client(
            's3',
            region_name=app.config['AWS_REGION'],
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )

        cleanup_service = BatchCleanupService(
            s3_client=s3_client,
            bucket_name=app.config['S3_BUCKET_NAME'],
            db=db
        )

        if args.stats:
            print("\n=== Batch Storage Statistics ===")
            stats = cleanup_service.get_batch_storage_stats()
            print(f"Input files:  {stats['input_files']['count']} files, "
                  f"{stats['input_files']['total_bytes'] / 1024 / 1024:.2f} MB")
            print(f"Output files: {stats['output_files']['count']} files, "
                  f"{stats['output_files']['total_bytes'] / 1024 / 1024:.2f} MB")
            return

        dry_run = not args.no_dry_run

        print(f"\n=== Batch File Cleanup ===")
        print(f"Mode: {'DRY RUN' if dry_run else 'LIVE DELETE'}")
        print(f"Cleaning files older than {args.days} days\n")

        results = cleanup_service.cleanup_old_batch_files(
            days_old=args.days,
            dry_run=dry_run
        )

        print(f"\nResults:")
        print(f"  Jobs processed: {results['jobs_processed']}")
        print(f"  Input files {'would be ' if dry_run else ''}deleted: {results['input_files_deleted']}")
        print(f"  Output files {'would be ' if dry_run else ''}deleted: {results['output_files_deleted']}")

        if results['errors']:
            print(f"\nErrors ({len(results['errors'])}):")
            for error in results['errors']:
                print(f"  - {error}")


if __name__ == '__main__':
    main()
