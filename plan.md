# Nova Batch Processing Improvements - Implementation Plan

## Overview

This plan addresses 8 improvements to the Nova batch processing system, prioritized by impact. Each task includes exact file locations, code snippets, and step-by-step instructions.

---

## Task 1: Add search_metadata to Batch Results (HIGH PRIORITY)

### Problem
`fetch_batch_results()` in `nova_service.py` doesn't extract `search_metadata` from batch output. Videos processed via batch mode won't have metadata for semantic search.

### Files to Modify
- `app/services/nova_service.py` (lines 538-763)

### Implementation Steps

#### Step 1.1: Add search_metadata parsing to fetch_batch_results()

In `app/services/nova_service.py`, locate the `fetch_batch_results()` method (starts at line 538).

After the `waterfall_classification` block (around line 744), add handling for `search_metadata`:

```python
# After line 744 (after waterfall_classification block), add:

        # Handle search_metadata if present in combined results
        if 'search_metadata' in record_outputs:
            output = record_outputs['search_metadata']
            metadata_text = self._extract_text_from_batch_output(output) or '{}'
            try:
                parsed = self._parse_json_response(metadata_text)
            except NovaError as e:
                logger.error(f"Failed to parse search_metadata batch response: {e}")
                parsed = {}

            # Validate and normalize search_metadata structure
            search_metadata = {
                'project': parsed.get('project', {}),
                'location': parsed.get('location', {}),
                'content': parsed.get('content', {}),
                'keywords': parsed.get('keywords', []),
                'dates': parsed.get('dates', {})
            }
            results['search_metadata'] = search_metadata
```

#### Step 1.2: Update combined results handling

In the same file, locate the combined results block (around line 588-613). After `results.update(combined_results)` (line 609), ensure search_metadata is included:

```python
# The combined results from _build_combined_results already includes search_metadata
# Verify this by checking app/services/nova/enrichment.py line 331
# No change needed here if using combined mode
```

#### Step 1.3: Store search_metadata in nova_analysis.py status endpoint

In `app/routes/nova_analysis.py`, locate `get_nova_status()` (line 545). In the update_data block (around line 617-642), add:

```python
# After line 642 (after raw_response handling), add:
                if 'search_metadata' in results:
                    update_data['search_metadata'] = json.dumps(results['search_metadata'])
```

### Verification
1. Run a batch Nova analysis on a test video
2. Check `nova_jobs.search_metadata` column is populated
3. Verify the search text includes metadata via `/api/nova/results/{id}`

---

## Task 2: Add Bedrock Batch Job Tracking Table (MEDIUM PRIORITY)

### Problem
Multiple `nova_jobs` reference the same `batch_job_arn` but there's no central tracking, causing redundant API calls.

### Files to Modify
- `app/database/base.py` (add table schema)
- `app/database/batch_jobs.py` (new file - CRUD operations)
- `app/database/__init__.py` (register mixin)

### Implementation Steps

#### Step 2.1: Add database table schema

In `app/database/base.py`, locate the table creation section (around line 249). After the `nova_jobs` table creation, add:

```python
            # Bedrock batch jobs tracking table (for aggregated batch submissions)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bedrock_batch_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_job_arn TEXT UNIQUE NOT NULL,
                    job_name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'SUBMITTED',
                    model TEXT NOT NULL,
                    input_s3_key TEXT,
                    output_s3_prefix TEXT,
                    nova_job_ids TEXT,
                    total_records INTEGER DEFAULT 0,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_checked_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    failure_message TEXT,
                    results_cached INTEGER DEFAULT 0,
                    cached_results TEXT
                )
            ''')

            # Index for faster lookups
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_bedrock_batch_jobs_status
                ON bedrock_batch_jobs(status)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_bedrock_batch_jobs_arn
                ON bedrock_batch_jobs(batch_job_arn)
            ''')
```

#### Step 2.2: Create batch_jobs.py mixin

Create new file `app/database/batch_jobs.py`:

```python
"""Bedrock batch job operations mixin for database."""
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any


class BedrockBatchJobsMixin:
    """Mixin providing Bedrock batch job CRUD operations."""

    def create_bedrock_batch_job(self, batch_job_arn: str, job_name: str, model: str,
                                  input_s3_key: str, output_s3_prefix: str,
                                  nova_job_ids: List[int], total_records: int = 0) -> int:
        """Create a new Bedrock batch job tracking record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO bedrock_batch_jobs
                (batch_job_arn, job_name, model, input_s3_key, output_s3_prefix,
                 nova_job_ids, total_records, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'SUBMITTED')
            ''', (batch_job_arn, job_name, model, input_s3_key, output_s3_prefix,
                  json.dumps(nova_job_ids), total_records))
            return cursor.lastrowid

    def get_bedrock_batch_job_by_arn(self, batch_job_arn: str) -> Optional[Dict[str, Any]]:
        """Get Bedrock batch job by ARN."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bedrock_batch_jobs WHERE batch_job_arn = ?',
                          (batch_job_arn,))
            row = cursor.fetchone()
            if row:
                job = dict(row)
                if job.get('nova_job_ids'):
                    job['nova_job_ids'] = json.loads(job['nova_job_ids'])
                if job.get('cached_results'):
                    job['cached_results'] = json.loads(job['cached_results'])
                return job
            return None

    def get_bedrock_batch_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Get Bedrock batch job by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM bedrock_batch_jobs WHERE id = ?', (job_id,))
            row = cursor.fetchone()
            if row:
                job = dict(row)
                if job.get('nova_job_ids'):
                    job['nova_job_ids'] = json.loads(job['nova_job_ids'])
                if job.get('cached_results'):
                    job['cached_results'] = json.loads(job['cached_results'])
                return job
            return None

    def update_bedrock_batch_job(self, batch_job_arn: str, update_data: Dict[str, Any]):
        """Update Bedrock batch job with arbitrary fields."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            fields = []
            values = []
            for key, value in update_data.items():
                fields.append(f"{key} = ?")
                if key in ('nova_job_ids', 'cached_results'):
                    values.append(json.dumps(value) if value is not None else None)
                else:
                    values.append(value)

            values.append(batch_job_arn)
            query = f"UPDATE bedrock_batch_jobs SET {', '.join(fields)} WHERE batch_job_arn = ?"
            cursor.execute(query, values)

    def get_pending_bedrock_batch_jobs(self) -> List[Dict[str, Any]]:
        """Get all pending (non-completed) Bedrock batch jobs."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM bedrock_batch_jobs
                WHERE status NOT IN ('COMPLETED', 'FAILED', 'STOPPED')
                ORDER BY submitted_at ASC
            ''')
            jobs = []
            for row in cursor.fetchall():
                job = dict(row)
                if job.get('nova_job_ids'):
                    job['nova_job_ids'] = json.loads(job['nova_job_ids'])
                jobs.append(job)
            return jobs

    def should_check_bedrock_batch_status(self, batch_job_arn: str,
                                           cache_seconds: int = 30) -> bool:
        """Check if enough time has passed to re-check batch status."""
        job = self.get_bedrock_batch_job_by_arn(batch_job_arn)
        if not job:
            return True

        last_checked = job.get('last_checked_at')
        if not last_checked:
            return True

        if isinstance(last_checked, str):
            last_checked = datetime.fromisoformat(last_checked.replace('Z', '+00:00'))

        return datetime.utcnow() - last_checked > timedelta(seconds=cache_seconds)

    def mark_bedrock_batch_checked(self, batch_job_arn: str):
        """Update last_checked_at timestamp."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE bedrock_batch_jobs
                SET last_checked_at = CURRENT_TIMESTAMP
                WHERE batch_job_arn = ?
            ''', (batch_job_arn,))

    def get_old_bedrock_batch_jobs(self, days_old: int = 7) -> List[Dict[str, Any]]:
        """Get completed batch jobs older than specified days for cleanup."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM bedrock_batch_jobs
                WHERE status IN ('COMPLETED', 'FAILED', 'STOPPED')
                AND completed_at < datetime('now', '-' || ? || ' days')
            ''', (days_old,))
            jobs = []
            for row in cursor.fetchall():
                job = dict(row)
                if job.get('nova_job_ids'):
                    job['nova_job_ids'] = json.loads(job['nova_job_ids'])
                jobs.append(job)
            return jobs

    def delete_bedrock_batch_job(self, batch_job_arn: str):
        """Delete a Bedrock batch job record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM bedrock_batch_jobs WHERE batch_job_arn = ?',
                          (batch_job_arn,))
```

#### Step 2.3: Register mixin in database __init__.py

In `app/database/__init__.py`, add the import and mixin:

```python
# Add import at top of file:
from .batch_jobs import BedrockBatchJobsMixin

# Add to the Database class inheritance list:
class Database(FilesMixin, TranscriptsMixin, AnalysisJobsMixin, NovaJobsMixin,
               EmbeddingsMixin, BillingMixin, RescanJobsMixin, ImportJobsMixin,
               BedrockBatchJobsMixin):  # Add this mixin
```

### Verification
1. Restart application to trigger table creation
2. Check SQLite database has `bedrock_batch_jobs` table
3. Test CRUD operations via Python shell

---

## Task 3: Integrate Batch Job Tracking into Submission Flow (MEDIUM PRIORITY)

### Problem
Need to create `bedrock_batch_jobs` records when submitting and use them for status caching.

### Files to Modify
- `app/routes/file_management/batch.py` (lines 1282-1322)
- `app/routes/nova_analysis.py` (lines 597-675)

### Implementation Steps

#### Step 3.1: Create bedrock_batch_jobs record on submission

In `app/routes/file_management/batch.py`, locate the batch submission block (around line 1282-1322).

After `batch_response = nova_service.start_batch_analysis_records(...)` (line 1289), add:

```python
# After line 1289, add:
                # Create tracking record for the Bedrock batch job
                nova_job_ids = [entry['nova_job_id'] for entry in batch_jobs]
                db.create_bedrock_batch_job(
                    batch_job_arn=batch_response['batch_job_arn'],
                    job_name=job_name,
                    model=model_key,
                    input_s3_key=batch_response['batch_input_s3_key'],
                    output_s3_prefix=batch_response['batch_output_s3_prefix'],
                    nova_job_ids=nova_job_ids,
                    total_records=len(batch_records)
                )
```

#### Step 3.2: Use cached status in polling endpoint

In `app/routes/nova_analysis.py`, locate `get_nova_status()` (line 545). Replace the batch status checking block (lines 597-675) with cached version:

```python
        # Around line 597, replace the existing batch status checking with:
        if job.get('batch_job_arn') and job['status'] not in ('COMPLETED', 'FAILED'):
            batch_job_arn = job['batch_job_arn']

            # Check if we have a cached status that's still fresh
            bedrock_job = db.get_bedrock_batch_job_by_arn(batch_job_arn)

            if bedrock_job and bedrock_job.get('status') in ('COMPLETED', 'SUCCEEDED'):
                # Use cached completed status - process results
                batch_state = bedrock_job['status'].upper()
            elif bedrock_job and bedrock_job.get('status') == 'FAILED':
                # Use cached failed status
                batch_state = 'FAILED'
                batch_status = {'status': 'FAILED', 'failure_message': bedrock_job.get('failure_message')}
            elif db.should_check_bedrock_batch_status(batch_job_arn, cache_seconds=30):
                # Time to re-check with Bedrock API
                nova_service = get_nova_service()
                batch_status = nova_service.get_batch_job_status(batch_job_arn)
                response['batch_status'] = batch_status['status']
                batch_state = (batch_status['status'] or '').upper()

                # Update cache
                db.mark_bedrock_batch_checked(batch_job_arn)
                db.update_bedrock_batch_job(batch_job_arn, {
                    'status': batch_status['status'],
                    'failure_message': batch_status.get('failure_message')
                })

                if batch_state in ('COMPLETED', 'SUCCEEDED', 'FAILED'):
                    db.update_bedrock_batch_job(batch_job_arn, {
                        'completed_at': datetime.utcnow().isoformat()
                    })
            else:
                # Use cached status (not time to re-check yet)
                batch_state = (bedrock_job.get('status') or '').upper()
                response['batch_status'] = bedrock_job.get('status')

            # Rest of the completion handling remains the same...
            if batch_state in ('COMPLETED', 'SUCCEEDED'):
                # ... existing result fetching code ...
```

Add the datetime import at the top of the file if not present:
```python
from datetime import datetime
```

### Verification
1. Submit a batch Nova analysis
2. Check `bedrock_batch_jobs` table has a new record
3. Poll status multiple times within 30s - should see only 1 Bedrock API call in logs

---

## Task 4: Cache Batch Results to Avoid Redundant S3 Downloads (MEDIUM PRIORITY)

### Problem
Each nova_job status poll re-downloads the same S3 output file when batch completes.

### Files to Modify
- `app/routes/nova_analysis.py` (lines 607-651)

### Implementation Steps

#### Step 4.1: Check for cached results before fetching

In `app/routes/nova_analysis.py`, in the `get_nova_status()` function, modify the result fetching block:

```python
            if batch_state in ('COMPLETED', 'SUCCEEDED'):
                # Check if results are already cached
                bedrock_job = db.get_bedrock_batch_job_by_arn(batch_job_arn)

                if bedrock_job and bedrock_job.get('results_cached') and bedrock_job.get('cached_results'):
                    # Use cached results - filter by this job's prefix
                    all_results = bedrock_job['cached_results']
                    options = _ensure_json_dict(job.get('user_options'))
                    record_prefix = options.get('batch_record_prefix')

                    # Filter cached results for this specific file
                    if record_prefix and record_prefix in all_results:
                        results = all_results[record_prefix]
                    else:
                        # Fallback to fetching (shouldn't happen normally)
                        nova_service = get_nova_service()
                        results = nova_service.fetch_batch_results(
                            s3_prefix=job.get('batch_output_s3_prefix', ''),
                            model=job['model'],
                            analysis_types=_ensure_json_list(job.get('analysis_types')),
                            options=options,
                            record_prefix=record_prefix
                        )
                else:
                    # First time fetching - get all results and cache them
                    nova_service = get_nova_service()

                    # Fetch WITHOUT prefix filter to get all results
                    all_results_raw = nova_service.fetch_batch_results(
                        s3_prefix=job.get('batch_output_s3_prefix', ''),
                        model=job['model'],
                        analysis_types=_ensure_json_list(job.get('analysis_types')),
                        options=_ensure_json_dict(job.get('user_options')),
                        record_prefix=None  # Get ALL results
                    )

                    # Cache the raw results
                    if bedrock_job:
                        db.update_bedrock_batch_job(batch_job_arn, {
                            'results_cached': 1,
                            'cached_results': all_results_raw
                        })

                    # Now fetch with prefix for this specific job
                    options = _ensure_json_dict(job.get('user_options'))
                    results = nova_service.fetch_batch_results(
                        s3_prefix=job.get('batch_output_s3_prefix', ''),
                        model=job['model'],
                        analysis_types=_ensure_json_list(job.get('analysis_types')),
                        options=options,
                        record_prefix=options.get('batch_record_prefix')
                    )

                # Continue with existing update logic...
                update_data = {
                    'status': 'COMPLETED',
                    # ... rest of update_data ...
                }
```

Note: This is a simplified approach. A more sophisticated implementation would parse all results once and distribute to all related nova_jobs in a single operation.

### Verification
1. Submit batch with 5+ videos
2. Poll each nova_job status
3. Check logs - S3 download should occur only once

---

## Task 5: Add S3 Cleanup for Old Batch Files (MEDIUM PRIORITY)

### Problem
Batch input/output files in S3 are never cleaned up.

### Files to Create/Modify
- `app/services/batch_cleanup_service.py` (new file)
- `scripts/cleanup_batch_files.py` (new file)

### Implementation Steps

#### Step 5.1: Create cleanup service

Create new file `app/services/batch_cleanup_service.py`:

```python
"""Service for cleaning up old batch processing files from S3."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class BatchCleanupService:
    """Handles cleanup of old batch processing artifacts."""

    def __init__(self, s3_client, bucket_name: str, db):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.db = db

    def cleanup_old_batch_files(self, days_old: int = 7, dry_run: bool = True) -> Dict[str, Any]:
        """
        Clean up S3 files for completed batch jobs older than specified days.

        Args:
            days_old: Minimum age in days for jobs to be cleaned up
            dry_run: If True, only report what would be deleted

        Returns:
            Summary of cleanup operation
        """
        results = {
            'jobs_processed': 0,
            'input_files_deleted': 0,
            'output_files_deleted': 0,
            'errors': [],
            'dry_run': dry_run
        }

        old_jobs = self.db.get_old_bedrock_batch_jobs(days_old)
        logger.info(f"Found {len(old_jobs)} old batch jobs to clean up")

        for job in old_jobs:
            try:
                # Delete input file
                input_key = job.get('input_s3_key')
                if input_key:
                    if dry_run:
                        logger.info(f"[DRY RUN] Would delete input: {input_key}")
                    else:
                        self.s3_client.delete_object(Bucket=self.bucket_name, Key=input_key)
                        logger.info(f"Deleted input file: {input_key}")
                    results['input_files_deleted'] += 1

                # Delete output files (prefix-based)
                output_prefix = job.get('output_s3_prefix')
                if output_prefix:
                    # List and delete all objects under the prefix
                    paginator = self.s3_client.get_paginator('list_objects_v2')
                    for page in paginator.paginate(Bucket=self.bucket_name, Prefix=output_prefix):
                        for obj in page.get('Contents', []):
                            if dry_run:
                                logger.info(f"[DRY RUN] Would delete output: {obj['Key']}")
                            else:
                                self.s3_client.delete_object(Bucket=self.bucket_name, Key=obj['Key'])
                                logger.info(f"Deleted output file: {obj['Key']}")
                            results['output_files_deleted'] += 1

                # Optionally delete the database record
                if not dry_run:
                    self.db.delete_bedrock_batch_job(job['batch_job_arn'])

                results['jobs_processed'] += 1

            except Exception as e:
                error_msg = f"Error cleaning up job {job.get('batch_job_arn')}: {str(e)}"
                logger.error(error_msg)
                results['errors'].append(error_msg)

        return results

    def get_batch_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics for batch files in S3."""
        stats = {
            'input_files': {'count': 0, 'total_bytes': 0},
            'output_files': {'count': 0, 'total_bytes': 0}
        }

        # Check input prefix
        input_prefix = 'nova/batch/input/'
        paginator = self.s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=input_prefix):
            for obj in page.get('Contents', []):
                stats['input_files']['count'] += 1
                stats['input_files']['total_bytes'] += obj.get('Size', 0)

        # Check output prefix
        output_prefix = 'nova/batch/output/'
        for page in paginator.paginate(Bucket=self.bucket_name, Prefix=output_prefix):
            for obj in page.get('Contents', []):
                stats['output_files']['count'] += 1
                stats['output_files']['total_bytes'] += obj.get('Size', 0)

        return stats
```

#### Step 5.2: Create cleanup script

Create new file `scripts/cleanup_batch_files.py`:

```python
#!/usr/bin/env python
"""Script to clean up old batch processing files from S3."""
import argparse
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.database import get_db
from app.services.batch_cleanup_service import BatchCleanupService
import boto3


def main():
    parser = argparse.ArgumentParser(description='Clean up old Nova batch files from S3')
    parser.add_argument('--days', type=int, default=7,
                        help='Delete files older than this many days (default: 7)')
    parser.add_argument('--no-dry-run', action='store_true',
                        help='Actually delete files (default is dry-run mode)')
    parser.add_argument('--stats', action='store_true',
                        help='Only show storage statistics, do not delete')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        db = get_db()

        s3_client = boto3.client(
            's3',
            region_name=app.config['AWS_REGION'],
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )

        cleanup_service = BatchCleanupService(
            s3_client=s3_client,
            bucket_name=app.config['S3_BUCKET_NAME'],
            db=db
        )

        if args.stats:
            print("\n=== Batch Storage Statistics ===")
            stats = cleanup_service.get_batch_storage_stats()
            print(f"Input files:  {stats['input_files']['count']} files, "
                  f"{stats['input_files']['total_bytes'] / 1024 / 1024:.2f} MB")
            print(f"Output files: {stats['output_files']['count']} files, "
                  f"{stats['output_files']['total_bytes'] / 1024 / 1024:.2f} MB")
            return

        dry_run = not args.no_dry_run

        print(f"\n=== Batch File Cleanup ===")
        print(f"Mode: {'DRY RUN' if dry_run else 'LIVE DELETE'}")
        print(f"Cleaning files older than {args.days} days\n")

        results = cleanup_service.cleanup_old_batch_files(
            days_old=args.days,
            dry_run=dry_run
        )

        print(f"\nResults:")
        print(f"  Jobs processed: {results['jobs_processed']}")
        print(f"  Input files {'would be ' if dry_run else ''}deleted: {results['input_files_deleted']}")
        print(f"  Output files {'would be ' if dry_run else ''}deleted: {results['output_files_deleted']}")

        if results['errors']:
            print(f"\nErrors ({len(results['errors'])}):")
            for error in results['errors']:
                print(f"  - {error}")


if __name__ == '__main__':
    main()
```

### Verification
1. Run `python -m scripts.cleanup_batch_files --stats`
2. Run `python -m scripts.cleanup_batch_files --days 7` (dry run)
3. If output looks correct, run with `--no-dry-run`

---

## Task 6: Add Retry Logic for Result Fetching (LOW PRIORITY)

### Problem
If S3 result fetching fails, there's no retry and job may be stuck.

### Files to Modify
- `app/routes/nova_analysis.py` (lines 607-651)

### Implementation Steps

#### Step 6.1: Add retry wrapper for result fetching

In `app/routes/nova_analysis.py`, add a retry helper function near the top of the file:

```python
import time
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=1.0, max_delay=10.0):
    """Decorator for retrying a function with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(max_delay, base_delay * (2 ** attempt))
                        logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay}s: {e}")
                        time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator
```

#### Step 6.2: Wrap result fetching in retry logic

In the `get_nova_status()` function, wrap the `fetch_batch_results` call:

```python
            if batch_state in ('COMPLETED', 'SUCCEEDED'):
                options = _ensure_json_dict(job.get('user_options'))

                @retry_with_backoff(max_retries=3, base_delay=2.0)
                def fetch_results_with_retry():
                    return nova_service.fetch_batch_results(
                        s3_prefix=job.get('batch_output_s3_prefix', ''),
                        model=job['model'],
                        analysis_types=_ensure_json_list(job.get('analysis_types')),
                        options=options,
                        record_prefix=options.get('batch_record_prefix')
                    )

                try:
                    results = fetch_results_with_retry()
                except Exception as e:
                    logger.error(f"Failed to fetch batch results after retries: {e}")
                    db.update_nova_job(nova_job_id, {
                        'status': 'FAILED',
                        'error_message': f'Failed to fetch results: {str(e)}',
                        'batch_status': 'RESULT_FETCH_FAILED'
                    })
                    db.update_analysis_job(
                        job['analysis_job_id'],
                        status='FAILED',
                        error_message=f'Failed to fetch batch results: {str(e)}'
                    )
                    response['status'] = 'FAILED'
                    response['error_message'] = f'Failed to fetch results: {str(e)}'
                    return jsonify(response), 200

                # Continue with existing result processing...
```

### Verification
1. Simulate S3 failure (disconnect network briefly)
2. Check logs show retry attempts
3. Verify job doesn't get stuck in IN_PROGRESS

---

## Task 7: Add Pending Batch Jobs API Endpoint (LOW PRIORITY)

### Problem
Users can't see status of pending Bedrock batch jobs.

### Files to Modify
- `app/routes/nova_analysis.py` (add new endpoint)

### Implementation Steps

#### Step 7.1: Add pending jobs endpoint

In `app/routes/nova_analysis.py`, add a new endpoint after the existing status endpoint:

```python
@bp.route('/batch/pending', methods=['GET'])
def get_pending_batch_jobs():
    """
    Get all pending Bedrock batch jobs.

    Returns:
        {
            "pending_jobs": [
                {
                    "id": 1,
                    "batch_job_arn": "arn:aws:...",
                    "job_name": "nova-batch-...",
                    "status": "IN_PROGRESS",
                    "model": "lite",
                    "total_records": 15,
                    "submitted_at": "2025-01-03T10:00:00",
                    "nova_job_count": 5
                }
            ],
            "total_pending": 1
        }
    """
    try:
        db = get_db()
        pending_jobs = db.get_pending_bedrock_batch_jobs()

        # Optionally refresh status for stale jobs
        nova_service = get_nova_service()
        for job in pending_jobs:
            if db.should_check_bedrock_batch_status(job['batch_job_arn'], cache_seconds=60):
                try:
                    status = nova_service.get_batch_job_status(job['batch_job_arn'])
                    job['status'] = status['status']
                    db.mark_bedrock_batch_checked(job['batch_job_arn'])
                    db.update_bedrock_batch_job(job['batch_job_arn'], {
                        'status': status['status']
                    })
                except Exception as e:
                    logger.warning(f"Failed to refresh batch status: {e}")

        response_jobs = []
        for job in pending_jobs:
            response_jobs.append({
                'id': job['id'],
                'batch_job_arn': job['batch_job_arn'],
                'job_name': job['job_name'],
                'status': job['status'],
                'model': job['model'],
                'total_records': job['total_records'],
                'submitted_at': job['submitted_at'],
                'last_checked_at': job.get('last_checked_at'),
                'nova_job_count': len(job.get('nova_job_ids', []))
            })

        return jsonify({
            'pending_jobs': response_jobs,
            'total_pending': len(response_jobs)
        }), 200

    except Exception as e:
        logger.error(f"Error getting pending batch jobs: {str(e)}")
        return jsonify({'error': str(e)}), 500
```

### Verification
1. Submit a batch job
2. Call `GET /api/nova/batch/pending`
3. Verify response includes the pending job

---

## Task 8: Add Image Batch Support (LOW PRIORITY - OPTIONAL)

### Problem
Images are processed synchronously even in batch mode.

### Files to Modify
- `app/routes/file_management/batch.py` (lines 1152-1189)
- `app/services/nova_image_service.py` (add batch methods)

### Implementation Steps

This is a larger change and should be implemented separately. The key changes would be:

1. Add `_build_batch_records()` method to `NovaImageService`
2. Add `start_batch_image_analysis()` method
3. Modify `_run_batch_nova_batch_mode()` to batch images separately
4. Add result parsing for image batch outputs

### Verification
Deferred to separate implementation phase.

---

## Testing Checklist

After implementing all tasks, verify:

- [ ] Batch submission creates `bedrock_batch_jobs` record
- [ ] Status polling uses cached status (check logs for API call frequency)
- [ ] Results are cached and reused for multiple nova_jobs
- [ ] `search_metadata` is populated for batch-processed videos
- [ ] S3 cleanup script works correctly
- [ ] Pending batch jobs endpoint returns correct data
- [ ] Retry logic handles transient S3 failures
- [ ] All existing tests still pass

---

## Rollback Plan

If issues arise:

1. Database changes are additive - no rollback needed for schema
2. Batch submission changes can be reverted by removing the `create_bedrock_batch_job` call
3. Status caching can be disabled by always setting `should_check = True`
4. S3 cleanup is manual-only, no automatic cleanup to rollback

---

## Implementation Order

1. **Task 2** - Database table (prerequisite for Tasks 3, 4, 5, 7)
2. **Task 3** - Integrate tracking (prerequisite for Tasks 4, 5)
3. **Task 1** - search_metadata fix (independent, high priority)
4. **Task 4** - Result caching (depends on Task 3)
5. **Task 5** - S3 cleanup (depends on Task 2)
6. **Task 6** - Retry logic (independent)
7. **Task 7** - Pending jobs API (depends on Task 2)
8. **Task 8** - Image batching (optional, independent)
