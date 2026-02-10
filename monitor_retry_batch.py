"""
Monitor the retry batch job status
"""
import time
import boto3
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

batch_job_arn = 'arn:aws:bedrock:us-east-1:676206912644:model-invocation-job/116hga8twyjp'

bedrock = boto3.client(
    'bedrock',
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)

print("=" * 80)
print("MONITORING BATCH RETRY JOB")
print("=" * 80)
print(f"Job ARN: {batch_job_arn}")
print()

while True:
    try:
        response = bedrock.get_model_invocation_job(jobIdentifier=batch_job_arn)

        status = response['status']
        job_name = response['jobName']
        submit_time = response['submitTime']
        last_modified = response.get('lastModifiedTime', submit_time)

        # Calculate elapsed time
        if isinstance(submit_time, datetime):
            elapsed = datetime.now(submit_time.tzinfo) - submit_time
            elapsed_mins = elapsed.total_seconds() / 60
        else:
            elapsed_mins = 0

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Status: {status}")
        print(f"  Job: {job_name}")
        print(f"  Elapsed: {elapsed_mins:.1f} minutes")
        print(f"  Last Modified: {last_modified}")

        if status in ('Completed', 'Failed', 'Stopped'):
            print()
            print("=" * 80)
            if status == 'Completed':
                print("BATCH JOB COMPLETED!")
                print()
                print("Next steps:")
                print("  1. Run: python -m scripts.process_batch_simple")
                print("  2. Or the results will auto-fetch when you view the videos in the UI")
            else:
                print(f"BATCH JOB {status.upper()}!")
                if 'message' in response:
                    print(f"Message: {response['message']}")
            print("=" * 80)
            break

        # Wait 30 seconds before next check
        time.sleep(30)

    except KeyboardInterrupt:
        print()
        print("Monitoring stopped by user")
        break
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
