"""Async job operations mixin for database (rescan and import jobs)."""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any


class AsyncJobsMixin:
    """Mixin providing rescan and import job CRUD operations."""

    # Rescan Jobs methods
    def create_rescan_job(self, job_id: str, directory_path: str, recursive: bool = True) -> int:
        """Create a new rescan job."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO rescan_jobs (job_id, directory_path, recursive, status)
                VALUES (?, ?, ?, 'SUBMITTED')
            ''', (job_id, directory_path, recursive))
            return cursor.lastrowid

    def get_rescan_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get rescan job by job_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM rescan_jobs WHERE job_id = ?', (job_id,))
            row = cursor.fetchone()
            if row:
                job = dict(row)
                # Parse JSON fields
                if job.get('results'):
                    job['results'] = json.loads(job['results'])
                return job
            return None

    def update_rescan_job(self, job_id: str, update_data: Dict[str, Any]):
        """Update rescan job with arbitrary fields."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            fields = []
            values = []
            for key, value in update_data.items():
                fields.append(f"{key} = ?")
                # JSON fields
                if key == 'results':
                    values.append(json.dumps(value) if value is not None else None)
                else:
                    values.append(value)

            values.append(job_id)
            query = f"UPDATE rescan_jobs SET {', '.join(fields)} WHERE job_id = ?"
            cursor.execute(query, values)

    def update_rescan_job_progress(self, job_id: str, files_scanned: int,
                                   total_files: int = None, current_operation: str = None):
        """Update rescan job progress."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Calculate progress percentage
            if total_files and total_files > 0:
                progress_percent = int((files_scanned / total_files) * 100)
            else:
                progress_percent = 0

            updates = ['files_scanned = ?', 'progress_percent = ?']
            values = [files_scanned, progress_percent]

            if total_files is not None:
                updates.append('total_files = ?')
                values.append(total_files)

            if current_operation is not None:
                updates.append('current_operation = ?')
                values.append(current_operation)

            values.append(job_id)
            query = f"UPDATE rescan_jobs SET {', '.join(updates)} WHERE job_id = ?"
            cursor.execute(query, values)

    def update_rescan_job_status(self, job_id: str, status: str):
        """Update rescan job status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE rescan_jobs SET status = ? WHERE job_id = ?',
                         (status, job_id))

    def complete_rescan_job(self, job_id: str, results: Dict[str, Any],
                           error_message: str = None):
        """Mark rescan job as completed with results."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            status = 'FAILED' if error_message else 'SUCCEEDED'
            cursor.execute('''
                UPDATE rescan_jobs
                SET status = ?,
                    results = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    error_message = ?,
                    progress_percent = 100
                WHERE job_id = ?
            ''', (status, json.dumps(results), error_message, job_id))

    def cancel_rescan_job(self, job_id: str):
        """Cancel a rescan job."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE rescan_jobs
                SET status = 'CANCELLED',
                    cancelled = 1,
                    completed_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
            ''', (job_id,))

    def is_rescan_job_cancelled(self, job_id: str) -> bool:
        """Check if a rescan job has been cancelled."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT cancelled FROM rescan_jobs WHERE job_id = ?', (job_id,))
            row = cursor.fetchone()
            return bool(row['cancelled']) if row else False

    # Import Jobs methods
    def create_import_job(self, job_id: str, directory_path: str, recursive: bool = True) -> int:
        """Create a new import job."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO import_jobs (job_id, directory_path, recursive, status)
                VALUES (?, ?, ?, 'SUBMITTED')
            ''', (job_id, directory_path, recursive))
            return cursor.lastrowid

    def get_import_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get import job by job_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM import_jobs WHERE job_id = ?', (job_id,))
            row = cursor.fetchone()
            if row:
                job = dict(row)
                # Parse JSON fields
                if job.get('errors'):
                    job['errors'] = json.loads(job['errors'])
                if job.get('results'):
                    job['results'] = json.loads(job['results'])
                return job
            return None

    def update_import_job(self, job_id: str, update_data: Dict[str, Any]):
        """Update import job with arbitrary fields."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            fields = []
            values = []
            for key, value in update_data.items():
                fields.append(f"{key} = ?")
                # JSON fields
                if key in ('errors', 'results'):
                    values.append(json.dumps(value) if value is not None else None)
                else:
                    values.append(value)

            values.append(job_id)
            query = f"UPDATE import_jobs SET {', '.join(fields)} WHERE job_id = ?"
            cursor.execute(query, values)

    def update_import_job_progress(self, job_id: str, files_scanned: int = None,
                                   files_imported: int = None, files_skipped_existing: int = None,
                                   files_skipped_unsupported: int = None, total_files: int = None,
                                   current_operation: str = None):
        """Update import job progress."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            updates = []
            values = []

            if files_scanned is not None:
                updates.append('files_scanned = ?')
                values.append(files_scanned)

            if files_imported is not None:
                updates.append('files_imported = ?')
                values.append(files_imported)

            if files_skipped_existing is not None:
                updates.append('files_skipped_existing = ?')
                values.append(files_skipped_existing)

            if files_skipped_unsupported is not None:
                updates.append('files_skipped_unsupported = ?')
                values.append(files_skipped_unsupported)

            if total_files is not None:
                updates.append('total_files = ?')
                values.append(total_files)

            # Calculate progress percentage
            if total_files and total_files > 0 and files_scanned is not None:
                progress_percent = int((files_scanned / total_files) * 100)
                updates.append('progress_percent = ?')
                values.append(progress_percent)

            if current_operation is not None:
                updates.append('current_operation = ?')
                values.append(current_operation)

            if updates:
                values.append(job_id)
                query = f"UPDATE import_jobs SET {', '.join(updates)} WHERE job_id = ?"
                cursor.execute(query, values)

    def update_import_job_status(self, job_id: str, status: str):
        """Update import job status."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE import_jobs SET status = ? WHERE job_id = ?',
                         (status, job_id))

    def complete_import_job(self, job_id: str, results: Dict[str, Any],
                           error_message: str = None):
        """Mark import job as completed with results."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            status = 'FAILED' if error_message else 'SUCCEEDED'
            cursor.execute('''
                UPDATE import_jobs
                SET status = ?,
                    results = ?,
                    completed_at = CURRENT_TIMESTAMP,
                    error_message = ?,
                    progress_percent = 100
                WHERE job_id = ?
            ''', (status, json.dumps(results), error_message, job_id))

    def cancel_import_job(self, job_id: str):
        """Cancel an import job."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE import_jobs
                SET status = 'CANCELLED',
                    cancelled = 1,
                    completed_at = CURRENT_TIMESTAMP
                WHERE job_id = ?
            ''', (job_id,))

    def is_import_job_cancelled(self, job_id: str) -> bool:
        """Check if an import job has been cancelled."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT cancelled FROM import_jobs WHERE job_id = ?', (job_id,))
            row = cursor.fetchone()
            return bool(row['cancelled']) if row else False
