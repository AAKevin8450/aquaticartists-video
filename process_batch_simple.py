"""
Simple batch results processor - processes in-memory for speed
"""
import json
import sqlite3
from datetime import datetime, timezone
import boto3
import os
from dotenv import load_dotenv

load_dotenv()

# Direct database connection
conn = sqlite3.connect('data/app.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# S3 client
s3_client = boto3.client(
    's3',
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)

bucket_name = os.getenv('S3_BUCKET_NAME')
batch_job_arn = 'arn:aws:bedrock:us-east-1:676206912644:model-invocation-job/813pkj5xu97q'

print("=" * 80)
print("LOADING BATCH JOB DATA")
print("=" * 80)

# Get batch job
cursor.execute('SELECT * FROM bedrock_batch_jobs WHERE batch_job_arn = ?', (batch_job_arn,))
batch_job = cursor.fetchone()
nova_job_ids = eval(batch_job['nova_job_ids'])

print(f"Jobs to process: {len(nova_job_ids)}")

# Load all S3 results into memory
key = f"{batch_job['output_s3_prefix']}813pkj5xu97q/batch_input_nova-batch-batch-nova-cbd6c874-1-1767575198.jsonl.out"
print(f"Loading S3 file: {key}")

response = s3_client.get_object(Bucket=bucket_name, Key=key)
body = response['Body'].read().decode('utf-8')
lines = [line for line in body.splitlines() if line.strip()]

print(f"Loaded {len(lines)} records from S3")
print()

# Parse all records
records = {}
for line in lines:
    try:
        record = json.loads(line)
        record_id = record.get('recordId', '')
        if record_id:
            # Extract file ID from recordId (format: "file-33945:combined")
            if ':' in record_id:
                file_part = record_id.split(':')[0]
                if file_part.startswith('file-'):
                    file_id = int(file_part[5:])
                    records[file_id] = record
    except:
        continue

print(f"Parsed {len(records)} records")
print()

# Process each job
print("=" * 80)
print("PROCESSING JOBS")
print("=" * 80)

success = 0
failed = 0
skipped = 0
total_cost = 0.0

# Nova Lite batch pricing: $0.00006/1K input tokens, $0.00024/1K output tokens
INPUT_PRICE = 0.00006 / 1000
OUTPUT_PRICE = 0.00024 / 1000

for idx, nova_job_id in enumerate(nova_job_ids, 1):
    cursor.execute('SELECT * FROM nova_jobs WHERE id = ?', (nova_job_id,))
    job = cursor.fetchone()

    if not job:
        failed += 1
        continue

    # Skip if already has results
    if job['summary_result']:
        skipped += 1
        if job['cost_usd']:
            total_cost += job['cost_usd']
        continue

    # Get analysis_job to find file_id
    cursor.execute('SELECT file_id FROM analysis_jobs WHERE id = ?', (job['analysis_job_id'],))
    analysis_job = cursor.fetchone()

    if not analysis_job:
        failed += 1
        continue

    file_id = analysis_job['file_id']

    # Find record in S3 results
    if file_id not in records:
        print(f"[{idx}/{len(nova_job_ids)}] File {file_id} - no S3 record found")
        failed += 1
        continue

    record = records[file_id]
    model_output = record.get('modelOutput', {})

    # Extract usage
    usage = model_output.get('usage', {})
    input_tokens = usage.get('inputTokens', 0)
    output_tokens = usage.get('outputTokens', 0)
    total_tokens = usage.get('totalTokens', input_tokens + output_tokens)

    # Calculate cost
    cost = (input_tokens * INPUT_PRICE) + (output_tokens * OUTPUT_PRICE)
    total_cost += cost

    # Extract text from output
    output_data = model_output.get('output', {})
    message = output_data.get('message', {})
    content_list = message.get('content', [])

    text = ''
    if content_list and isinstance(content_list, list):
        first_content = content_list[0]
        if isinstance(first_content, dict):
            text = first_content.get('text', '')

    # Parse JSON from text (remove markdown code fences)
    text = text.strip()
    if text.startswith('```json'):
        text = text[7:]
    if text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()

    try:
        analysis = json.loads(text)
    except:
        print(f"[{idx}/{len(nova_job_ids)}] File {file_id} - failed to parse JSON")
        failed += 1
        continue

    # Update nova_jobs table
    cursor.execute('''
        UPDATE nova_jobs
        SET batch_status = 'COMPLETED',
            status = 'COMPLETED',
            progress_percent = 100,
            tokens_input = ?,
            tokens_output = ?,
            tokens_total = ?,
            cost_usd = ?,
            summary_result = ?,
            chapters_result = ?,
            elements_result = ?,
            waterfall_classification_result = ?,
            search_metadata = ?,
            completed_at = ?
        WHERE id = ?
    ''', (
        input_tokens,
        output_tokens,
        total_tokens,
        cost,
        json.dumps(analysis.get('summary', {})) if 'summary' in analysis else None,
        json.dumps(analysis.get('chapters', {})) if 'chapters' in analysis else None,
        json.dumps(analysis.get('elements', {})) if 'elements' in analysis else None,
        json.dumps(analysis.get('waterfall_classification', {})) if 'waterfall_classification' in analysis else None,
        json.dumps(analysis.get('search_metadata', {})) if 'search_metadata' in analysis else None,
        datetime.now(timezone.utc).isoformat(),
        nova_job_id
    ))

    # Update analysis_jobs table
    cursor.execute('''
        UPDATE analysis_jobs
        SET status = 'COMPLETED'
        WHERE id = ?
    ''', (job['analysis_job_id'],))

    success += 1

    if idx % 25 == 0:
        conn.commit()
        print(f"[{idx}/{len(nova_job_ids)}] Processed {success}, ${total_cost:.4f}")

conn.commit()

print()
print("=" * 80)
print("COMPLETE")
print("=" * 80)
print(f"Success: {success}/{len(nova_job_ids)}")
print(f"Failed: {failed}")
print(f"Skipped: {skipped}")
print(f"Total Cost: ${total_cost:.4f}")
print(f"On-Demand Cost (est): ${total_cost * 2:.4f}")
print(f"Savings: ${total_cost:.4f}")

conn.close()
