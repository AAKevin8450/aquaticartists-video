"""
Database management for SQLite with schema initialization and helper functions.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any


class Database:
    """SQLite database manager."""

    def __init__(self, db_path: str | Path):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self._ensure_db_directory()
        self._init_db()

    def _ensure_db_directory(self):
        """Ensure database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row  # Enable dict-like access to rows
        # Enable WAL mode for better concurrent access
        conn.execute('PRAGMA journal_mode=WAL')
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Files table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    s3_key TEXT UNIQUE NOT NULL,
                    file_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSON
                )
            ''')

            # Analysis jobs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    file_id INTEGER NOT NULL,
                    analysis_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'SUBMITTED',
                    parameters JSON,
                    results JSON,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
                )
            ''')

            # Face collections table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS face_collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_id TEXT UNIQUE NOT NULL,
                    collection_arn TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    face_count INTEGER DEFAULT 0,
                    metadata JSON
                )
            ''')

            # Transcripts table (redesigned for multi-model support)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    modified_time REAL NOT NULL,
                    model_name TEXT NOT NULL,
                    language TEXT,
                    transcript_text TEXT,
                    segments TEXT,
                    word_timestamps TEXT,
                    confidence_score REAL,
                    processing_time REAL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    UNIQUE(file_path, file_size, modified_time, model_name)
                )
            ''')

            # Create indexes for better query performance
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_files_type
                ON files(file_type)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_jobs_status
                ON analysis_jobs(status)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_jobs_file_id
                ON analysis_jobs(file_id)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_transcripts_status
                ON transcripts(status)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_transcripts_model_name
                ON transcripts(model_name)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_transcripts_language
                ON transcripts(language)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_transcripts_file_name
                ON transcripts(file_name)
            ''')

    # File operations
    def create_file(self, filename: str, s3_key: str, file_type: str,
                    size_bytes: int, content_type: str, metadata: Optional[Dict] = None) -> int:
        """Create a new file record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO files (filename, s3_key, file_type, size_bytes, content_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (filename, s3_key, file_type, size_bytes, content_type, json.dumps(metadata or {})))
            return cursor.lastrowid

    def get_file(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Get file by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM files WHERE id = ?', (file_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_file_by_s3_key(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """Get file by S3 key."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM files WHERE s3_key = ?', (s3_key,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_files(self, file_type: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List files with optional type filter."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if file_type:
                cursor.execute('''
                    SELECT * FROM files WHERE file_type = ?
                    ORDER BY uploaded_at DESC LIMIT ? OFFSET ?
                ''', (file_type, limit, offset))
            else:
                cursor.execute('''
                    SELECT * FROM files ORDER BY uploaded_at DESC LIMIT ? OFFSET ?
                ''', (limit, offset))
            return [dict(row) for row in cursor.fetchall()]

    def delete_file(self, file_id: int) -> bool:
        """Delete file record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
            return cursor.rowcount > 0

    # Analysis job operations
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
                    job['parameters'] = json.loads(job['parameters'])
                if job.get('results'):
                    job['results'] = json.loads(job['results'])
                return job
            return None

    def update_job_status(self, job_id: str, status: str, results: Optional[Dict] = None,
                         error_message: Optional[str] = None):
        """Update job status and results."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status in ('SUCCEEDED', 'FAILED'):
                cursor.execute('''
                    UPDATE analysis_jobs
                    SET status = ?, results = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE job_id = ?
                ''', (status, json.dumps(results) if results else None, error_message, job_id))
            else:
                cursor.execute('''
                    UPDATE analysis_jobs SET status = ? WHERE job_id = ?
                ''', (status, job_id))

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
                    job['parameters'] = json.loads(job['parameters'])
                if job.get('results'):
                    job['results'] = json.loads(job['results'])
                jobs.append(job)
            return jobs

    def delete_job(self, job_id: str) -> bool:
        """Delete job record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM analysis_jobs WHERE job_id = ?', (job_id,))
            return cursor.rowcount > 0

    # Face collection operations
    def create_collection(self, collection_id: str, collection_arn: str,
                         metadata: Optional[Dict] = None) -> int:
        """Create a new face collection record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO face_collections (collection_id, collection_arn, metadata)
                VALUES (?, ?, ?)
            ''', (collection_id, collection_arn, json.dumps(metadata or {})))
            return cursor.lastrowid

    def get_collection(self, collection_id: str) -> Optional[Dict[str, Any]]:
        """Get collection by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM face_collections WHERE collection_id = ?', (collection_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_collections(self) -> List[Dict[str, Any]]:
        """List all collections."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM face_collections ORDER BY created_at DESC')
            return [dict(row) for row in cursor.fetchall()]

    def update_collection_face_count(self, collection_id: str, face_count: int):
        """Update face count for a collection."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE face_collections SET face_count = ? WHERE collection_id = ?
            ''', (face_count, collection_id))

    def delete_collection(self, collection_id: str) -> bool:
        """Delete collection record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM face_collections WHERE collection_id = ?', (collection_id,))
            return cursor.rowcount > 0

    # Transcript operations
    def create_transcript(self, file_path: str, file_name: str, file_size: int,
                         modified_time: float, model_name: str) -> int:
        """Create a new transcript record."""
        from datetime import datetime
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transcripts (file_path, file_name, file_size, modified_time, model_name, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
            ''', (file_path, file_name, file_size, modified_time, model_name, datetime.now().isoformat()))
            return cursor.lastrowid

    def get_transcript(self, transcript_id: int) -> Optional[Dict[str, Any]]:
        """Get transcript by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM transcripts WHERE id = ?', (transcript_id,))
            row = cursor.fetchone()
            if row:
                transcript = dict(row)
                # Parse JSON fields
                for field in ['segments', 'word_timestamps']:
                    if transcript.get(field):
                        transcript[field] = json.loads(transcript[field])
                return transcript
            return None

    def get_transcript_by_file_info(self, file_path: str, file_size: int,
                                    modified_time: float, model_name: str) -> Optional[Dict[str, Any]]:
        """
        Get transcript by file info and model name.
        Allows multiple transcripts for same file with different models.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM transcripts
                WHERE file_path = ? AND file_size = ? AND modified_time = ? AND model_name = ?
            ''', (file_path, file_size, modified_time, model_name))
            row = cursor.fetchone()
            if row:
                transcript = dict(row)
                # Parse JSON fields
                for field in ['segments', 'word_timestamps']:
                    if transcript.get(field):
                        transcript[field] = json.loads(transcript[field])
                return transcript
            return None

    def update_transcript_status(self, transcript_id: int, status: str,
                                transcript_text: Optional[str] = None,
                                segments: Optional[List] = None,
                                word_timestamps: Optional[List] = None,
                                language: Optional[str] = None,
                                confidence_score: Optional[float] = None,
                                processing_time: Optional[float] = None,
                                error_message: Optional[str] = None):
        """Update transcript status and results."""
        from datetime import datetime
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status == 'COMPLETED':
                cursor.execute('''
                    UPDATE transcripts
                    SET status = ?, transcript_text = ?, segments = ?,
                        word_timestamps = ?, language = ?,
                        confidence_score = ?, processing_time = ?,
                        completed_at = ?
                    WHERE id = ?
                ''', (status, transcript_text,
                     json.dumps(segments) if segments else None,
                     json.dumps(word_timestamps) if word_timestamps else None,
                     language, confidence_score, processing_time,
                     datetime.now().isoformat(), transcript_id))
            elif status == 'FAILED':
                cursor.execute('''
                    UPDATE transcripts
                    SET status = ?, error_message = ?, completed_at = ?
                    WHERE id = ?
                ''', (status, error_message, datetime.now().isoformat(), transcript_id))
            else:
                cursor.execute('''
                    UPDATE transcripts SET status = ? WHERE id = ?
                ''', (status, transcript_id))

    def list_transcripts(self, status: Optional[str] = None, model: Optional[str] = None,
                        language: Optional[str] = None, search: Optional[str] = None,
                        from_date: Optional[str] = None, to_date: Optional[str] = None,
                        sort_by: str = 'created_at', sort_order: str = 'desc',
                        limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List transcripts with advanced filtering and search."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Build query dynamically with filters
            query = 'SELECT * FROM transcripts WHERE 1=1'
            params = []

            if status:
                query += ' AND status = ?'
                params.append(status)

            if model:
                query += ' AND model_name = ?'
                params.append(model)

            if language:
                query += ' AND language = ?'
                params.append(language)

            if search:
                query += ' AND (file_name LIKE ? OR file_path LIKE ? OR transcript_text LIKE ?)'
                search_pattern = f'%{search}%'
                params.extend([search_pattern, search_pattern, search_pattern])

            if from_date:
                query += ' AND created_at >= ?'
                params.append(from_date)

            if to_date:
                query += ' AND created_at <= ?'
                params.append(to_date)

            # Add sorting
            valid_sort_fields = ['created_at', 'file_name', 'file_size', 'processing_time', 'model_name']
            if sort_by in valid_sort_fields:
                sort_direction = 'ASC' if sort_order.lower() == 'asc' else 'DESC'
                query += f' ORDER BY {sort_by} {sort_direction}'
            else:
                query += ' ORDER BY created_at DESC'

            query += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)

            transcripts = []
            for row in cursor.fetchall():
                transcript = dict(row)
                # Parse JSON fields
                for field in ['segments', 'word_timestamps']:
                    if transcript.get(field):
                        transcript[field] = json.loads(transcript[field])
                transcripts.append(transcript)
            return transcripts

    def delete_transcript(self, transcript_id: int) -> bool:
        """Delete transcript record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM transcripts WHERE id = ?', (transcript_id,))
            return cursor.rowcount > 0

    def count_transcripts(self, status: Optional[str] = None, model: Optional[str] = None,
                         language: Optional[str] = None, search: Optional[str] = None,
                         from_date: Optional[str] = None, to_date: Optional[str] = None) -> int:
        """Count transcripts with filtering support."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Build query dynamically with filters
            query = 'SELECT COUNT(*) FROM transcripts WHERE 1=1'
            params = []

            if status:
                query += ' AND status = ?'
                params.append(status)

            if model:
                query += ' AND model_name = ?'
                params.append(model)

            if language:
                query += ' AND language = ?'
                params.append(language)

            if search:
                query += ' AND (file_name LIKE ? OR file_path LIKE ? OR transcript_text LIKE ?)'
                search_pattern = f'%{search}%'
                params.extend([search_pattern, search_pattern, search_pattern])

            if from_date:
                query += ' AND created_at >= ?'
                params.append(from_date)

            if to_date:
                query += ' AND created_at <= ?'
                params.append(to_date)

            cursor.execute(query, params)
            return cursor.fetchone()[0]

    def get_available_models(self) -> List[str]:
        """Get list of all model names that have transcripts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT model_name FROM transcripts ORDER BY model_name')
            return [row[0] for row in cursor.fetchall()]

    def get_available_languages(self) -> List[str]:
        """Get list of all languages that have transcripts."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT language FROM transcripts WHERE language IS NOT NULL ORDER BY language')
            return [row[0] for row in cursor.fetchall()]


# Global database instance (will be initialized in app factory)
db: Optional[Database] = None


def init_db(app):
    """Initialize database with Flask app."""
    global db
    db_path = app.config.get('DATABASE_PATH', 'data/app.db')
    db = Database(db_path)
    return db


def get_db() -> Database:
    """Get database instance."""
    if db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return db
