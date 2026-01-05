"""
Create a batch job to retry the 35 failed videos from the previous batch
"""
import json
import os
import sys
import sqlite3
from datetime import datetime, timezone
from dotenv import load_dotenv

from app.database import get_db
from app.services.nova_service import NovaVideoService

load_dotenv()

# Failed file IDs from previous analysis
FAILED_FILE_IDS = [
    22153, 3010, 2985, 2984, 2795, 2792, 2791, 2788, 2689, 2685,
    2682, 2679, 2675, 2673, 2667, 2656, 2646, 2641, 2332, 2314,
    2313, 2309, 2298, 1404, 757, 756, 595, 591, 588, 583,
    484, 483, 482, 481, 478
]

print("=" * 80)
print("BATCH RETRY FOR 35 FAILED VIDEOS")
print("=" * 80)
print()

# Initialize services
db = get_db()
bucket_name = os.getenv('S3_BUCKET_NAME')
region = os.getenv('AWS_REGION', 'us-east-1')
role_arn = os.getenv('BEDROCK_BATCH_ROLE_ARN')

if not role_arn:
    print("ERROR: BEDROCK_BATCH_ROLE_ARN not set in environment")
    sys.exit(1)

nova_service = NovaVideoService(bucket_name=bucket_name, region=region)

# Get file and proxy information
print(f"Loading information for {len(FAILED_FILE_IDS)} files...")

conn = sqlite3.connect('data/app.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

placeholders = ','.join('?' * len(FAILED_FILE_IDS))
cursor.execute(f'''
    SELECT
        f.id,
        f.filename,
        proxy.s3_key as proxy_s3_key,
        proxy.id as proxy_id
    FROM files f
    LEFT JOIN files proxy ON proxy.source_file_id = f.id AND proxy.is_proxy = 1
    WHERE f.id IN ({placeholders})
    ORDER BY f.id
''', FAILED_FILE_IDS)

files_data = []
missing_proxies = []

for row in cursor.fetchall():
    file_id = row['id']
    proxy_s3_key = row['proxy_s3_key']

    if not proxy_s3_key:
        missing_proxies.append(file_id)
        print(f"  [!] File {file_id}: No proxy S3 key found")
    else:
        files_data.append({
            'file_id': file_id,
            'filename': row['filename'],
            'proxy_s3_key': proxy_s3_key,
            'proxy_id': row['proxy_id']
        })

conn.close()

print(f"Found {len(files_data)} files with proxies")
if missing_proxies:
    print(f"WARNING: {len(missing_proxies)} files missing proxies: {missing_proxies}")
    print()

if not files_data:
    print("ERROR: No valid files to process")
    sys.exit(1)

# Build batch records
print()
print("Building batch records...")
records = []
nova_job_ids = []

# Standard analysis configuration
model = 'lite'
analysis_types = ['combined']  # Combined analysis (summary + chapters + elements + waterfall)
options = {
    'summary_depth': 'detailed',
    'language': 'en'
}

import uuid

for file_data in files_data:
    file_id = file_data['file_id']
    proxy_s3_key = file_data['proxy_s3_key']

    # Create analysis job in database
    job_id = f"nova-batch-retry-{file_id}-{uuid.uuid4().hex[:8]}"
    analysis_job_id = db.create_analysis_job(
        file_id=file_id,
        job_id=job_id,
        analysis_type='nova',
        status='PENDING'
    )

    # Create nova job in database
    nova_job_id = db.create_nova_job(
        analysis_job_id=analysis_job_id,
        model=model,
        analysis_types=analysis_types,
        user_options=options
    )

    # Mark as batch mode
    db.update_nova_job(nova_job_id, {'batch_mode': True})

    nova_job_ids.append(nova_job_id)

    # Build batch record with URL encoding (via nova_service)
    options_with_prefix = options.copy()
    options_with_prefix['batch_record_prefix'] = f'file-{file_id}:'

    file_records = nova_service._build_batch_records(
        s3_key=proxy_s3_key,
        analysis_types=analysis_types,
        options=options_with_prefix,
        record_prefix=f'file-{file_id}:'
    )

    records.extend(file_records)

    print(f"  [{len(records)}/{len(files_data)}] File {file_id}: {file_data['filename']}")

print()
print(f"Created {len(records)} batch records for {len(files_data)} files")
print()

# Submit batch job
job_name = f"nova-batch-retry-failed-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
input_prefix = "nova/batch/input"
output_prefix = "nova/batch/output"

print("=" * 80)
print("SUBMITTING BATCH JOB")
print("=" * 80)
print(f"Job Name: {job_name}")
print(f"Model: {model} (Nova Lite)")
print(f"Files: {len(files_data)}")
print(f"Analysis Types: {analysis_types}")
print(f"Batch Mode: 50% cost discount")
print()

try:
    result = nova_service.start_batch_analysis_records(
        records=records,
        model=model,
        role_arn=role_arn,
        input_prefix=input_prefix,
        output_prefix=output_prefix,
        job_name=job_name
    )

    batch_job_arn = result['batch_job_arn']
    batch_input_s3_key = result['batch_input_s3_key']
    batch_output_s3_prefix = result['batch_output_s3_prefix']

    print(f"[SUCCESS] Batch job submitted!")
    print()
    print(f"Batch Job ARN: {batch_job_arn}")
    print(f"Input S3 Key: {batch_input_s3_key}")
    print(f"Output S3 Prefix: {batch_output_s3_prefix}")
    print()

    # Update database - create bedrock_batch_jobs entry
    db.create_bedrock_batch_job(
        batch_job_arn=batch_job_arn,
        job_name=job_name,
        model=model,
        nova_job_ids=nova_job_ids,
        input_s3_key=batch_input_s3_key,
        output_s3_prefix=batch_output_s3_prefix
    )

    # Update nova jobs with batch information
    for nova_job_id in nova_job_ids:
        db.update_nova_job(nova_job_id, {
            'batch_job_arn': batch_job_arn,
            'batch_status': 'SUBMITTED',
            'batch_input_s3_key': batch_input_s3_key,
            'batch_output_s3_prefix': batch_output_s3_prefix
        })

    print(f"Database updated with batch job tracking")
    print()

    # Estimate processing time and cost
    print("=" * 80)
    print("BATCH JOB ESTIMATE")
    print("=" * 80)
    print(f"Videos: {len(files_data)}")
    print(f"Estimated processing time: ~20 minutes")
    print(f"Estimated cost: ~$0.17 (with 50% batch discount)")
    print()
    print("The batch job is now processing. You can check status in the UI or wait")
    print("for it to complete. Results will be automatically fetched when ready.")
    print()

except Exception as e:
    print(f"[ERROR] Failed to submit batch job: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("=" * 80)
print("[COMPLETE] Batch retry job successfully submitted!")
print("=" * 80)
