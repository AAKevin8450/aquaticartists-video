"""Analysis job operations mixin for database."""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any


class AnalysisJobsMixin:
    """Mixin providing analysis job CRUD operations."""

    def create_job(self, job_id: str, file_id: int, analysis_type: str,
                   parameters: Optional[Dict] = None) -> int:
        """Create a new analysis job record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO analysis_jobs (job_id, file_id, analysis_type, status, parameters)
                VALUES (?, ?, ?, 'SUBMITTED', ?)
            ''', (job_id, file_id, analysis_type, json.dumps(parameters or {})))
            return cursor.lastrowid

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job by job ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM analysis_jobs WHERE job_id = ?', (job_id,))
            row = cursor.fetchone()
            if row:
                job = dict(row)
                # Parse JSON fields
                if job.get('parameters'):
                    job['parameters'] = self._parse_json_field(job['parameters'], max_depth=2)
                if job.get('results'):
                    job['results'] = self._parse_json_field(job['results'], max_depth=2)
                return job
            return None

    def get_analysis_job(self, analysis_job_id: int) -> Optional[Dict[str, Any]]:
        """Get analysis job by database ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM analysis_jobs WHERE id = ?', (analysis_job_id,))
            row = cursor.fetchone()
            if row:
                job = dict(row)
                if job.get('parameters'):
                    job['parameters'] = self._parse_json_field(job['parameters'], max_depth=2)
                if job.get('results'):
                    job['results'] = self._parse_json_field(job['results'], max_depth=2)
                return job
            return None

    def update_job_status(self, job_id: str, status: str, results: Optional[Dict] = None,
                         error_message: Optional[str] = None):
        """Update job status and results."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            normalized_status = 'COMPLETED' if status == 'SUCCEEDED' else status
            if normalized_status in ('COMPLETED', 'FAILED'):
                cursor.execute('''
                    UPDATE analysis_jobs
                    SET status = ?, results = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE job_id = ?
                ''', (normalized_status, json.dumps(results) if results else None, error_message, job_id))
            else:
                cursor.execute('''
                    UPDATE analysis_jobs SET status = ? WHERE job_id = ?
                ''', (normalized_status, job_id))

    def list_jobs(self, file_id: Optional[int] = None, status: Optional[str] = None,
                  analysis_type: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List jobs with optional filters."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM analysis_jobs WHERE 1=1'
            params = []

            if file_id:
                query += ' AND file_id = ?'
                params.append(file_id)
            if status:
                query += ' AND status = ?'
                params.append(status)
            if analysis_type:
                query += ' AND analysis_type = ?'
                params.append(analysis_type)

            query += ' ORDER BY started_at DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)
            jobs = []
            for row in cursor.fetchall():
                job = dict(row)
                if job.get('parameters'):
                    job['parameters'] = self._parse_json_field(job['parameters'], max_depth=2)
                if job.get('results'):
                    job['results'] = self._parse_json_field(job['results'], max_depth=2)
                jobs.append(job)
            return jobs

    def delete_job(self, job_id: str) -> bool:
        """Delete job record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM analysis_jobs WHERE job_id = ?', (job_id,))
            return cursor.rowcount > 0

    def create_analysis_job(self, file_id: int, job_id: str, analysis_type: str,
                           status: str = 'SUBMITTED', parameters: Optional[Dict] = None) -> int:
        """Create a new analysis job (wrapper around create_job for compatibility)."""
        return self.create_job(job_id, file_id, analysis_type, parameters)

    def update_analysis_job(self, job_id: int, status: str = None, results: Optional[Dict] = None,
                           error_message: Optional[str] = None):
        """Update analysis job status (handles both job_id string and int)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Check if job_id is an integer (database ID) or string (job_id field)
            if isinstance(job_id, int):
                # It's the database ID
                normalized_status = 'COMPLETED' if status == 'SUCCEEDED' else status
                if normalized_status in ('COMPLETED', 'FAILED'):
                    cursor.execute('''
                        UPDATE analysis_jobs
                        SET status = ?, results = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (normalized_status, json.dumps(results) if results else None, error_message, job_id))
                elif status:
                    cursor.execute('''
                        UPDATE analysis_jobs SET status = ? WHERE id = ?
                    ''', (normalized_status, job_id))
            else:
                # It's the job_id string
                normalized_status = 'COMPLETED' if status == 'SUCCEEDED' else status
                if normalized_status in ('COMPLETED', 'FAILED'):
                    cursor.execute('''
                        UPDATE analysis_jobs
                        SET status = ?, results = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP
                        WHERE job_id = ?
                    ''', (normalized_status, json.dumps(results) if results else None, error_message, job_id))
                elif status:
                    cursor.execute('''
                        UPDATE analysis_jobs SET status = ? WHERE job_id = ?
                    ''', (normalized_status, job_id))
