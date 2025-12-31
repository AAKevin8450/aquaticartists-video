"""Nova job operations mixin for database."""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any


class NovaJobsMixin:
    """Mixin providing Nova analysis job CRUD operations."""

    def create_nova_job(self, analysis_job_id: int, model: str, analysis_types: list,
                       user_options: dict = None) -> int:
        """Create a new Nova analysis job."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO nova_jobs (analysis_job_id, model, analysis_types, user_options, status)
                VALUES (?, ?, ?, ?, 'SUBMITTED')
            ''', (analysis_job_id, model, json.dumps(analysis_types), json.dumps(user_options or {})))
            return cursor.lastrowid

    def get_nova_job(self, nova_job_id: int) -> Optional[Dict[str, Any]]:
        """Get Nova job by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM nova_jobs WHERE id = ?', (nova_job_id,))
            row = cursor.fetchone()
            if row:
                job = dict(row)
                # Parse JSON fields
                if job.get('analysis_types'):
                    job['analysis_types'] = json.loads(job['analysis_types'])
                if job.get('user_options'):
                    job['user_options'] = json.loads(job['user_options'])
                if job.get('summary_result'):
                    job['summary_result'] = json.loads(job['summary_result'])
                if job.get('chapters_result'):
                    job['chapters_result'] = json.loads(job['chapters_result'])
                if job.get('elements_result'):
                    job['elements_result'] = json.loads(job['elements_result'])
                if job.get('waterfall_classification_result'):
                    job['waterfall_classification_result'] = json.loads(job['waterfall_classification_result'])
                return job
            return None

    def get_nova_job_by_analysis_job(self, analysis_job_id: int) -> Optional[Dict[str, Any]]:
        """Get Nova job by analysis_job_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM nova_jobs WHERE analysis_job_id = ?', (analysis_job_id,))
            row = cursor.fetchone()
            if row:
                job = dict(row)
                # Parse JSON fields
                if job.get('analysis_types'):
                    job['analysis_types'] = json.loads(job['analysis_types'])
                if job.get('user_options'):
                    job['user_options'] = json.loads(job['user_options'])
                if job.get('summary_result'):
                    job['summary_result'] = json.loads(job['summary_result'])
                if job.get('chapters_result'):
                    job['chapters_result'] = json.loads(job['chapters_result'])
                if job.get('elements_result'):
                    job['elements_result'] = json.loads(job['elements_result'])
                if job.get('waterfall_classification_result'):
                    job['waterfall_classification_result'] = json.loads(job['waterfall_classification_result'])
                return job
            return None

    def update_nova_job(self, nova_job_id: int, update_data: Dict[str, Any]):
        """Update Nova job with arbitrary fields."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Build UPDATE query dynamically
            fields = []
            values = []
            for key, value in update_data.items():
                fields.append(f"{key} = ?")
                # JSON fields
                if key in ('summary_result', 'chapters_result', 'elements_result', 'waterfall_classification_result', 'user_options'):
                    values.append(json.dumps(value) if value is not None else None)
                else:
                    values.append(value)

            values.append(nova_job_id)
            query = f"UPDATE nova_jobs SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, values)

    def update_nova_job_status(self, nova_job_id: int, status: str, progress_percent: int = None):
        """Update Nova job status and progress."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if progress_percent is not None:
                cursor.execute('''
                    UPDATE nova_jobs
                    SET status = ?, progress_percent = ?
                    WHERE id = ?
                ''', (status, progress_percent, nova_job_id))
            else:
                cursor.execute('''
                    UPDATE nova_jobs SET status = ? WHERE id = ?
                ''', (status, nova_job_id))

    def update_nova_job_started_at(self, nova_job_id: int):
        """Update Nova job started_at timestamp."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE nova_jobs SET started_at = CURRENT_TIMESTAMP WHERE id = ?
            ''', (nova_job_id,))

    def update_nova_job_completed_at(self, nova_job_id: int):
        """Update Nova job completed_at timestamp."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE nova_jobs SET completed_at = CURRENT_TIMESTAMP WHERE id = ?
            ''', (nova_job_id,))

    def update_nova_job_chunk_progress(self, nova_job_id: int, current_chunk: int,
                                      total_chunks: int, status_message: str = None):
        """Update Nova job chunk progress for multi-chunk processing."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Calculate progress percentage based on chunks
            progress_percent = int((current_chunk / total_chunks) * 100) if total_chunks > 0 else 0

            # Update chunk-specific metadata
            update_data = {
                'current_chunk': current_chunk,
                'chunk_count': total_chunks,
                'progress_percent': progress_percent,
                'is_chunked': 1 if total_chunks > 1 else 0
            }

            if status_message:
                update_data['chunk_status_message'] = status_message

            # Build UPDATE query dynamically
            fields = [f"{key} = ?" for key in update_data.keys()]
            values = list(update_data.values())
            values.append(nova_job_id)

            query = f"UPDATE nova_jobs SET {', '.join(fields)} WHERE id = ?"
            cursor.execute(query, values)

    def list_nova_jobs(self, status: Optional[str] = None, model: Optional[str] = None,
                      limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List Nova jobs with optional filters."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM nova_jobs WHERE 1=1'
            params = []

            if status:
                query += ' AND status = ?'
                params.append(status)

            if model:
                query += ' AND model = ?'
                params.append(model)

            query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)
            jobs = []
            for row in cursor.fetchall():
                job = dict(row)
                # Parse JSON fields
                if job.get('analysis_types'):
                    job['analysis_types'] = json.loads(job['analysis_types'])
                if job.get('user_options'):
                    job['user_options'] = json.loads(job['user_options'])
                jobs.append(job)
            return jobs

    def delete_nova_job(self, nova_job_id: int) -> bool:
        """Delete a Nova job."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM nova_jobs WHERE id = ?', (nova_job_id,))
            return cursor.rowcount > 0

    def get_nova_jobs_by_file(self, file_id: int) -> List[Dict[str, Any]]:
        """Get all Nova jobs for a specific file."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT nj.*
                FROM nova_jobs nj
                JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id
                WHERE aj.file_id = ?
                ORDER BY nj.created_at DESC
            ''', (file_id,))

            jobs = []
            for row in cursor.fetchall():
                job = dict(row)
                # Parse JSON fields
                if job.get('analysis_types'):
                    job['analysis_types'] = json.loads(job['analysis_types'])
                if job.get('user_options'):
                    job['user_options'] = json.loads(job['user_options'])
                if job.get('summary_result'):
                    job['summary_result'] = json.loads(job['summary_result'])
                if job.get('chapters_result'):
                    job['chapters_result'] = json.loads(job['chapters_result'])
                if job.get('elements_result'):
                    job['elements_result'] = json.loads(job['elements_result'])
                if job.get('waterfall_classification_result'):
                    job['waterfall_classification_result'] = json.loads(job['waterfall_classification_result'])
                jobs.append(job)
            return jobs
