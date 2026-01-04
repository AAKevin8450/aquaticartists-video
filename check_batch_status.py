"""
Check AWS Bedrock batch job status directly.
"""
import boto3
import os
from dotenv import load_dotenv
from app.database import get_db

load_dotenv()

# Initialize Bedrock client
bedrock = boto3.client(
    'bedrock',
    region_name=os.getenv('AWS_REGION', 'us-east-1'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

# Get batch job ARN from database
db = get_db()
with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT batch_job_arn, job_name, submitted_at FROM bedrock_batch_jobs LIMIT 1')
    row = cursor.fetchone()

    if not row:
        print("No batch jobs found in database!")
        exit(1)

    batch_job_arn = row['batch_job_arn']
    job_name = row['job_name']
    submitted_at = row['submitted_at']

print(f"Checking batch job status...")
print(f"  Job: {job_name}")
print(f"  ARN: {batch_job_arn}")
print(f"  Submitted: {submitted_at}")
print()

try:
    # Check job status
    response = bedrock.get_model_invocation_job(
        jobIdentifier=batch_job_arn
    )

    print("Batch Job Status from AWS:")
    print("=" * 80)
    print(f"  Status: {response['status']}")
    print(f"  Job ARN: {response['jobArn']}")
    print(f"  Job Name: {response['jobName']}")
    print(f"  Model ID: {response['modelId']}")
    print(f"  Submit Time: {response['submitTime']}")

    if 'endTime' in response:
        print(f"  End Time: {response['endTime']}")

    if 'lastModifiedTime' in response:
        print(f"  Last Modified: {response['lastModifiedTime']}")

    # Input/output data config
    print(f"\n  Input S3 URI: {response['inputDataConfig']['s3InputDataConfig']['s3Uri']}")
    print(f"  Output S3 URI: {response['outputDataConfig']['s3OutputDataConfig']['s3Uri']}")

    # Check if there are any metrics
    if 'invocationModelSummary' in response:
        print(f"\n  Invocation Summary:")
        summary = response['invocationModelSummary']
        if 'inputTokenCount' in summary:
            print(f"    Input Tokens: {summary['inputTokenCount']:,}")
        if 'outputTokenCount' in summary:
            print(f"    Output Tokens: {summary['outputTokenCount']:,}")
        if 'invocationCount' in summary:
            print(f"    Invocations: {summary['invocationCount']:,}")

    print("\n" + "=" * 80)

    if response['status'] == 'Completed':
        print("\n✓ Batch job has COMPLETED!")
        print("\nNext steps:")
        print("  1. The app needs to fetch results from S3")
        print("  2. You can trigger this by visiting the Nova Analysis page")
        print("  3. Or hit the endpoint: GET /api/nova/batch/pending")
    elif response['status'] == 'InProgress':
        print("\n⏳ Batch job is still IN PROGRESS")
    elif response['status'] == 'Failed':
        print("\n✗ Batch job FAILED!")
        if 'failureMessage' in response:
            print(f"  Error: {response['failureMessage']}")
    else:
        print(f"\n Status: {response['status']}")

except Exception as e:
    print(f"\nError checking batch job status: {e}")
    import traceback
    traceback.print_exc()
