"""
Process batch results for batch job b4phxso20xjs
"""
import json
import sys
from datetime import datetime, timezone
from app.database import get_db
from app.services.nova_service import NovaVideoService
from dotenv import load_dotenv
import os

load_dotenv()

# Initialize database and service
db = get_db()
bucket_name = os.getenv('S3_BUCKET_NAME')
region = os.getenv('AWS_REGION', 'us-east-1')
nova_service = NovaVideoService(bucket_name=bucket_name, region=region)

# Get batch job details
batch_job_arn = 'arn:aws:bedrock:us-east-1:676206912644:model-invocation-job/b4phxso20xjs'

with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM bedrock_batch_jobs WHERE batch_job_arn = ?
    ''', (batch_job_arn,))
    batch_job = cursor.fetchone()

    if not batch_job:
        print(f"Batch job not found: {batch_job_arn}")
        sys.exit(1)

print("=" * 80)
print("BATCH JOB DETAILS")
print("=" * 80)
print(f"ARN: {batch_job['batch_job_arn']}")
print(f"Status: {batch_job['status']}")
print(f"Model: {batch_job['model']}")
print(f"Output S3 Prefix: {batch_job['output_s3_prefix']}")
nova_job_ids = eval(batch_job['nova_job_ids'])
print(f"Total Jobs: {len(nova_job_ids)}")
print()

# Mark batch as completed if not already
if batch_job['completed_at'] is None:
    db.update_bedrock_batch_job(batch_job_arn, {
        'status': 'COMPLETED',
        'completed_at': datetime.now(timezone.utc).isoformat()
    })
    print("[OK] Marked batch job as COMPLETED")

print(f"\nProcessing {len(nova_job_ids)} jobs...")
print("=" * 80)

success_count = 0
fail_count = 0
total_cost = 0.0
total_tokens_input = 0
total_tokens_output = 0

for i, nova_job_id in enumerate(nova_job_ids, 1):
    # Get nova job details
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM nova_jobs WHERE id = ?', (nova_job_id,))
        job = cursor.fetchone()

    if not job:
        print(f"[{i}/{len(nova_job_ids)}] Nova job {nova_job_id} not found - SKIP")
        fail_count += 1
        continue

    # Skip if already completed
    if job['batch_status'] == 'COMPLETED':
        print(f"[{i}/{len(nova_job_ids)}] Job {nova_job_id} already completed - SKIP")
        success_count += 1
        continue

    # Parse options
    try:
        options = json.loads(job['user_options']) if job['user_options'] else {}
        analysis_types = json.loads(job['analysis_types']) if job['analysis_types'] else []

        # Fetch results from S3
        try:
            results = nova_service.fetch_batch_results(
                s3_prefix=job['batch_output_s3_prefix'],
                model=job['model'],
                analysis_types=analysis_types,
                options=options,
                record_prefix=options.get('batch_record_prefix')
            )

            # Update nova job with results
            update_data = {
                'status': 'COMPLETED',
                'progress_percent': 100,
                'tokens_total': results['totals']['tokens_total'],
                'processing_time_seconds': results['totals']['processing_time_seconds'],
                'cost_usd': results['totals']['cost_total_usd'],
                'batch_status': 'COMPLETED',
                'completed_at': datetime.now(timezone.utc).isoformat()
            }

            if 'summary' in results:
                update_data['summary_result'] = json.dumps(results['summary'])
                update_data['tokens_input'] = results['summary'].get('tokens_input', 0)
                update_data['tokens_output'] = results['summary'].get('tokens_output', 0)

            if 'chapters' in results:
                update_data['chapters_result'] = json.dumps(results['chapters'])

            if 'elements' in results:
                update_data['elements_result'] = json.dumps(results['elements'])

            if 'waterfall_classification' in results:
                update_data['waterfall_classification_result'] = json.dumps(results['waterfall_classification'])

            if 'search_metadata' in results:
                update_data['search_metadata'] = json.dumps(results['search_metadata'])

            db.update_nova_job(nova_job_id, update_data)

            # Update analysis job
            db.update_analysis_job(
                job['analysis_job_id'],
                status='COMPLETED',
                results=results
            )

            total_cost += results['totals'].get('cost_total_usd', 0)
            total_tokens_input += results.get('summary', {}).get('tokens_input', 0)
            total_tokens_output += results.get('summary', {}).get('tokens_output', 0)

            success_count += 1
            if i % 10 == 0:
                print(f"[{i}/{len(nova_job_ids)}] Processed {success_count} jobs, ${total_cost:.4f} total")

        except Exception as e:
            print(f"[{i}/{len(nova_job_ids)}] Job {nova_job_id} failed to fetch results: {e}")
            db.update_nova_job(nova_job_id, {
                'status': 'FAILED',
                'error_message': f'Failed to fetch batch results: {str(e)}',
                'batch_status': 'RESULT_FETCH_FAILED'
            })
            db.update_analysis_job(
                job['analysis_job_id'],
                status='FAILED',
                error_message=f'Failed to fetch batch results: {str(e)}'
            )
            fail_count += 1

    except Exception as e:
        print(f"[{i}/{len(nova_job_ids)}] Job {nova_job_id} processing error: {e}")
        fail_count += 1

print()
print("=" * 80)
print("PROCESSING COMPLETE")
print("=" * 80)
print(f"Success: {success_count}/{len(nova_job_ids)}")
print(f"Failed: {fail_count}/{len(nova_job_ids)}")
print(f"\nTotal Tokens Input: {total_tokens_input:,}")
print(f"Total Tokens Output: {total_tokens_output:,}")
print(f"Total Cost: ${total_cost:.4f}")
print()

# Calculate savings (50% discount for batch vs on-demand)
on_demand_cost = total_cost * 2  # Batch is ~50% cheaper
savings = on_demand_cost - total_cost
print(f"On-Demand Cost (estimated): ${on_demand_cost:.4f}")
print(f"Batch Cost (actual): ${total_cost:.4f}")
print(f"Savings (50% discount): ${savings:.4f}")
