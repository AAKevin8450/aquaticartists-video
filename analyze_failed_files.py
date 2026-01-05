"""
Analyze the 35 failed batch processing files to identify the root cause
"""
import sqlite3
import boto3
import os
import json
from dotenv import load_dotenv

load_dotenv()

# Get failed file IDs from S3 batch output
s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
bucket_name = os.getenv('S3_BUCKET_NAME')
key = 'nova/batch/output/nova-batch-batch-nova-cbd6c874-1-1767575198/813pkj5xu97q/batch_input_nova-batch-batch-nova-cbd6c874-1-1767575198.jsonl.out'

print("Loading S3 batch output...")
response = s3_client.get_object(Bucket=bucket_name, Key=key)
body = response['Body'].read().decode('utf-8')
lines = [line for line in body.splitlines() if line.strip()]

# Extract failed file IDs and their S3 URIs
failed_records = []
for line in lines:
    record = json.loads(line)
    if 'error' in record:
        record_id = record.get('recordId', '')
        s3_uri = None

        # Extract S3 URI from modelInput
        if 'modelInput' in record:
            messages = record['modelInput'].get('messages', [])
            if messages:
                content = messages[0].get('content', [])
                for item in content:
                    if 'video' in item:
                        s3_uri = item['video']['source']['s3Location']['uri']
                        break

        if record_id and ':' in record_id:
            file_part = record_id.split(':')[0]
            if file_part.startswith('file-'):
                file_id = int(file_part[5:])
                failed_records.append({
                    'file_id': file_id,
                    'record_id': record_id,
                    's3_uri': s3_uri,
                    'error': record['error']
                })

print(f"Found {len(failed_records)} failed files")
print()

# Get file details from database
conn = sqlite3.connect('data/app.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

file_ids = [r['file_id'] for r in failed_records]
placeholders = ','.join('?' * len(file_ids))

# Get original files and their proxies
cursor.execute(f'''
    SELECT
        f.id,
        f.filename,
        f.s3_key as original_s3_key,
        f.local_path,
        proxy.id as proxy_id,
        proxy.filename as proxy_filename,
        proxy.s3_key as proxy_s3_key,
        proxy.local_path as proxy_local_path
    FROM files f
    LEFT JOIN files proxy ON proxy.source_file_id = f.id AND proxy.is_proxy = 1
    WHERE f.id IN ({placeholders})
    ORDER BY f.id
''', file_ids)

db_files = {row['id']: dict(row) for row in cursor.fetchall()}
conn.close()

print("=" * 80)
print("FAILED FILES ANALYSIS")
print("=" * 80)
print()

# Categorize issues
issues = {
    'missing_proxy': [],
    'missing_s3_key': [],
    'special_chars': [],
    'spaces_in_name': [],
    's3_not_exists': []
}

for rec in failed_records:
    file_id = rec['file_id']
    db_file = db_files.get(file_id)

    if not db_file:
        print(f"File ID {file_id}: NOT IN DATABASE")
        continue

    filename = db_file['filename']
    proxy_local_path = db_file['proxy_local_path']
    proxy_s3_key = db_file['proxy_s3_key']
    s3_uri = rec['s3_uri']

    print(f"File ID {file_id}:")
    print(f"  Filename: {filename}")
    print(f"  Proxy Path (local): {proxy_local_path or 'MISSING'}")
    print(f"  Proxy S3 Key: {proxy_s3_key or 'MISSING'}")
    print(f"  S3 URI (batch input): {s3_uri or 'MISSING'}")

    # Check for issues
    has_issues = False

    if not proxy_local_path:
        issues['missing_proxy'].append(file_id)
        print(f"  [X] ISSUE: No proxy created")
        has_issues = True

    if not proxy_s3_key:
        issues['missing_s3_key'].append(file_id)
        print(f"  [X] ISSUE: Proxy not uploaded to S3")
        has_issues = True

    # Check for special characters
    special_char_set = set(' ,()[]{}#&@!$%^*+=~`\\\'"')
    special_chars = [c for c in filename if c in special_char_set]
    if special_chars:
        issues['special_chars'].append(file_id)
        print(f"  [!] Special chars: {''.join(set(special_chars))}")

    if ' ' in filename:
        issues['spaces_in_name'].append(file_id)
        print(f"  [!] Contains spaces")

    # Check if file exists in S3
    if s3_uri and s3_uri.startswith('s3://'):
        # Parse S3 URI
        uri_parts = s3_uri[5:].split('/', 1)
        if len(uri_parts) == 2:
            uri_bucket, uri_key = uri_parts
            try:
                s3_client.head_object(Bucket=uri_bucket, Key=uri_key)
                print(f"  [OK] File EXISTS in S3")
            except:
                issues['s3_not_exists'].append(file_id)
                print(f"  [X] ISSUE: File NOT FOUND in S3")
                has_issues = True

    print()

print()
print("=" * 80)
print("ISSUE SUMMARY")
print("=" * 80)
print(f"Missing proxy path: {len(issues['missing_proxy'])} files")
print(f"Missing S3 key: {len(issues['missing_s3_key'])} files")
print(f"Files with special chars: {len(issues['special_chars'])} files")
print(f"Files with spaces: {len(issues['spaces_in_name'])} files")
print(f"Files not found in S3: {len(issues['s3_not_exists'])} files")
print()

# Show common patterns
print("=" * 80)
print("PATTERN ANALYSIS")
print("=" * 80)

# Check if all failed files have a common pattern
s3_not_found_files = [db_files[fid]['filename'] for fid in issues['s3_not_exists'] if fid in db_files]
if s3_not_found_files:
    print(f"\nFiles NOT FOUND in S3 ({len(s3_not_found_files)}):")
    for fname in s3_not_found_files[:10]:
        print(f"  - {fname}")
    if len(s3_not_found_files) > 10:
        print(f"  ... and {len(s3_not_found_files) - 10} more")
