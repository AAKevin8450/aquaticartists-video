"""
Analyze Nova Analysis batch job failures

Run this to investigate why files failed during Nova processing:
    python -m scripts.analyze_nova_failures
"""

import sqlite3
import json
import os
import sys
from pathlib import Path
from collections import Counter

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

DATABASE_PATH = os.getenv('DATABASE_PATH', 'data/app.db')


def analyze_failures():
    """Analyze Nova analysis job failures"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    try:
        # Get all failed Nova jobs with file information
        cursor.execute('''
            SELECT
                nj.id,
                nj.created_at,
                nj.status,
                nj.error_message,
                nj.model,
                nj.analysis_types,
                nj.cost_usd,
                nj.processing_time_seconds,
                f.filename,
                f.local_path,
                f.duration_seconds,
                f.size_bytes
            FROM nova_jobs nj
            LEFT JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id
            LEFT JOIN files f ON aj.file_id = f.id
            WHERE nj.status = 'FAILED'
            ORDER BY nj.created_at DESC
        ''')

        failures = cursor.fetchall()

        if not failures:
            print("No failed Nova jobs found in database")
            return

        print("=" * 100)
        print(f"NOVA JOB FAILURE ANALYSIS - {len(failures)} Failed Jobs")
        print("=" * 100)

        # Categorize errors
        error_categories = Counter()
        error_examples = {}
        file_durations = []
        file_sizes = []

        for failure in failures:
            (job_id, created_at, status, error_msg, model, analysis_types,
             cost, proc_time, file_name, local_path, duration, size_bytes) = failure

            if not error_msg:
                error_msg = "No error message recorded"

            # Categorize the error
            if 'ValidationException' in error_msg:
                category = 'ValidationException'
            elif 'ThrottlingException' in error_msg:
                category = 'ThrottlingException'
            elif 'duration exceeds' in error_msg or 'exceeds maximum' in error_msg or 'exceeds the maximum' in error_msg:
                category = 'Duration/Size Limit Exceeded'
            elif 'not found' in error_msg.lower() or 'does not exist' in error_msg.lower():
                category = 'File Not Found / S3 Error'
            elif 'format' in error_msg.lower() or 'codec' in error_msg.lower():
                category = 'Format/Codec Issue'
            elif 'timed out' in error_msg.lower() or 'timeout' in error_msg.lower():
                category = 'Timeout'
            elif 'AccessDeniedException' in error_msg or 'Access Denied' in error_msg:
                category = 'Access Denied'
            elif 'too large' in error_msg.lower():
                category = 'File Too Large'
            else:
                category = 'Other'

            error_categories[category] += 1

            # Store first example of each category
            if category not in error_examples:
                error_examples[category] = {
                    'job_id': job_id,
                    'file': file_name or local_path or 'unknown',
                    'error': error_msg,
                    'model': model,
                    'duration': duration,
                    'size_mb': size_bytes / 1024 / 1024 if size_bytes else None,
                    'created_at': created_at
                }

            # Track file characteristics
            if duration:
                file_durations.append(duration)
            if size_bytes:
                file_sizes.append(size_bytes / 1024 / 1024)  # Convert to MB

        # Print error summary
        print("\nError Summary by Category:")
        print("-" * 80)
        for category, count in error_categories.most_common():
            percentage = (count / len(failures)) * 100
            print(f"  {category}: {count} failures ({percentage:.1f}%)")

        # Print file characteristics for failed files
        if file_durations:
            avg_duration = sum(file_durations) / len(file_durations)
            max_duration = max(file_durations)
            print(f"\nFailed File Durations:")
            print(f"  Average: {avg_duration:.1f} seconds ({avg_duration/60:.1f} minutes)")
            print(f"  Maximum: {max_duration:.1f} seconds ({max_duration/60:.1f} minutes)")
            print(f"  Files with duration data: {len(file_durations)}")

        if file_sizes:
            avg_size = sum(file_sizes) / len(file_sizes)
            max_size = max(file_sizes)
            print(f"\nFailed File Sizes:")
            print(f"  Average: {avg_size:.1f} MB")
            print(f"  Maximum: {max_size:.1f} MB")

        # Print examples
        print("\n" + "=" * 100)
        print("Error Examples by Category:")
        print("=" * 100)
        for category, example in error_examples.items():
            print(f"\n[{category}]")
            print(f"  Job ID: {example['job_id']}")
            print(f"  File: {example['file']}")
            print(f"  Model: {example['model']}")
            if example['duration']:
                print(f"  Duration: {example['duration']:.1f}s ({example['duration']/60:.1f} min)")
            if example['size_mb']:
                print(f"  Size: {example['size_mb']:.1f} MB")
            print(f"  Created: {example['created_at']}")
            print(f"  Error: {example['error'][:300]}")
            if len(example['error']) > 300:
                print(f"         ...")

        # Print recent failures (last 10)
        print("\n" + "=" * 100)
        print("Recent Failures (Last 10):")
        print("=" * 100)
        for i, failure in enumerate(failures[:10], 1):
            (job_id, created_at, status, error_msg, model, analysis_types,
             cost, proc_time, file_name, local_path, duration, size_bytes) = failure

            print(f"\n{i}. Job ID: {job_id} | Created: {created_at}")
            print(f"   File: {file_name or local_path or 'unknown'}")
            print(f"   Model: {model}")
            if duration:
                print(f"   Duration: {duration:.1f}s ({duration/60:.1f} min)")
            print(f"   Error: {error_msg[:200]}")
            if len(error_msg) > 200:
                print(f"          ...")

        print("\n" + "=" * 100)

    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

    return True


if __name__ == '__main__':
    analyze_failures()
