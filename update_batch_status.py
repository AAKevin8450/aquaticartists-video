"""Manually trigger batch status updates from AWS."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app
from app.database import get_db
from datetime import datetime

# Create Flask app context
app = create_app()

with app.app_context():
    from app.routes.nova_analysis import get_nova_service

    db = get_db()

    # Get pending batch jobs
    pending_jobs = db.get_pending_bedrock_batch_jobs()

    print(f'Updating status for {len(pending_jobs)} batch jobs...')
    print('=' * 100)

    nova_service = get_nova_service()

    for job in pending_jobs:
        batch_job_arn = job['batch_job_arn']
        job_name = job['job_name']

        print(f'\nJob: {job_name}')
        print(f'  Current DB status: {job["status"]}')

        try:
            # Check status from AWS
            status_response = nova_service.get_batch_job_status(batch_job_arn)
            aws_status = status_response['status']

            print(f'  AWS status: {aws_status}')

            # Update database
            db.mark_bedrock_batch_checked(batch_job_arn)
            db.update_bedrock_batch_job(batch_job_arn, {
                'status': aws_status
            })

            # If completed or failed, set completed_at
            if aws_status in ('Completed', 'Failed', 'Stopped'):
                db.update_bedrock_batch_job(batch_job_arn, {
                    'completed_at': datetime.utcnow().isoformat()
                })
                print(f'  Updated DB status to: {aws_status}')

            # Update all associated nova_jobs
            nova_job_ids = job.get('nova_job_ids', [])
            print(f'  Updating {len(nova_job_ids)} associated nova_jobs...')

            for nova_job_id in nova_job_ids:
                db.update_nova_job(nova_job_id, {
                    'batch_status': aws_status
                })

            print(f'  Done!')

        except Exception as e:
            print(f'  ERROR: {e}')

    print('\n' + '=' * 100)
    print('Status update complete!')
    print('\nRe-checking database state...\n')

    # Show updated state
    pending_jobs = db.get_pending_bedrock_batch_jobs()
    print(f'Pending jobs remaining: {len(pending_jobs)}')

    for job in pending_jobs:
        print(f'  {job["job_name"]}: {job["status"]}')
