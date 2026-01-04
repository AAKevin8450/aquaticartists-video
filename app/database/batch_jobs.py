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
