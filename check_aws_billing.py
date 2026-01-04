"""
Check AWS billing data for Bedrock batch processing charges.
"""
from app.database import get_db
from app.services.billing_service import get_billing_service, BillingError
from datetime import datetime, timedelta
from flask import Flask
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create minimal Flask app for config
app = Flask(__name__)
app.config['BILLING_BUCKET_NAME'] = os.getenv('BILLING_BUCKET_NAME')
app.config['AWS_REGION'] = os.getenv('AWS_REGION', 'us-east-1')
app.config['BILLING_CUR_PREFIX'] = os.getenv('BILLING_CUR_PREFIX', '/hourly_reports/')
app.config['AWS_ACCESS_KEY_ID'] = os.getenv('AWS_ACCESS_KEY_ID')
app.config['AWS_SECRET_ACCESS_KEY'] = os.getenv('AWS_SECRET_ACCESS_KEY')

# Get billing service
billing_service = get_billing_service(app)

if not billing_service:
    print("ERROR: Billing service not configured!")
    print("Set BILLING_BUCKET_NAME in .env")
    exit(1)

# Get last 30 days of billing data
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

print("Fetching AWS billing data...")
print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
print("=" * 100)

try:
    billing_data = billing_service.fetch_cur_data(
        start_date.strftime('%Y-%m-%d'),
        end_date.strftime('%Y-%m-%d')
    )

    print(f"\nTotal cost: ${billing_data['total_cost']:.6f}")
    print(f"Rows processed: {billing_data['rows_processed']:,}")
    print()

    # Look for Bedrock services
    bedrock_services = [s for s in billing_data['services'] if 'Bedrock' in s['service_name']]

    if bedrock_services:
        print("\n" + "=" * 100)
        print("BEDROCK SERVICES:")
        print("=" * 100)

        for service in bedrock_services:
            print(f"\n{service['service_name']}: ${service['cost']:.6f} ({service['percent']:.1f}%)")

            # Show operations for this service
            operations = billing_data.get('operations_by_service', {}).get(service['service_code'], [])

            if operations:
                print("\n  Operations:")
                for op in operations:
                    print(f"    {op['operation_name']}:")
                    print(f"      Usage: {op['usage_amount']:,.2f} {op['usage_type']}")
                    print(f"      Cost: ${op['cost']:.6f} ({op['percent']:.1f}%)")

                    # Check for batch-specific pricing
                    if 'batch' in op['usage_type'].lower() or 'batch' in op['operation'].lower():
                        print(f"      ⚠ BATCH PRICING DETECTED")
    else:
        print("\nNo Bedrock services found in billing data")
        print("\nAll services:")
        for service in billing_data['services'][:10]:
            print(f"  {service['service_name']}: ${service['cost']:.6f}")

    # Also check database for any batch job status
    print("\n" + "=" * 100)
    print("BATCH JOB STATUS FROM DATABASE:")
    print("=" * 100)

    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Count batch jobs by status
        cursor.execute('''
            SELECT batch_status, COUNT(*) as count
            FROM nova_jobs
            WHERE batch_mode = 1
            GROUP BY batch_status
        ''')

        batch_stats = cursor.fetchall()
        if batch_stats:
            print("\nBatch jobs by status:")
            for stat in batch_stats:
                print(f"  {stat['batch_status']}: {stat['count']}")

        # Get bedrock_batch_jobs
        cursor.execute('''
            SELECT *
            FROM bedrock_batch_jobs
            ORDER BY submitted_at DESC
            LIMIT 5
        ''')

        batch_submissions = cursor.fetchall()
        if batch_submissions:
            print("\n\nRecent batch submissions:")
            for sub in batch_submissions:
                print(f"\n  Job: {sub['job_name']}")
                print(f"    ARN: {sub['batch_job_arn']}")
                print(f"    Status: {sub['status']}")
                print(f"    Model: {sub['model']}")
                print(f"    Records: {sub['total_records']}")
                print(f"    Submitted: {sub['submitted_at']}")
        else:
            print("\nNo batch submissions found in bedrock_batch_jobs table")

except BillingError as e:
    print(f"\nERROR: {e}")
except Exception as e:
    print(f"\nUNEXPECTED ERROR: {e}")
    import traceback
    traceback.print_exc()
