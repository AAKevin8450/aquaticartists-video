"""
Manually fetch and process batch job results from S3.
"""
import boto3
import json
import os
from dotenv import load_dotenv
from app.database import get_db
from app.services.nova_service import fetch_batch_results

load_dotenv()

# Get batch job details from database
db = get_db()
with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, batch_job_arn, output_s3_prefix, nova_job_ids, model
        FROM bedrock_batch_jobs
        WHERE status != 'Completed'
        LIMIT 1
    ''')
    batch_job = cursor.fetchone()

    if not batch_job:
        print("No pending batch jobs found!")
        print("\nChecking if there are any batch jobs at all...")
        cursor.execute('SELECT id, status FROM bedrock_batch_jobs')
        all_jobs = cursor.fetchall()
        for job in all_jobs:
            print(f"  Job {job['id']}: {job['status']}")
        exit(0)

print(f"Fetching results for batch job {batch_job['id']}...")
print(f"  ARN: {batch_job['batch_job_arn']}")
print(f"  Output prefix: {batch_job['output_s3_prefix']}")
print(f"  Model: {batch_job['model']}")
print(f"  Nova job IDs: {len(json.loads(batch_job['nova_job_ids']))} jobs")
print()

# Update batch job status to Completed
with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE bedrock_batch_jobs
        SET status = 'Completed', completed_at = datetime('now')
        WHERE id = ?
    ''', (batch_job['id'],))

# Fetch results using the nova_service function
try:
    print("Fetching results from S3...")
    batch_job_arn = batch_job['batch_job_arn']
    output_s3_prefix = batch_job['output_s3_prefix']
    nova_job_ids = json.loads(batch_job['nova_job_ids'])
    model = batch_job['model']

    results = fetch_batch_results(
        batch_job_arn=batch_job_arn,
        output_s3_prefix=output_s3_prefix,
        nova_job_ids=nova_job_ids,
        model=model
    )

    print(f"\nResults fetched successfully!")
    print(f"  Processed {len(results)} jobs")

    # Show summary
    total_tokens_input = 0
    total_tokens_output = 0
    total_cost = 0

    for result in results:
        total_tokens_input += result.get('tokens_input', 0)
        total_tokens_output += result.get('tokens_output', 0)
        total_cost += result.get('cost_usd', 0)

    print(f"\nSummary:")
    print(f"  Total input tokens: {total_tokens_input:,}")
    print(f"  Total output tokens: {total_tokens_output:,}")
    print(f"  Total cost: ${total_cost:.6f}")

except Exception as e:
    print(f"\nError fetching results: {e}")
    import traceback
    traceback.print_exc()
