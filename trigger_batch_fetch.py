"""
Trigger batch result fetching by checking status and fetching results.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add app to path
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.database import get_db
import json

# Create Flask app context
app = create_app()

with app.app_context():
    from app.routes.nova_analysis import get_nova_service, check_bedrock_batch_status

    db = get_db()

    # Get the batch job
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT batch_job_arn, nova_job_ids
            FROM bedrock_batch_jobs
            WHERE status != 'Completed'
            LIMIT 1
        ''')
        batch_job = cursor.fetchone()

        if not batch_job:
            print("No pending batch jobs found!")
            sys.exit(0)

    batch_job_arn = batch_job['batch_job_arn']
    nova_job_ids = json.loads(batch_job['nova_job_ids'])

    print(f"Checking batch job: {batch_job_arn}")
    print(f"  Nova jobs: {len(nova_job_ids)}")

    # Check status from AWS
    status = check_bedrock_batch_status(batch_job_arn)
    print(f"\nBatch status: {status}")

    if status['status'] in ('Completed', 'COMPLETED'):
        print("\nBatch job completed! Fetching results for all jobs...")

        # Update bedrock_batch_jobs status
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE bedrock_batch_jobs
                SET status = 'Completed'
                WHERE batch_job_arn = ?
            ''', (batch_job_arn,))

        # Process each nova job
        success_count = 0
        error_count = 0

        for i, nova_job_id in enumerate(nova_job_ids):
            try:
                # Get the job details
                job = db.get_nova_job(nova_job_id)
                if not job:
                    print(f"Job {nova_job_id}: NOT FOUND")
                    error_count += 1
                    continue

                # Fetch results
                nova_service = get_nova_service()
                options = json.loads(job.get('user_options') or '{}')
                analysis_types = json.loads(job.get('analysis_types') or '[]')

                results = nova_service.fetch_batch_results(
                    s3_prefix=job.get('batch_output_s3_prefix', ''),
                    model=job['model'],
                    analysis_types=analysis_types,
                    options=options,
                    record_prefix=options.get('batch_record_prefix')
                )

                # Update job with results
                update_data = {
                    'status': 'COMPLETED',
                    'batch_status': 'Completed',
                    'completed_at': 'datetime("now")',
                }

                # Add result fields
                if 'summary' in results:
                    update_data['summary_result'] = results['summary']
                if 'chapters' in results:
                    update_data['chapters_result'] = results['chapters']
                if 'elements' in results:
                    update_data['elements_result'] = results['elements']
                if 'waterfall_classification' in results:
                    update_data['waterfall_classification_result'] = results['waterfall_classification']
                if 'search_metadata' in results:
                    update_data['search_metadata'] = results['search_metadata']

                # Add token and cost data
                if 'totals' in results:
                    totals = results['totals']
                    update_data['tokens_input'] = totals.get('tokens_input', 0)
                    update_data['tokens_output'] = totals.get('tokens_output', 0)
                    update_data['tokens_total'] = totals.get('tokens_total', 0)
                    update_data['cost_usd'] = totals.get('cost_total_usd', 0)
                    update_data['processing_time_seconds'] = totals.get('processing_time_seconds', 0)

                db.update_nova_job(nova_job_id, update_data)

                # Also update analysis_job
                db.update_analysis_job(
                    job['analysis_job_id'],
                    status='COMPLETED',
                    results=results
                )

                success_count += 1
                if (i + 1) % 10 == 0:
                    print(f"  Processed {i + 1}/{len(nova_job_ids)} jobs...")

            except Exception as e:
                print(f"Job {nova_job_id}: ERROR - {e}")
                error_count += 1
                continue

        print(f"\nResults:")
        print(f"  Success: {success_count}")
        print(f"  Errors: {error_count}")
        print(f"  Total: {len(nova_job_ids)}")

        # Now run the cost analysis
        print("\n" + "=" * 80)
        print("Running cost analysis...")
        print("=" * 80)

        os.system(f'{sys.executable} check_batch_jobs.py')
    else:
        print(f"\nBatch job not completed yet. Status: {status['status']}")
