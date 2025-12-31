"""
Base database operations and connection management.
"""
import sqlite3
import json
import os
import struct
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, List, Dict, Any


class DatabaseBase:
    """Base class with connection and schema management."""

    def __init__(self, db_path: str | Path):
        """Initialize database connection."""
        self.db_path = Path(db_path)
        self._ensure_db_directory()
        self._init_db()

    def _ensure_db_directory(self):
        """Ensure database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_embedding_dimension(self) -> int:
        """Get configured embedding dimension."""
        try:
            return int(os.getenv('NOVA_EMBED_DIMENSION', '1024'))
        except ValueError:
            return 1024

    def _load_vector_extension(self, conn: sqlite3.Connection) -> bool:
        """Attempt to load the SQLite vector extension for this connection."""
        try:
            conn.enable_load_extension(True)
        except Exception:
            pass

        loaded = False
        try:
            import sqlite_vec  # type: ignore
            sqlite_vec.load(conn)
            loaded = True
        except Exception:
            loaded = False

        if not loaded:
            vec_path = os.getenv('SQLITE_VEC_PATH')
            try:
                if vec_path:
                    conn.load_extension(vec_path)
                    loaded = True
            except Exception:
                loaded = False

        if not loaded:
            try:
                conn.load_extension('vec0')
                loaded = True
            except Exception:
                loaded = False

        try:
            conn.enable_load_extension(False)
        except Exception:
            pass

        return loaded

    def _ensure_embedding_tables(self, conn: sqlite3.Connection):
        """Ensure embedding tables exist (requires vector extension for vec0)."""
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nova_embedding_metadata (
                rowid INTEGER PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                file_id INTEGER,
                model_name TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        try:
            cursor.execute('ALTER TABLE nova_embedding_metadata ADD COLUMN file_id INTEGER')
        except sqlite3.OperationalError:
            pass
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_nova_embedding_source
            ON nova_embedding_metadata(source_type, source_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_nova_embedding_file
            ON nova_embedding_metadata(file_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_nova_embedding_model
            ON nova_embedding_metadata(model_name)
        ''')
        cursor.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS ux_nova_embedding_unique
            ON nova_embedding_metadata(source_type, source_id, model_name, content_hash)
        ''')

        if self._load_vector_extension(conn):
            dimension = self._get_embedding_dimension()
            cursor.execute(f'''
                CREATE VIRTUAL TABLE IF NOT EXISTS nova_embeddings
                USING vec0(embedding float[{dimension}])
            ''')

    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row  # Enable dict-like access to rows
        # Enable WAL mode for better concurrent access
        conn.execute('PRAGMA journal_mode=WAL')
        # Enable foreign key constraints for CASCADE deletes
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            self._load_vector_extension(conn)
        except Exception:
            pass
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
                    s3_key TEXT UNIQUE,
                    file_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata JSON,
                    is_proxy BOOLEAN DEFAULT 0,
                    source_file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
                    local_path TEXT,
                    resolution_width INTEGER,
                    resolution_height INTEGER,
                    frame_rate REAL,
                    codec_video TEXT,
                    codec_audio TEXT,
                    duration_seconds REAL,
                    bitrate INTEGER
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
                    character_count INTEGER,
                    word_count INTEGER,
                    duration_seconds REAL,
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

            # Add columns if they don't exist (migration for existing databases)
            migration_columns = [
                ('transcripts', 'character_count', 'INTEGER'),
                ('transcripts', 'word_count', 'INTEGER'),
                ('transcripts', 'duration_seconds', 'REAL'),
                ('transcripts', 'resolution_width', 'INTEGER'),
                ('transcripts', 'resolution_height', 'INTEGER'),
                ('transcripts', 'frame_rate', 'REAL'),
                ('transcripts', 'codec_video', 'TEXT'),
                ('transcripts', 'codec_audio', 'TEXT'),
                ('transcripts', 'bitrate', 'INTEGER'),
                ('transcripts', 'transcript_summary', 'TEXT'),
            ]
            for table, column, col_type in migration_columns:
                try:
                    cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Create indexes for better query performance
            indexes = [
                ('idx_files_type', 'files', 'file_type'),
                ('idx_files_uploaded_at', 'files', 'uploaded_at DESC'),
                ('idx_files_size_bytes', 'files', 'size_bytes DESC'),
                ('idx_jobs_status', 'analysis_jobs', 'status'),
                ('idx_jobs_file_id', 'analysis_jobs', 'file_id'),
                ('idx_transcripts_status', 'transcripts', 'status'),
                ('idx_transcripts_model_name', 'transcripts', 'model_name'),
                ('idx_transcripts_language', 'transcripts', 'language'),
                ('idx_transcripts_file_name', 'transcripts', 'file_name'),
                ('idx_transcripts_file_path', 'transcripts', 'file_path'),
            ]
            for idx_name, table, columns in indexes:
                cursor.execute(f'''
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {table}({columns})
                ''')

            # Nova jobs table (for Amazon Bedrock Nova intelligent video analysis)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS nova_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_job_id INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    analysis_types TEXT NOT NULL,
                    user_options TEXT,
                    status TEXT NOT NULL DEFAULT 'SUBMITTED',
                    summary_result TEXT,
                    chapters_result TEXT,
                    elements_result TEXT,
                    waterfall_classification_result TEXT,
                    search_metadata TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    progress_percent INTEGER DEFAULT 0,
                    current_chunk INTEGER,
                    total_chunks INTEGER,
                    estimated_cost REAL,
                    actual_cost REAL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    processing_time REAL,
                    error_message TEXT,
                    FOREIGN KEY (analysis_job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE
                )
            ''')
            nova_job_columns = [
                ('nova_jobs', 'waterfall_classification_result', 'TEXT'),
                ('nova_jobs', 'search_metadata', 'TEXT'),
                ('nova_jobs', 'raw_response', 'TEXT'),
                ('nova_jobs', 'content_type', "VARCHAR(10) DEFAULT 'video'"),
                ('nova_jobs', 'description_result', 'TEXT'),
            ]
            for table, column, col_type in nova_job_columns:
                try:
                    cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {col_type}')
                except sqlite3.OperationalError:
                    pass

            # Rescan jobs table (for folder rescan operations with progress tracking)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rescan_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    directory_path TEXT NOT NULL,
                    recursive BOOLEAN DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'SUBMITTED',
                    current_operation TEXT,
                    files_scanned INTEGER DEFAULT 0,
                    total_files INTEGER DEFAULT 0,
                    progress_percent INTEGER DEFAULT 0,
                    results JSON,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    cancelled BOOLEAN DEFAULT 0
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_rescan_jobs_status
                ON rescan_jobs(status)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_rescan_jobs_started_at
                ON rescan_jobs(started_at DESC)
            ''')

            # Import jobs table (for directory import operations with progress tracking)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS import_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    directory_path TEXT NOT NULL,
                    recursive BOOLEAN DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'SUBMITTED',
                    current_operation TEXT,
                    files_scanned INTEGER DEFAULT 0,
                    files_imported INTEGER DEFAULT 0,
                    files_skipped_existing INTEGER DEFAULT 0,
                    files_skipped_unsupported INTEGER DEFAULT 0,
                    total_files INTEGER DEFAULT 0,
                    progress_percent INTEGER DEFAULT 0,
                    errors JSON,
                    results JSON,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    error_message TEXT,
                    cancelled BOOLEAN DEFAULT 0
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_import_jobs_status
                ON import_jobs(status)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_import_jobs_started_at
                ON import_jobs(started_at DESC)
            ''')

            # Search optimization indexes
            search_indexes = [
                ('idx_files_filename', 'files', 'filename'),
                ('idx_files_local_path', 'files', 'local_path'),
                ('idx_jobs_analysis_type', 'analysis_jobs', 'analysis_type'),
                ('idx_jobs_completed_at', 'analysis_jobs', 'completed_at DESC'),
                ('idx_nova_jobs_status', 'nova_jobs', 'status'),
                ('idx_nova_jobs_completed_at', 'nova_jobs', 'completed_at DESC'),
                ('idx_nova_jobs_analysis_job_id', 'nova_jobs', 'analysis_job_id'),
                ('idx_transcripts_completed_at', 'transcripts', 'completed_at DESC'),
                ('idx_collections_created_at', 'face_collections', 'created_at DESC'),
            ]
            for idx_name, table, columns in search_indexes:
                cursor.execute(f'''
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {table}({columns})
                ''')

            # Embedding tables (requires vector extension for vec0 virtual table)
            self._ensure_embedding_tables(conn)

    def _parse_json_field(self, value: Any, default: Any = None, max_depth: int = 1) -> Any:
        """Parse a JSON field safely, returning default on errors."""
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            parsed = value
            depth = 0
            while depth < max_depth and isinstance(parsed, str):
                try:
                    parsed = json.loads(parsed)
                except json.JSONDecodeError:
                    return default if default is not None else value
                depth += 1
            return parsed
        return value

    def _parse_json_fields(self, row: Dict, fields: List[str], default: Any = None) -> Dict:
        """Parse multiple JSON fields in a row dict."""
        for field in fields:
            if field in row and row[field] is not None:
                row[field] = self._parse_json_field(row[field], default=default)
        return row
