"""
Backfill script to populate analysis_jobs.results for existing image Nova jobs.

This script fixes the issue where image analysis data was stored in nova_jobs table
but not compiled into analysis_jobs.results for dashboard display.
"""
import sys
import os
import json
import sqlite3
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import get_db


def backfill_image_analysis_results(dry_run=True, limit=None):
    """
    Backfill analysis_jobs.results for completed image Nova jobs.

    Args:
        dry_run: If True, only show what would be updated without making changes
        limit: Maximum number of jobs to process (None = all)
    """
    db = get_db()

    # Query for image Nova jobs that need backfilling
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find completed image jobs where analysis_jobs.results is NULL
        query = """
            SELECT
                nj.id as nova_job_id,
                nj.analysis_job_id,
                nj.model,
                nj.analysis_types,
                nj.tokens_input,
                nj.tokens_output,
                nj.tokens_total,
                nj.cost_usd,
                nj.processing_time_seconds,
                nj.description_result,
                nj.elements_result,
                nj.waterfall_classification_result,
                nj.search_metadata,
                aj.job_id
            FROM nova_jobs nj
            JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id
            WHERE nj.content_type = 'image'
              AND nj.status = 'COMPLETED'
              AND aj.results IS NULL
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        jobs = cursor.fetchall()

    total_jobs = len(jobs)
    print(f"\n{'=' * 80}")
    print(f"Found {total_jobs} image analysis jobs to backfill")
    print(f"Mode: {'DRY RUN (no changes will be made)' if dry_run else 'LIVE (changes will be saved)'}")
    print(f"{'=' * 80}\n")

    if total_jobs == 0:
        print("No jobs to backfill. Exiting.")
        return

    if not dry_run:
        confirm = input(f"\nAre you sure you want to update {total_jobs} jobs? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Aborted.")
            return

    updated_count = 0
    error_count = 0

    for idx, job in enumerate(jobs, 1):
        try:
            # Parse JSON fields
            analysis_types = json.loads(job['analysis_types']) if job['analysis_types'] else []
            description = json.loads(job['description_result']) if job['description_result'] else None
            elements = json.loads(job['elements_result']) if job['elements_result'] else None
            waterfall = json.loads(job['waterfall_classification_result']) if job['waterfall_classification_result'] else None
            metadata = json.loads(job['search_metadata']) if job['search_metadata'] else None

            # Compile results (matching the format from nova_image_analysis.py)
            compiled_results = {
                'content_type': 'image',
                'model': job['model'],
                'analysis_types': analysis_types,
                'totals': {
                    'tokens_total': job['tokens_total'] or 0,
                    'cost_total_usd': job['cost_usd'] or 0.0,
                    'processing_time_seconds': job['processing_time_seconds'] or 0.0
                }
            }

            # Add analysis results
            if description:
                compiled_results['description'] = description
            if elements:
                compiled_results['elements'] = elements
            if waterfall:
                compiled_results['waterfall_classification'] = waterfall
            if metadata:
                compiled_results['metadata'] = metadata

            # Show preview
            if idx <= 3 or dry_run:
                print(f"\nJob {idx}/{total_jobs}: {job['job_id']}")
                print(f"  Nova Job ID: {job['nova_job_id']}")
                print(f"  Analysis Job ID: {job['analysis_job_id']}")
                print(f"  Model: {job['model']}")
                print(f"  Analysis Types: {', '.join(analysis_types)}")
                print(f"  Has description: {description is not None}")
                print(f"  Has elements: {elements is not None}")
                print(f"  Has waterfall: {waterfall is not None}")
                print(f"  Has metadata: {metadata is not None}")
                print(f"  Tokens: {job['tokens_total']}")
                print(f"  Cost: ${job['cost_usd']:.6f}" if job['cost_usd'] else "  Cost: N/A")

            if not dry_run:
                # Update analysis_jobs.results
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE analysis_jobs SET results = ? WHERE id = ?",
                        (json.dumps(compiled_results), job['analysis_job_id'])
                    )

            updated_count += 1

            # Progress indicator
            if idx % 100 == 0:
                print(f"\nProcessed {idx}/{total_jobs} jobs...")

        except Exception as e:
            error_count += 1
            print(f"\nERROR processing job {job['job_id']} (nova_job_id={job['nova_job_id']}): {e}")
            continue

    print(f"\n{'=' * 80}")
    print(f"SUMMARY:")
    print(f"  Total jobs processed: {total_jobs}")
    print(f"  Successfully updated: {updated_count}")
    print(f"  Errors: {error_count}")
    print(f"  Mode: {'DRY RUN (no changes made)' if dry_run else 'LIVE (changes saved)'}")
    print(f"{'=' * 80}\n")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Backfill analysis_jobs.results for image Nova jobs'
    )
    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Actually update the database (default is dry run)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of jobs to process'
    )

    args = parser.parse_args()

    backfill_image_analysis_results(
        dry_run=not args.no_dry_run,
        limit=args.limit
    )
