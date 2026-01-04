from app.database import get_db
from datetime import datetime, timedelta
import json

db = get_db()
with db.get_connection() as conn:
    cursor = conn.cursor()

    # First, get schema
    cursor.execute('PRAGMA table_info(nova_jobs)')
    columns = cursor.fetchall()
    print("Nova jobs table schema:")
    print("=" * 80)
    for col in columns:
        print(f"{col['cid']}: {col['name']} ({col['type']})")
    print("\n")

    # Get recent completed batch jobs
    cursor.execute('''
        SELECT *
        FROM nova_jobs
        WHERE batch_mode = 1 AND batch_status = 'Completed'
        ORDER BY completed_at DESC
        LIMIT 20
    ''')

    batch_jobs = [dict(row) for row in cursor.fetchall()]

    print(f"Completed Batch Jobs: {len(batch_jobs)}")
    print("=" * 100)

    if not batch_jobs:
        print("No completed batch jobs found!")
        print("\nNote: Batch jobs are still being processed. Check batch_status in the database.")
        import sys
        sys.exit(0)

    for job in batch_jobs:
        print(f"Job ID: {job['id']}")
        print(f"  Model: {job.get('model')}")
        print(f"  Content Type: {job.get('content_type')}")
        print(f"  Status: {job.get('status')}")
        print(f"  Batch Status: {job.get('batch_status')}")
        print(f"  Cost: ${job.get('cost_usd', 0):.6f}")
        print(f"  Tokens: input={job.get('tokens_input', 0):,}, output={job.get('tokens_output', 0):,}, total={job.get('tokens_total', 0):,}")
        print(f"  Completed: {job.get('completed_at')}")
        print()

    # Get date range for billing query
    created_dates = [job.get('created_at') or job.get('started_at') for job in batch_jobs if job.get('created_at') or job.get('started_at')]
    if not created_dates:
        print("No batch jobs with valid timestamps found.")
        import sys
        sys.exit(0)

    oldest_date = min(datetime.fromisoformat(d).date() for d in created_dates)
    newest_date = max(datetime.fromisoformat(d).date() for d in created_dates)

    print(f"\nBatch jobs date range: {oldest_date} to {newest_date}")

    # Calculate expected costs at standard vs batch rates
    print("\n" + "=" * 100)
    print("COST ANALYSIS:")
    print("=" * 100)

    # Nova pricing (standard rates per 1000 tokens):
    # Nova Lite: Input $0.00006, Output $0.00024
    # Nova Pro: Input $0.0008, Output $0.0032
    # Nova Premier: Input $0.003, Output $0.012
    # Batch discount is 50% off standard rates

    pricing = {
        'lite': {
            'name': 'Nova Lite',
            'input_standard': 0.00006,
            'output_standard': 0.00024,
            'input_batch': 0.00003,
            'output_batch': 0.00012,
        },
        'pro': {
            'name': 'Nova Pro',
            'input_standard': 0.0008,
            'output_standard': 0.0032,
            'input_batch': 0.0004,
            'output_batch': 0.0016,
        },
        'premier': {
            'name': 'Nova Premier',
            'input_standard': 0.003,
            'output_standard': 0.012,
            'input_batch': 0.0015,
            'output_batch': 0.006,
        }
    }

    total_actual = 0
    total_expected_batch = 0
    total_expected_standard = 0

    for job in batch_jobs:
        model = job.get('model', '')
        if model in pricing:
            rates = pricing[model]

            tokens_input = job.get('tokens_input') or 0
            tokens_output = job.get('tokens_output') or 0
            cost_actual = job.get('cost_usd') or 0

            # Prices are per 1000 tokens
            expected_batch = (
                (tokens_input / 1000) * rates['input_batch'] +
                (tokens_output / 1000) * rates['output_batch']
            )
            expected_standard = (
                (tokens_input / 1000) * rates['input_standard'] +
                (tokens_output / 1000) * rates['output_standard']
            )

            total_actual += cost_actual
            total_expected_batch += expected_batch
            total_expected_standard += expected_standard

            print(f"\nJob {job['id']} ({rates['name']}):")
            print(f"  Tokens: {tokens_input:,} input, {tokens_output:,} output")
            print(f"  Actual cost:          ${cost_actual:.6f}")
            print(f"  Expected (batch):     ${expected_batch:.6f}")
            print(f"  Expected (standard):  ${expected_standard:.6f}")
            diff = cost_actual - expected_batch
            print(f"  Difference:           ${abs(diff):.6f} ({'HIGHER' if diff > 0 else 'lower'} than expected)")

    print("\n" + "=" * 100)
    print("TOTALS:")
    print(f"  Actual total:             ${total_actual:.6f}")
    print(f"  Expected batch total:     ${total_expected_batch:.6f}")
    print(f"  Expected standard total:  ${total_expected_standard:.6f}")

    if total_expected_standard > 0:
        savings = total_expected_standard - total_actual
        savings_pct = (savings / total_expected_standard) * 100
        print(f"  Savings vs standard:      ${savings:.6f} ({savings_pct:.1f}%)")

    if total_expected_batch > 0:
        actual_vs_batch_diff = total_actual - total_expected_batch
        actual_vs_batch_pct = (actual_vs_batch_diff / total_expected_batch) * 100
        print(f"\n  Actual vs expected batch: ${actual_vs_batch_diff:+.6f} ({actual_vs_batch_pct:+.2f}%)")

        if abs(actual_vs_batch_pct) < 1:
            print("\n  ✓ CONFIRMED: Charges match batch pricing (50% discount)")
        elif abs(actual_vs_batch_pct) < 5:
            print("\n  ⚠ WARNING: Small discrepancy from batch pricing (within 5%)")
        else:
            print("\n  ✗ ERROR: Large discrepancy from batch pricing!")

    print("=" * 100)
