"""Check status of all batch jobs from AWS."""
import boto3
import os
from dotenv import load_dotenv
from app.database import get_db
import json

load_dotenv()

bedrock = boto3.client(
    'bedrock',
    region_name='us-east-1',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

db = get_db()
with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT batch_job_arn, job_name FROM bedrock_batch_jobs ORDER BY submitted_at DESC')
    jobs = cursor.fetchall()

print(f"Checking {len(jobs)} batch jobs from AWS...\n")
print("=" * 100)

for job in jobs:
    arn = job['batch_job_arn']
    name = job['job_name']

    try:
        response = bedrock.get_model_invocation_job(jobIdentifier=arn)

        status = response['status']
        submit_time = response.get('submitTime', 'N/A')
        end_time = response.get('endTime', 'N/A')

        print(f"\nJob: {name}")
        print(f"  ARN: {arn}")
        print(f"  Status: {status}")
        print(f"  Submitted: {submit_time}")

        if end_time != 'N/A':
            print(f"  Ended: {end_time}")

        if status == 'Completed':
            print(f"  ✓ COMPLETED - Ready to fetch results")

            # Check if there are output files
            output_uri = response['outputDataConfig']['s3OutputDataConfig']['s3Uri']
            print(f"  Output URI: {output_uri}")

        elif status == 'Failed':
            print(f"  ✗ FAILED")
            if 'message' in response:
                print(f"  Error: {response['message']}")

        elif status in ('InProgress', 'Submitted', 'Validating'):
            print(f"  ⏳ Still processing...")

    except Exception as e:
        print(f"\nJob: {name}")
        print(f"  ARN: {arn}")
        print(f"  ERROR: {e}")

print("\n" + "=" * 100)
