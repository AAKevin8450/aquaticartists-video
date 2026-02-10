"""
Simple batch result fetcher - directly processes S3 output files.
"""
import boto3
import json
import os
from dotenv import load_dotenv
from app.database import get_db
from datetime import datetime

load_dotenv()

# Initialize AWS clients
s3 = boto3.client(
    's3',
    region_name=os.getenv('AWS_REGION', 'us-east-1'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

bucket_name = os.getenv('S3_BUCKET_NAME')

# Get batch job from database
db = get_db()
with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, batch_job_arn, output_s3_prefix, nova_job_ids, model
        FROM bedrock_batch_jobs
        LIMIT 1
    ''')
    batch_job = cursor.fetchone()

if not batch_job:
    print("No batch jobs found!")
    exit(0)

output_prefix = batch_job['output_s3_prefix']
nova_job_ids = json.loads(batch_job['nova_job_ids'])
model = batch_job['model']

print(f"Fetching batch results from S3...")
print(f"  Bucket: {bucket_name}")
print(f"  Prefix: {output_prefix}")
print(f"  Jobs: {len(nova_job_ids)}")

# List all output files
response = s3.list_objects_v2(Bucket=bucket_name, Prefix=output_prefix)
files = [obj['Key'] for obj in response.get('Contents', []) if obj['Key'].endswith('.jsonl.out')]

print(f"\nFound {len(files)} output files")

# Read all output records
all_records = []
for file_key in files:
    print(f"  Reading {file_key}...")
    obj = s3.get_object(Bucket=bucket_name, Key=file_key)
    content = obj['Body'].read().decode('utf-8')

    lines = content.strip().split('\n')
    print(f"    Found {len(lines)} lines")

    for i, line in enumerate(lines):
        if line.strip():
            try:
                record = json.loads(line)
                all_records.append(record)
            except json.JSONDecodeError as e:
                print(f"    Line {i+1}: JSON decode error - {e}")
                if i < 2:  # Show first few lines for debugging
                    print(f"      Content: {line[:200]}...")

print(f"\nTotal records: {len(all_records)}")

# Debug: show first record
if all_records:
    print("\nFirst record keys:")
    print(f"  {list(all_records[0].keys())}")

    # Show full first record to understand structure
    with open('debug_batch_record.json', 'w') as f:
        json.dump(all_records[0], f, indent=2)
    print("  Full first record saved to debug_batch_record.json")

# Process records and update database
print("\nProcessing records...")

# Model pricing (batch rates - 50% off standard)
pricing = {
    'lite': {
        'input_per_1k': 0.00003,   # $0.00003 per 1K tokens
        'output_per_1k': 0.00012   # $0.00012 per 1K tokens
    },
    'pro': {
        'input_per_1k': 0.0004,
        'output_per_1k': 0.0016
    },
    'premier': {
        'input_per_1k': 0.0015,
        'output_per_1k': 0.006
    }
}

rates = pricing.get(model, pricing['lite'])

total_input_tokens = 0
total_output_tokens = 0
total_cost = 0

processed = 0
for record in all_records:
    record_id = record.get('recordId', '')

    # Extract nova_job_id from recordId (format: "combined", "summary", etc.)
    # Skip for now - we'll update based on order

    # Extract model output
    model_output = record.get('modelOutput', {})
    content = model_output.get('content', [])

    if not content:
        continue

    # Get the text response
    response_text = content[0].get('text', '') if content else ''

    # Get usage metadata
    usage = model_output.get('usage', {})
    input_tokens = usage.get('inputTokens', 0)
    output_tokens = usage.get('outputTokens', 0)
    total_tokens = input_tokens + output_tokens

    # Calculate cost (batch rate)
    cost = (input_tokens / 1000) * rates['input_per_1k'] + (output_tokens / 1000) * rates['output_per_1k']

    total_input_tokens += input_tokens
    total_output_tokens += output_tokens
    total_cost += cost

    processed += 1

    if processed <= 5:
        print(f"\n  Record {record_id}:")
        print(f"    Input tokens: {input_tokens:,}")
        print(f"    Output tokens: {output_tokens:,}")
        print(f"    Cost: ${cost:.6f}")

print(f"\n{'=' * 80}")
print(f"BATCH JOB TOTALS:")
print(f"{'=' * 80}")
print(f"  Records processed: {processed}")
print(f"  Total input tokens: {total_input_tokens:,}")
print(f"  Total output tokens: {total_output_tokens:,}")
print(f"  Total tokens: {total_input_tokens + total_output_tokens:,}")
print(f"  Total cost (batch rate): ${total_cost:.6f}")
print()

# Calculate cost per 1M tokens for verification
if total_input_tokens + total_output_tokens > 0:
    avg_cost_per_1m = (total_cost / (total_input_tokens + total_output_tokens)) * 1_000_000
    print(f"  Average cost per 1M tokens: ${avg_cost_per_1m:.2f}")
    print()

# Expected rates
print(f"  Expected batch rates for {model.upper()}:")
print(f"    Input: ${rates['input_per_1k'] * 1000:.2f} per 1M tokens")
print(f"    Output: ${rates['output_per_1k'] * 1000:.2f} per 1M tokens")
print()

# Calculate expected cost at standard rates for comparison
standard_pricing = {
    'lite': {'input_per_1k': 0.00006, 'output_per_1k': 0.00024},
    'pro': {'input_per_1k': 0.0008, 'output_per_1k': 0.0032},
    'premier': {'input_per_1k': 0.003, 'output_per_1k': 0.012}
}

std_rates = standard_pricing.get(model, standard_pricing['lite'])
standard_cost = (total_input_tokens / 1000) * std_rates['input_per_1k'] + (total_output_tokens / 1000) * std_rates['output_per_1k']

print(f"  Standard rate cost would be: ${standard_cost:.6f}")
if standard_cost > 0:
    print(f"  Savings: ${standard_cost - total_cost:.6f} ({((standard_cost - total_cost) / standard_cost * 100):.1f}%)")
print(f"{'=' * 80}")

print("\n\nNOTE: This is the calculated cost based on batch pricing.")
print("To verify actual AWS billing, run: python check_aws_billing.py")
