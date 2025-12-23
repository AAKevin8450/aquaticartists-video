"""
Database management for SQLite with schema initialization and helper functions.
"""
import sqlite3
import json
import os
import struct
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

            # Add character_count and word_count columns if they don't exist (migration for existing databases)
            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN character_count INTEGER')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN word_count INTEGER')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN duration_seconds REAL')
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Add video metadata columns (for better file management integration)
            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN resolution_width INTEGER')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN resolution_height INTEGER')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN frame_rate REAL')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN codec_video TEXT')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN codec_audio TEXT')
            except sqlite3.OperationalError:
                pass  # Column already exists

            try:
                cursor.execute('ALTER TABLE transcripts ADD COLUMN bitrate INTEGER')
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Create indexes for better query performance
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_files_type
                ON files(file_type)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_files_uploaded_at
                ON files(uploaded_at DESC)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_files_size_bytes
                ON files(size_bytes DESC)
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
            try:
                cursor.execute('ALTER TABLE nova_jobs ADD COLUMN waterfall_classification_result TEXT')
            except sqlite3.OperationalError:
                pass

            # Search optimization indexes
            # Files table indexes for search
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_files_filename
                ON files(filename)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_files_local_path
                ON files(local_path)
            ''')

            # Analysis jobs indexes for search
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_jobs_analysis_type
                ON analysis_jobs(analysis_type)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_jobs_completed_at
                ON analysis_jobs(completed_at DESC)
            ''')

            # Nova jobs indexes for search
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_nova_jobs_status
                ON nova_jobs(status)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_nova_jobs_completed_at
                ON nova_jobs(completed_at DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_nova_jobs_analysis_job_id
                ON nova_jobs(analysis_job_id)
            ''')

            # Transcripts indexes for search
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_transcripts_completed_at
                ON transcripts(completed_at DESC)
            ''')

            # Face collections indexes for search
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_collections_created_at
                ON face_collections(created_at DESC)
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
            if not row:
                return None
            file = dict(row)
            if 'metadata' in file:
                file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return file

    def get_file_by_s3_key(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """Get file by S3 key."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM files WHERE s3_key = ?', (s3_key,))
            row = cursor.fetchone()
            if not row:
                return None
            file = dict(row)
            if 'metadata' in file:
                file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return file

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
            files = [dict(row) for row in cursor.fetchall()]
            for file in files:
                if 'metadata' in file:
                    file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return files

    def delete_file(self, file_id: int) -> bool:
        """Delete file record."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
            return cursor.rowcount > 0

    def update_file_metadata(self, file_id: int, metadata_updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update file metadata by merging new values."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT metadata FROM files WHERE id = ?', (file_id,))
            row = cursor.fetchone()
            if not row:
                return None
            existing = self._parse_json_field(row['metadata'], default={})
            existing.update(metadata_updates or {})
            cursor.execute('''
                UPDATE files SET metadata = ? WHERE id = ?
            ''', (json.dumps(existing), file_id))
            return existing

    def update_file_local_path(self, file_id: int, local_path: str) -> bool:
        """Update local_path for a file."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE files SET local_path = ? WHERE id = ?', (local_path, file_id))
            return cursor.rowcount > 0

    def create_source_file(self, filename: str, s3_key: str, file_type: str,
                          size_bytes: int, content_type: str,
                          local_path: Optional[str] = None,
                          resolution_width: Optional[int] = None,
                          resolution_height: Optional[int] = None,
                          frame_rate: Optional[float] = None,
                          codec_video: Optional[str] = None,
                          codec_audio: Optional[str] = None,
                          duration_seconds: Optional[float] = None,
                          bitrate: Optional[int] = None,
                          metadata: Optional[Dict] = None) -> int:
        """Create a source file record with media metadata."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO files (
                    filename, s3_key, file_type, size_bytes, content_type,
                    is_proxy, source_file_id, local_path,
                    resolution_width, resolution_height, frame_rate,
                    codec_video, codec_audio, duration_seconds, bitrate,
                    metadata
                )
                VALUES (?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (filename, s3_key, file_type, size_bytes, content_type,
                  local_path, resolution_width, resolution_height, frame_rate,
                  codec_video, codec_audio, duration_seconds, bitrate,
                  json.dumps(metadata or {})))
            return cursor.lastrowid

    def create_proxy_file(self, source_file_id: int, filename: str, s3_key: str,
                         size_bytes: int, content_type: str,
                         local_path: Optional[str] = None,
                         resolution_width: Optional[int] = None,
                         resolution_height: Optional[int] = None,
                         frame_rate: Optional[float] = None,
                         codec_video: Optional[str] = None,
                         codec_audio: Optional[str] = None,
                         duration_seconds: Optional[float] = None,
                         bitrate: Optional[int] = None,
                         metadata: Optional[Dict] = None) -> int:
        """Create a proxy file record linked to a source file."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO files (
                    filename, s3_key, file_type, size_bytes, content_type,
                    is_proxy, source_file_id, local_path,
                    resolution_width, resolution_height, frame_rate,
                    codec_video, codec_audio, duration_seconds, bitrate,
                    metadata
                )
                VALUES (?, ?, 'video', ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (filename, s3_key, size_bytes, content_type,
                  source_file_id, local_path,
                  resolution_width, resolution_height, frame_rate,
                  codec_video, codec_audio, duration_seconds, bitrate,
                  json.dumps(metadata or {})))
            return cursor.lastrowid

    def get_proxy_for_source(self, source_file_id: int) -> Optional[Dict[str, Any]]:
        """Get proxy file record for a given source file."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM files WHERE source_file_id = ? AND is_proxy = 1
                LIMIT 1
            ''', (source_file_id,))
            row = cursor.fetchone()
            if not row:
                return None
            file = dict(row)
            if 'metadata' in file:
                file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return file

    def get_source_for_proxy(self, proxy_file_id: int) -> Optional[Dict[str, Any]]:
        """Get source file record for a given proxy file."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT source_file_id FROM files WHERE id = ?', (proxy_file_id,))
            row = cursor.fetchone()
            if not row or not row['source_file_id']:
                return None
            return self.get_file(row['source_file_id'])

    def list_source_files(self, file_type: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """List source files (non-proxy) with optional type filter."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if file_type:
                cursor.execute('''
                    SELECT * FROM files WHERE file_type = ? AND (is_proxy = 0 OR is_proxy IS NULL)
                    ORDER BY uploaded_at DESC LIMIT ? OFFSET ?
                ''', (file_type, limit, offset))
            else:
                cursor.execute('''
                    SELECT * FROM files WHERE (is_proxy = 0 OR is_proxy IS NULL)
                    ORDER BY uploaded_at DESC LIMIT ? OFFSET ?
                ''', (limit, offset))
            files = [dict(row) for row in cursor.fetchall()]
            for file in files:
                if 'metadata' in file:
                    file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return files

    def get_file_by_local_path(self, local_path: str) -> Optional[Dict[str, Any]]:
        """Get file by local_path."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM files WHERE local_path = ? LIMIT 1', (local_path,))
            row = cursor.fetchone()
            if not row:
                return None
            file = dict(row)
            if 'metadata' in file:
                file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return file

    def import_transcript_as_file(self, transcript: Dict[str, Any]) -> Optional[int]:
        """
        Import a transcript-only file into the files table.

        This allows transcript-only files to be treated as full files for
        proxy creation, analysis, and other operations.

        Returns:
            File ID if created, None if file already exists
        """
        import hashlib
        import os

        # Check if file already exists by local_path
        existing = self.get_file_by_local_path(transcript['file_path'])
        if existing:
            return None  # Already imported

        # Generate unique s3_key placeholder for local files
        # Format: local://<hash of path>
        path_hash = hashlib.sha256(transcript['file_path'].encode()).hexdigest()[:16]
        s3_key = f"local://{path_hash}"

        # Derive content_type from file extension
        ext = os.path.splitext(transcript['file_name'])[1].lower()
        content_type_map = {
            '.mp4': 'video/mp4',
            '.mov': 'video/quicktime',
            '.avi': 'video/x-msvideo',
            '.mkv': 'video/x-matroska',
            '.webm': 'video/webm',
            '.flv': 'video/x-flv',
            '.wmv': 'video/x-ms-wmv',
            '.m4v': 'video/x-m4v',
        }
        content_type = content_type_map.get(ext, 'video/mp4')

        file_stat = None
        try:
            file_stat = os.stat(transcript['file_path'])
        except OSError:
            file_stat = None

        file_ctime = file_stat.st_ctime if file_stat else None
        file_mtime = file_stat.st_mtime if file_stat else transcript.get('modified_time')

        metadata = {'source': 'transcript_import', 'imported_at': datetime.now().isoformat()}
        if isinstance(file_ctime, (int, float)):
            metadata['file_ctime'] = file_ctime
        if isinstance(file_mtime, (int, float)):
            metadata['file_mtime'] = file_mtime

        # Create file record using transcript metadata
        return self.create_source_file(
            filename=transcript['file_name'],
            s3_key=s3_key,
            file_type='video',  # Transcripts are always video files
            size_bytes=transcript['file_size'],
            content_type=content_type,
            local_path=transcript['file_path'],
            resolution_width=transcript.get('resolution_width'),
            resolution_height=transcript.get('resolution_height'),
            frame_rate=transcript.get('frame_rate'),
            codec_video=transcript.get('codec_video'),
            codec_audio=transcript.get('codec_audio'),
            duration_seconds=transcript.get('duration_seconds'),
            bitrate=transcript.get('bitrate'),
            metadata=metadata
        )

    def import_all_transcripts_as_files(self) -> Dict[str, Any]:
        """
        Import ALL transcript-only files into the files table.

        This is a one-time migration to unify file management.

        Returns:
            Dictionary with statistics about the import
        """
        # Get all unique file paths from transcripts that are NOT in files table
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT
                    t.file_path,
                    t.file_name,
                    t.file_size,
                    MAX(t.resolution_width) as resolution_width,
                    MAX(t.resolution_height) as resolution_height,
                    MAX(t.frame_rate) as frame_rate,
                    MAX(t.codec_video) as codec_video,
                    MAX(t.codec_audio) as codec_audio,
                    MAX(t.duration_seconds) as duration_seconds,
                    MAX(t.bitrate) as bitrate
                FROM transcripts t
                LEFT JOIN files f ON t.file_path = f.local_path
                WHERE f.id IS NULL AND t.status = 'COMPLETED'
                GROUP BY t.file_path, t.file_name, t.file_size
            ''')
            transcripts = [dict(row) for row in cursor.fetchall()]

        # Import each transcript as a file
        imported = 0
        skipped = 0
        errors = []

        for transcript in transcripts:
            try:
                file_id = self.import_transcript_as_file(transcript)
                if file_id:
                    imported += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append({
                    'file_path': transcript['file_path'],
                    'error': str(e)
                })

        return {
            'total': len(transcripts),
            'imported': imported,
            'skipped': skipped,
            'errors': errors
        }

    def list_source_files_with_stats(
        self,
        file_type: Optional[str] = None,
        has_proxy: Optional[bool] = None,
        has_transcription: Optional[bool] = None,
        search: Optional[str] = None,
        upload_from_date: Optional[str] = None,
        upload_to_date: Optional[str] = None,
        created_from_date: Optional[str] = None,
        created_to_date: Optional[str] = None,
        sort_by: str = 'uploaded_at',
        sort_order: str = 'desc',
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List source files with aggregated statistics.

        Returns files with additional fields:
        - has_proxy: Boolean indicating if proxy exists
        - proxy_file_id, proxy_s3_key: Proxy file information
        - total_analyses, completed_analyses, running_analyses, failed_analyses: Analysis job counts
        - total_transcripts, completed_transcripts: Transcript counts
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Build query with subqueries for aggregation
            query = '''
                SELECT
                    f.*,
                    (SELECT COUNT(*) FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1) as has_proxy,
                    (SELECT p.id FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1 LIMIT 1) as proxy_file_id,
                    (SELECT p.s3_key FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1 LIMIT 1) as proxy_s3_key,
                    (SELECT COUNT(*) FROM analysis_jobs aj WHERE aj.file_id = f.id) as total_analyses,
                    (SELECT COUNT(*) FROM analysis_jobs aj WHERE aj.file_id = f.id AND aj.status = 'COMPLETED') as completed_analyses,
                    (SELECT COUNT(*) FROM analysis_jobs aj WHERE aj.file_id = f.id AND aj.status = 'IN_PROGRESS') as running_analyses,
                    (SELECT COUNT(*) FROM analysis_jobs aj WHERE aj.file_id = f.id AND aj.status = 'FAILED') as failed_analyses,
                    (SELECT COUNT(*) FROM transcripts t WHERE t.file_path = f.local_path OR t.file_id = f.id) as total_transcripts,
                    (SELECT COUNT(*) FROM transcripts t WHERE (t.file_path = f.local_path OR t.file_id = f.id) AND t.status = 'COMPLETED') as completed_transcripts
                FROM files f
                WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)
            '''

            params = []

            # Apply filters
            if file_type:
                query += ' AND f.file_type = ?'
                params.append(file_type)

            if has_proxy is not None:
                if has_proxy:
                    query += ' AND EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'

            if has_transcription is not None:
                if has_transcription:
                    query += ' AND EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path OR t.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path OR t.file_id = f.id)'

            if search:
                query += ''' AND (
                    f.filename LIKE ?
                    OR f.local_path LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM transcripts t
                        WHERE (t.file_id = f.id OR t.file_path = f.local_path)
                          AND t.transcript_text LIKE ?
                    )
                )'''
                search_pattern = f'%{search}%'
                params.extend([search_pattern, search_pattern, search_pattern])

            if upload_from_date:
                query += ' AND date(f.uploaded_at) >= date(?)'
                params.append(upload_from_date)

            if upload_to_date:
                query += ' AND date(f.uploaded_at) <= date(?)'
                params.append(upload_to_date)

            created_date_expr = (
                "CASE "
                "WHEN json_extract(f.metadata, '$.file_mtime') IS NULL "
                "AND json_extract(f.metadata, '$.file_ctime') IS NULL "
                "THEN f.uploaded_at "
                "WHEN json_extract(f.metadata, '$.file_mtime') IS NULL "
                "THEN datetime(json_extract(f.metadata, '$.file_ctime'), 'unixepoch') "
                "WHEN json_extract(f.metadata, '$.file_ctime') IS NULL "
                "THEN datetime(json_extract(f.metadata, '$.file_mtime'), 'unixepoch') "
                "WHEN json_extract(f.metadata, '$.file_mtime') <= json_extract(f.metadata, '$.file_ctime') "
                "THEN datetime(json_extract(f.metadata, '$.file_mtime'), 'unixepoch') "
                "ELSE datetime(json_extract(f.metadata, '$.file_ctime'), 'unixepoch') "
                "END"
            )

            if created_from_date:
                query += f' AND date({created_date_expr}) >= date(?)'
                params.append(created_from_date)

            if created_to_date:
                query += f' AND date({created_date_expr}) <= date(?)'
                params.append(created_to_date)

            # Add sorting
            valid_sort_fields = ['uploaded_at', 'filename', 'size_bytes', 'duration_seconds', 'file_type']
            if sort_by in valid_sort_fields:
                sort_direction = 'ASC' if sort_order.lower() == 'asc' else 'DESC'
                query += f' ORDER BY f.{sort_by} {sort_direction}'
            else:
                query += ' ORDER BY f.uploaded_at DESC'

            query += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)

            files = []
            for row in cursor.fetchall():
                file = dict(row)
                if 'metadata' in file:
                    file['metadata'] = self._parse_json_field(file['metadata'], default={})
                files.append(file)
            return files

    def count_source_files(
        self,
        file_type: Optional[str] = None,
        has_proxy: Optional[bool] = None,
        has_transcription: Optional[bool] = None,
        search: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None
    ) -> int:
        """Count source files matching the given filters."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = 'SELECT COUNT(*) FROM files f WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)'
            params = []

            if file_type:
                query += ' AND f.file_type = ?'
                params.append(file_type)

            if has_proxy is not None:
                if has_proxy:
                    query += ' AND EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'

            if has_transcription is not None:
                if has_transcription:
                    query += ' AND EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path OR t.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path OR t.file_id = f.id)'

            if search:
                query += ''' AND (
                    f.filename LIKE ?
                    OR f.local_path LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM transcripts t
                        WHERE (t.file_id = f.id OR t.file_path = f.local_path)
                          AND t.transcript_text LIKE ?
                    )
                )'''
                search_pattern = f'%{search}%'
                params.extend([search_pattern, search_pattern, search_pattern])

            if from_date:
                query += ' AND f.uploaded_at >= ?'
                params.append(from_date)

            if to_date:
                query += ' AND f.uploaded_at <= ?'
                params.append(to_date)

            cursor.execute(query, params)
            return cursor.fetchone()[0]

    def get_file_with_stats(self, file_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed file information with all related data.

        Returns:
        - file: File record with metadata
        - proxy: Proxy file record (if exists)
        - analysis_jobs: List of analysis jobs for this file
        - transcripts: List of transcripts for this file
        """
        file = self.get_file(file_id)
        if not file:
            return None

        # Get proxy file
        proxy = self.get_proxy_for_source(file_id)

        # Get analysis jobs
        analysis_jobs = self.list_jobs(file_id=file_id, limit=1000)

        # Get transcripts (by file_id or local_path)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM transcripts
                WHERE file_id = ? OR file_path = ?
                ORDER BY created_at DESC
            ''', (file_id, file.get('local_path')))

            transcripts = []
            for row in cursor.fetchall():
                transcript = dict(row)
                for field in ['segments', 'word_timestamps']:
                    if transcript.get(field):
                        transcript[field] = json.loads(transcript[field])
                transcripts.append(transcript)

        return {
            'file': file,
            'proxy': proxy,
            'analysis_jobs': analysis_jobs,
            'transcripts': transcripts
        }

    def list_s3_files(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        List all files stored in S3 (proxies) with source file linking.

        Returns proxy files with source file information.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    p.id as proxy_id,
                    p.filename as proxy_filename,
                    p.s3_key,
                    p.size_bytes,
                    p.uploaded_at,
                    p.source_file_id,
                    s.id as source_id,
                    s.filename as source_filename,
                    s.local_path as source_local_path,
                    s.file_type as source_file_type
                FROM files p
                LEFT JOIN files s ON p.source_file_id = s.id
                WHERE p.is_proxy = 1 AND p.s3_key IS NOT NULL
                ORDER BY p.uploaded_at DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset))

            files = [dict(row) for row in cursor.fetchall()]
            return files

    def delete_file_cascade(self, file_id: int) -> Dict[str, int]:
        """
        Delete file and all related data with cascade logic.

        Returns dictionary with counts of deleted records:
        - analysis_jobs: Number of analysis jobs deleted
        - nova_jobs: Number of Nova jobs deleted
        - transcripts: Number of transcripts deleted
        - proxy_files: Number of proxy files deleted

        Note: This does NOT delete actual S3 or local files, only database records.
        File deletion should be handled by the calling code.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Get proxy files for this source
            cursor.execute('SELECT id FROM files WHERE source_file_id = ? AND is_proxy = 1', (file_id,))
            proxy_ids = [row[0] for row in cursor.fetchall()]

            # Count analysis jobs (will be cascade deleted via FK)
            cursor.execute('SELECT COUNT(*) FROM analysis_jobs WHERE file_id = ?', (file_id,))
            analysis_jobs_count = cursor.fetchone()[0]

            # Count Nova jobs (will be cascade deleted via FK from analysis_jobs)
            cursor.execute('''
                SELECT COUNT(*) FROM nova_jobs nj
                JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id
                WHERE aj.file_id = ?
            ''', (file_id,))
            nova_jobs_count = cursor.fetchone()[0]

            # Count transcripts for this file (by file_id or local_path)
            file = self.get_file(file_id)
            local_path = file.get('local_path') if file else None

            if local_path:
                cursor.execute('''
                    SELECT COUNT(*) FROM transcripts
                    WHERE file_id = ? OR file_path = ?
                ''', (file_id, local_path))
            else:
                cursor.execute('SELECT COUNT(*) FROM transcripts WHERE file_id = ?', (file_id,))
            transcripts_count = cursor.fetchone()[0]

            # Delete transcripts (not cascade, manual delete)
            if local_path:
                cursor.execute('''
                    DELETE FROM transcripts WHERE file_id = ? OR file_path = ?
                ''', (file_id, local_path))
            else:
                cursor.execute('DELETE FROM transcripts WHERE file_id = ?', (file_id,))

            # Delete proxy files (will also cascade delete their analysis jobs)
            for proxy_id in proxy_ids:
                cursor.execute('DELETE FROM files WHERE id = ?', (proxy_id,))

            # Delete source file (will cascade delete analysis_jobs and nova_jobs via FK)
            cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))

            return {
                'analysis_jobs': analysis_jobs_count,
                'nova_jobs': nova_jobs_count,
                'transcripts': transcripts_count,
                'proxy_files': len(proxy_ids)
            }

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

    def get_transcript_by_path_and_model(self, file_path: str, model_name: str) -> Optional[Dict[str, Any]]:
        """Get transcript by file path and model name."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM transcripts
                WHERE file_path = ? AND model_name = ?
            ''', (file_path, model_name))
            row = cursor.fetchone()
            if row:
                transcript = dict(row)
                for field in ['segments', 'word_timestamps']:
                    if transcript.get(field):
                        transcript[field] = json.loads(transcript[field])
                return transcript
            return None

    def update_transcript_status(self, transcript_id: int, status: str,
                                transcript_text: Optional[str] = None,
                                character_count: Optional[int] = None,
                                word_count: Optional[int] = None,
                                duration_seconds: Optional[float] = None,
                                segments: Optional[List] = None,
                                word_timestamps: Optional[List] = None,
                                language: Optional[str] = None,
                                confidence_score: Optional[float] = None,
                                processing_time: Optional[float] = None,
                                error_message: Optional[str] = None,
                                resolution_width: Optional[int] = None,
                                resolution_height: Optional[int] = None,
                                frame_rate: Optional[float] = None,
                                codec_video: Optional[str] = None,
                                codec_audio: Optional[str] = None,
                                bitrate: Optional[int] = None):
        """Update transcript status and results."""
        from datetime import datetime
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if status == 'COMPLETED':
                cursor.execute('''
                    UPDATE transcripts
                    SET status = ?, transcript_text = ?, character_count = ?, word_count = ?,
                        duration_seconds = ?, segments = ?, word_timestamps = ?, language = ?,
                        confidence_score = ?, processing_time = ?,
                        resolution_width = ?, resolution_height = ?, frame_rate = ?,
                        codec_video = ?, codec_audio = ?, bitrate = ?,
                        completed_at = ?
                    WHERE id = ?
                ''', (status, transcript_text, character_count, word_count, duration_seconds,
                     json.dumps(segments) if segments else None,
                     json.dumps(word_timestamps) if word_timestamps else None,
                     language, confidence_score, processing_time,
                     resolution_width, resolution_height, frame_rate,
                     codec_video, codec_audio, bitrate,
                     datetime.now().isoformat(), transcript_id))

                # Automatically import transcript file into files table
                # This ensures all transcribed files can have proxies created and be analyzed
                transcript = self.get_transcript(transcript_id)
                if transcript:
                    try:
                        self.import_transcript_as_file(transcript)
                    except Exception as e:
                        # Log error but don't fail the transcript update
                        print(f"[WARNING] Failed to import transcript file into files table: {e}")

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

    def get_transcripts_by_file(self, file_id: int) -> List[Dict[str, Any]]:
        """Get all transcripts for a specific file."""
        file = self.get_file(file_id)
        if not file:
            return []

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM transcripts
                WHERE file_id = ? OR file_path = ?
                ORDER BY created_at DESC
            ''', (file_id, file.get('local_path')))

            transcripts = []
            for row in cursor.fetchall():
                transcript = dict(row)
                for field in ['segments', 'word_timestamps']:
                    if transcript.get(field):
                        transcript[field] = json.loads(transcript[field])
                transcripts.append(transcript)
            return transcripts

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

    # ============================================================================
    # EMBEDDING OPERATIONS
    # ============================================================================

    def _serialize_embedding(self, vector: List[float]) -> bytes:
        """Serialize embedding vector to float32 bytes for sqlite-vec."""
        return struct.pack(f'{len(vector)}f', *vector)

    def _validate_embedding_dimension(self, vector: List[float]):
        """Validate embedding length matches configured dimension."""
        expected = self._get_embedding_dimension()
        if len(vector) != expected:
            raise ValueError(f"Embedding dimension mismatch: expected {expected}, got {len(vector)}")

    def get_embedding_by_hash(self, source_type: str, source_id: int,
                              model_name: str, content_hash: str) -> Optional[Dict[str, Any]]:
        """Get embedding metadata by content hash."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM nova_embedding_metadata
                WHERE source_type = ? AND source_id = ? AND model_name = ? AND content_hash = ?
            ''', (source_type, source_id, model_name, content_hash))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_nova_embedding(self, embedding_vector: List[float], source_type: str,
                              source_id: int, model_name: str, content_hash: str,
                              file_id: Optional[int] = None) -> int:
        """Store embedding vector and metadata in sqlite-vec tables."""
        self._validate_embedding_dimension(embedding_vector)

        with self.get_connection() as conn:
            if not self._load_vector_extension(conn):
                raise RuntimeError("SQLite vector extension not available. Set SQLITE_VEC_PATH or install sqlite-vec.")

            self._ensure_embedding_tables(conn)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT rowid FROM nova_embedding_metadata
                WHERE source_type = ? AND source_id = ? AND model_name = ? AND content_hash = ?
            ''', (source_type, source_id, model_name, content_hash))
            existing = cursor.fetchone()
            if existing:
                return existing['rowid']

            vector_blob = self._serialize_embedding(embedding_vector)
            cursor.execute('INSERT INTO nova_embeddings(embedding) VALUES (?)', (vector_blob,))
            rowid = cursor.lastrowid
            cursor.execute('''
                INSERT INTO nova_embedding_metadata (
                    rowid, source_type, source_id, file_id, model_name, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (rowid, source_type, source_id, file_id, model_name, content_hash, datetime.now().isoformat()))
            return rowid

    def search_embeddings(
        self,
        query_vector: List[float],
        limit: int = 20,
        source_types: Optional[List[str]] = None,
        min_similarity: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Perform KNN vector search using sqlite-vec.

        Args:
            query_vector: Embedding vector for the query
            limit: Maximum results to return
            source_types: Filter by source type ('transcript', 'nova_analysis')
            min_similarity: Minimum cosine similarity (0.0-1.0)

        Returns:
            List of matches with distance, source_type, source_id, etc.
        """
        self._validate_embedding_dimension(query_vector)

        with self.get_connection() as conn:
            if not self._load_vector_extension(conn):
                raise RuntimeError("SQLite vector extension not available")

            query_blob = self._serialize_embedding(query_vector)
            cursor = conn.cursor()

            # Build query with optional source_type filter.
            # vec0 requires a k/limit constraint on the vector table itself.
            sql = '''
                SELECT
                    e.rowid,
                    e.distance,
                    m.source_type,
                    m.source_id,
                    m.file_id,
                    m.model_name,
                    m.content_hash,
                    m.created_at
                FROM (
                    SELECT rowid, distance
                    FROM nova_embeddings
                    WHERE embedding MATCH ? AND k = ?
                ) e
                JOIN nova_embedding_metadata m ON e.rowid = m.rowid
            '''
            params = [query_blob, max(1, int(limit))]

            if source_types:
                placeholders = ','.join('?' * len(source_types))
                sql += f' AND m.source_type IN ({placeholders})'
                params.extend(source_types)

            sql += ' ORDER BY e.distance'

            cursor.execute(sql, params)
            results = [dict(row) for row in cursor.fetchall()]

            # Convert L2 distance to similarity score (optional normalization)
            for r in results:
                # For normalized vectors, similarity ≈ 1 - (distance² / 2)
                r['similarity'] = max(0, 1 - (r['distance'] ** 2) / 2)

            # Filter by minimum similarity if specified
            if min_similarity > 0:
                results = [r for r in results if r['similarity'] >= min_similarity]

            return results

    def get_content_for_embedding_results(
        self,
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Fetch actual content for embedding search results.
        Enriches results with text content from source tables.
        """
        if not results:
            return []

        # Group by source type for efficient fetching
        transcript_ids = [r['source_id'] for r in results if r['source_type'] == 'transcript']
        nova_ids = [r['source_id'] for r in results if r['source_type'] == 'nova_analysis']

        enriched = []

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Fetch transcripts
            if transcript_ids:
                placeholders = ','.join('?' * len(transcript_ids))
                cursor.execute(f'''
                    SELECT id, file_name, file_path, transcript_text, language, model_name
                    FROM transcripts WHERE id IN ({placeholders})
                ''', transcript_ids)
                transcripts = {row['id']: dict(row) for row in cursor.fetchall()}
            else:
                transcripts = {}

            # Fetch Nova jobs
            if nova_ids:
                placeholders = ','.join('?' * len(nova_ids))
                cursor.execute(f'''
                    SELECT id, model, analysis_types, summary_result, chapters_result, elements_result, waterfall_classification_result
                    FROM nova_jobs WHERE id IN ({placeholders})
                ''', nova_ids)
                nova_jobs = {row['id']: dict(row) for row in cursor.fetchall()}
            else:
                nova_jobs = {}

        # Enrich results
        for r in results:
            enriched_result = r.copy()

            if r['source_type'] == 'transcript':
                source = transcripts.get(r['source_id'], {})
                enriched_result['title'] = source.get('file_name', 'Unknown')
                enriched_result['preview'] = (source.get('transcript_text', '')[:200] + '...')
                enriched_result['file_path'] = source.get('file_path')
                enriched_result['language'] = source.get('language')

            elif r['source_type'] == 'nova_analysis':
                source = nova_jobs.get(r['source_id'], {})
                analysis_types = source.get('analysis_types', '[]')
                if isinstance(analysis_types, str):
                    try:
                        analysis_types = json.loads(analysis_types)
                    except:
                        analysis_types = []
                enriched_result['title'] = f"Nova {', '.join(analysis_types) if analysis_types else 'Analysis'}"

                # Parse results JSON for preview
                try:
                    # Try summary first
                    summary_result = source.get('summary_result')
                    if summary_result:
                        if isinstance(summary_result, str):
                            summary_result = json.loads(summary_result)
                        enriched_result['preview'] = str(summary_result)[:200] + '...'
                    else:
                        # Fall back to chapters or elements
                        chapters_result = source.get('chapters_result')
                        if chapters_result:
                            if isinstance(chapters_result, str):
                                chapters_result = json.loads(chapters_result)
                            enriched_result['preview'] = str(chapters_result)[:200] + '...'
                        else:
                            waterfall_result = source.get('waterfall_classification_result')
                            if waterfall_result:
                                if isinstance(waterfall_result, str):
                                    waterfall_result = json.loads(waterfall_result)
                                enriched_result['preview'] = str(waterfall_result)[:200] + '...'
                            else:
                                enriched_result['preview'] = 'Analysis results'
                except:
                    enriched_result['preview'] = 'Analysis results'

            enriched.append(enriched_result)

        return enriched

    def delete_embeddings_for_source(
        self,
        source_type: str,
        source_id: int
    ) -> int:
        """Delete all embeddings for a source. Returns count deleted."""
        with self.get_connection() as conn:
            if not self._load_vector_extension(conn):
                return 0

            cursor = conn.cursor()

            # Get rowids to delete
            cursor.execute('''
                SELECT rowid FROM nova_embedding_metadata
                WHERE source_type = ? AND source_id = ?
            ''', (source_type, source_id))
            rowids = [row['rowid'] for row in cursor.fetchall()]

            if not rowids:
                return 0

            # Delete from both tables
            placeholders = ','.join('?' * len(rowids))
            cursor.execute(f'DELETE FROM nova_embeddings WHERE rowid IN ({placeholders})', rowids)
            cursor.execute(f'DELETE FROM nova_embedding_metadata WHERE rowid IN ({placeholders})', rowids)

            return len(rowids)

    def get_embedding_stats(self) -> Dict[str, Any]:
        """Get embedding statistics for monitoring."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT
                    source_type,
                    model_name,
                    COUNT(*) as count
                FROM nova_embedding_metadata
                GROUP BY source_type, model_name
            ''')

            by_source = {}
            for row in cursor.fetchall():
                key = f"{row['source_type']}:{row['model_name']}"
                by_source[key] = row['count']

            cursor.execute('SELECT COUNT(*) as total FROM nova_embedding_metadata')
            total = cursor.fetchone()['total']

            return {
                'total_embeddings': total,
                'by_source_and_model': by_source,
                'dimension': self._get_embedding_dimension()
            }

    # ============================================================================
    # NOVA JOB OPERATIONS
    # ============================================================================

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

    def list_all_files_with_stats(
        self,
        file_type: Optional[str] = None,
        has_proxy: Optional[bool] = None,
        has_transcription: Optional[bool] = None,
        has_nova_analysis: Optional[bool] = None,
        has_rekognition_analysis: Optional[bool] = None,
        has_nova_embeddings: Optional[bool] = None,
        search: Optional[str] = None,
        upload_from_date: Optional[str] = None,
        upload_to_date: Optional[str] = None,
        created_from_date: Optional[str] = None,
        created_to_date: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        sort_by: str = 'uploaded_at',
        sort_order: str = 'desc',
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        List ALL files from the files table with stats.

        All files the system knows about are now in the files table,
        including transcript-only files that were migrated.

        Returns unified file list with stats.

        OPTIMIZED: Uses LEFT JOINs with GROUP BY instead of correlated subqueries
        for much better performance (~100x faster for large datasets).
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Optimized query using LEFT JOINs and aggregations instead of correlated subqueries
            query = '''
                SELECT
                    f.id,
                    f.filename,
                    f.s3_key,
                    f.file_type,
                    f.size_bytes,
                    f.content_type,
                    f.uploaded_at,
                    f.metadata,
                    f.local_path,
                    f.resolution_width,
                    f.resolution_height,
                    f.frame_rate,
                    f.codec_video,
                    f.codec_audio,
                    f.duration_seconds,
                    f.bitrate,
                    COUNT(DISTINCT CASE WHEN p.is_proxy = 1 THEN p.id END) as has_proxy,
                    MAX(CASE WHEN p.is_proxy = 1 THEN p.id END) as proxy_file_id,
                    MAX(CASE WHEN p.is_proxy = 1 THEN p.s3_key END) as proxy_s3_key,
                    MAX(CASE WHEN p.is_proxy = 1 THEN p.size_bytes END) as proxy_size_bytes,
                    COUNT(DISTINCT aj.id) as total_analyses,
                    COUNT(DISTINCT CASE WHEN aj.status = 'COMPLETED' THEN aj.id END) as completed_analyses,
                    COUNT(DISTINCT CASE WHEN aj.status = 'IN_PROGRESS' THEN aj.id END) as running_analyses,
                    COUNT(DISTINCT CASE WHEN aj.status = 'FAILED' THEN aj.id END) as failed_analyses,
                    COUNT(DISTINCT t.id) as total_transcripts,
                    COUNT(DISTINCT CASE WHEN t.status = 'COMPLETED' THEN t.id END) as completed_transcripts,
                    MAX(CASE WHEN t.status = 'COMPLETED'
                        THEN COALESCE(t.character_count, LENGTH(COALESCE(t.transcript_text, '')))
                        END) as max_completed_transcript_chars
                FROM files f
                LEFT JOIN files p ON p.source_file_id = f.id AND p.is_proxy = 1
                LEFT JOIN analysis_jobs aj ON aj.file_id = f.id
                LEFT JOIN transcripts t ON t.file_path = f.local_path
                WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)
            '''

            params = []

            # Apply filters
            if file_type:
                query += ' AND f.file_type = ?'
                params.append(file_type)

            if has_proxy is not None:
                if has_proxy:
                    query += ' AND EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'

            if has_transcription is not None:
                if has_transcription:
                    query += ' AND EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path)'

            if has_nova_analysis is not None:
                if has_nova_analysis:
                    query += ' AND EXISTS (SELECT 1 FROM nova_jobs nj JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id WHERE aj.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM nova_jobs nj JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id WHERE aj.file_id = f.id)'

            if has_rekognition_analysis is not None:
                if has_rekognition_analysis:
                    query += ' AND EXISTS (SELECT 1 FROM analysis_jobs aj WHERE aj.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM analysis_jobs aj WHERE aj.file_id = f.id)'

            if has_nova_embeddings is not None:
                if has_nova_embeddings:
                    query += ' AND EXISTS (SELECT 1 FROM nova_embedding_metadata nem WHERE nem.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM nova_embedding_metadata nem WHERE nem.file_id = f.id)'

            if search:
                query += ''' AND (
                    f.filename LIKE ?
                    OR f.local_path LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM transcripts t
                        WHERE t.file_path = f.local_path
                          AND t.transcript_text LIKE ?
                    )
                )'''
                search_pattern = f'%{search}%'
                params.extend([search_pattern, search_pattern, search_pattern])

            if upload_from_date:
                query += ' AND date(f.uploaded_at) >= date(?)'
                params.append(upload_from_date)

            if upload_to_date:
                query += ' AND date(f.uploaded_at) <= date(?)'
                params.append(upload_to_date)

            created_date_expr = (
                "CASE "
                "WHEN json_extract(f.metadata, '$.file_mtime') IS NULL "
                "AND json_extract(f.metadata, '$.file_ctime') IS NULL "
                "THEN f.uploaded_at "
                "WHEN json_extract(f.metadata, '$.file_mtime') IS NULL "
                "THEN datetime(json_extract(f.metadata, '$.file_ctime'), 'unixepoch') "
                "WHEN json_extract(f.metadata, '$.file_ctime') IS NULL "
                "THEN datetime(json_extract(f.metadata, '$.file_mtime'), 'unixepoch') "
                "WHEN json_extract(f.metadata, '$.file_mtime') <= json_extract(f.metadata, '$.file_ctime') "
                "THEN datetime(json_extract(f.metadata, '$.file_mtime'), 'unixepoch') "
                "ELSE datetime(json_extract(f.metadata, '$.file_ctime'), 'unixepoch') "
                "END"
            )

            if created_from_date:
                query += f' AND date({created_date_expr}) >= date(?)'
                params.append(created_from_date)

            if created_to_date:
                query += f' AND date({created_date_expr}) <= date(?)'
                params.append(created_to_date)

            if min_size is not None:
                query += ' AND f.size_bytes >= ?'
                params.append(min_size)

            if max_size is not None:
                query += ' AND f.size_bytes <= ?'
                params.append(max_size)

            if min_duration is not None:
                query += ' AND f.duration_seconds >= ?'
                params.append(min_duration)

            if max_duration is not None:
                query += ' AND f.duration_seconds <= ?'
                params.append(max_duration)

            # Group by file ID to aggregate stats from joined tables
            query += ' GROUP BY f.id'

            # Add sorting
            valid_sort_fields = ['uploaded_at', 'filename', 'size_bytes', 'duration_seconds', 'file_type']
            if sort_by in valid_sort_fields:
                sort_direction = 'ASC' if sort_order.lower() == 'asc' else 'DESC'
                query += f' ORDER BY f.{sort_by} {sort_direction}'
            else:
                query += ' ORDER BY f.uploaded_at DESC'

            query += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)

            files = []
            for row in cursor.fetchall():
                file = dict(row)
                if 'metadata' in file:
                    file['metadata'] = self._parse_json_field(file['metadata'], default={})
                files.append(file)
            return files

    def count_all_files(
        self,
        file_type: Optional[str] = None,
        has_proxy: Optional[bool] = None,
        has_transcription: Optional[bool] = None,
        has_nova_analysis: Optional[bool] = None,
        has_rekognition_analysis: Optional[bool] = None,
        has_nova_embeddings: Optional[bool] = None,
        search: Optional[str] = None,
        upload_from_date: Optional[str] = None,
        upload_to_date: Optional[str] = None,
        created_from_date: Optional[str] = None,
        created_to_date: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None
    ) -> int:
        """Count all files from the files table."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Simplified query - all files are now in the files table
            query = 'SELECT COUNT(*) FROM files f WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)'
            params = []

            if file_type:
                query += ' AND f.file_type = ?'
                params.append(file_type)

            if has_proxy is not None:
                if has_proxy:
                    query += ' AND EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'

            if has_transcription is not None:
                if has_transcription:
                    query += ' AND EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path)'

            if has_nova_analysis is not None:
                if has_nova_analysis:
                    query += ' AND EXISTS (SELECT 1 FROM nova_jobs nj JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id WHERE aj.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM nova_jobs nj JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id WHERE aj.file_id = f.id)'

            if has_rekognition_analysis is not None:
                if has_rekognition_analysis:
                    query += ' AND EXISTS (SELECT 1 FROM analysis_jobs aj WHERE aj.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM analysis_jobs aj WHERE aj.file_id = f.id)'

            if has_nova_embeddings is not None:
                if has_nova_embeddings:
                    query += ' AND EXISTS (SELECT 1 FROM nova_embedding_metadata nem WHERE nem.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM nova_embedding_metadata nem WHERE nem.file_id = f.id)'

            if search:
                query += ''' AND (
                    f.filename LIKE ?
                    OR f.local_path LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM transcripts t
                        WHERE t.file_path = f.local_path
                          AND t.transcript_text LIKE ?
                    )
                )'''
                search_pattern = f'%{search}%'
                params.extend([search_pattern, search_pattern, search_pattern])

            if upload_from_date:
                query += ' AND date(f.uploaded_at) >= date(?)'
                params.append(upload_from_date)

            if upload_to_date:
                query += ' AND date(f.uploaded_at) <= date(?)'
                params.append(upload_to_date)

            created_date_expr = (
                "CASE "
                "WHEN json_extract(f.metadata, '$.file_mtime') IS NULL "
                "AND json_extract(f.metadata, '$.file_ctime') IS NULL "
                "THEN f.uploaded_at "
                "WHEN json_extract(f.metadata, '$.file_mtime') IS NULL "
                "THEN datetime(json_extract(f.metadata, '$.file_ctime'), 'unixepoch') "
                "WHEN json_extract(f.metadata, '$.file_ctime') IS NULL "
                "THEN datetime(json_extract(f.metadata, '$.file_mtime'), 'unixepoch') "
                "WHEN json_extract(f.metadata, '$.file_mtime') <= json_extract(f.metadata, '$.file_ctime') "
                "THEN datetime(json_extract(f.metadata, '$.file_mtime'), 'unixepoch') "
                "ELSE datetime(json_extract(f.metadata, '$.file_ctime'), 'unixepoch') "
                "END"
            )

            if created_from_date:
                query += f' AND date({created_date_expr}) >= date(?)'
                params.append(created_from_date)

            if created_to_date:
                query += f' AND date({created_date_expr}) <= date(?)'
                params.append(created_to_date)

            if min_size is not None:
                query += ' AND f.size_bytes >= ?'
                params.append(min_size)

            if max_size is not None:
                query += ' AND f.size_bytes <= ?'
                params.append(max_size)

            if min_duration is not None:
                query += ' AND f.duration_seconds >= ?'
                params.append(min_duration)

            if max_duration is not None:
                query += ' AND f.duration_seconds <= ?'
                params.append(max_duration)

            cursor.execute(query, params)
            return cursor.fetchone()[0]

    def get_all_files_summary(
        self,
        file_type: Optional[str] = None,
        has_proxy: Optional[bool] = None,
        has_transcription: Optional[bool] = None,
        has_nova_analysis: Optional[bool] = None,
        has_rekognition_analysis: Optional[bool] = None,
        has_nova_embeddings: Optional[bool] = None,
        search: Optional[str] = None,
        upload_from_date: Optional[str] = None,
        upload_to_date: Optional[str] = None,
        created_from_date: Optional[str] = None,
        created_to_date: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get summary statistics for all files matching filters.

        Returns:
            {
                'total_count': int,
                'total_size_bytes': int,
                'total_duration_seconds': float,
                'total_proxy_size_bytes': int
            }

        OPTIMIZED: Uses LEFT JOIN instead of correlated subquery for proxy sizes.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Optimized query using LEFT JOIN instead of correlated subquery
            query = '''
                SELECT
                    COUNT(DISTINCT f.id) as total_count,
                    COALESCE(SUM(f.size_bytes), 0) as total_size_bytes,
                    COALESCE(SUM(f.duration_seconds), 0) as total_duration_seconds,
                    COALESCE(SUM(p.size_bytes), 0) as total_proxy_size_bytes
                FROM files f
                LEFT JOIN files p ON p.source_file_id = f.id AND p.is_proxy = 1
                WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)
            '''

            params = []

            if file_type:
                query += ' AND f.file_type = ?'
                params.append(file_type)

            if has_proxy is not None:
                if has_proxy:
                    query += ' AND EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM files p WHERE p.source_file_id = f.id AND p.is_proxy = 1)'

            if has_transcription is not None:
                if has_transcription:
                    query += ' AND EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM transcripts t WHERE t.file_path = f.local_path)'

            if has_nova_analysis is not None:
                if has_nova_analysis:
                    query += ' AND EXISTS (SELECT 1 FROM nova_jobs nj JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id WHERE aj.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM nova_jobs nj JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id WHERE aj.file_id = f.id)'

            if has_rekognition_analysis is not None:
                if has_rekognition_analysis:
                    query += ' AND EXISTS (SELECT 1 FROM analysis_jobs aj WHERE aj.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM analysis_jobs aj WHERE aj.file_id = f.id)'

            if has_nova_embeddings is not None:
                if has_nova_embeddings:
                    query += ' AND EXISTS (SELECT 1 FROM nova_embedding_metadata nem WHERE nem.file_id = f.id)'
                else:
                    query += ' AND NOT EXISTS (SELECT 1 FROM nova_embedding_metadata nem WHERE nem.file_id = f.id)'

            if search:
                query += ''' AND (
                    f.filename LIKE ?
                    OR f.local_path LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM transcripts t
                        WHERE t.file_path = f.local_path
                          AND t.transcript_text LIKE ?
                    )
                )'''
                search_pattern = f'%{search}%'
                params.extend([search_pattern, search_pattern, search_pattern])

            if upload_from_date:
                query += ' AND date(f.uploaded_at) >= date(?)'
                params.append(upload_from_date)

            if upload_to_date:
                query += ' AND date(f.uploaded_at) <= date(?)'
                params.append(upload_to_date)

            created_date_expr = (
                "CASE "
                "WHEN json_extract(f.metadata, '$.file_mtime') IS NULL "
                "AND json_extract(f.metadata, '$.file_ctime') IS NULL "
                "THEN f.uploaded_at "
                "WHEN json_extract(f.metadata, '$.file_mtime') IS NULL "
                "THEN datetime(json_extract(f.metadata, '$.file_ctime'), 'unixepoch') "
                "WHEN json_extract(f.metadata, '$.file_ctime') IS NULL "
                "THEN datetime(json_extract(f.metadata, '$.file_mtime'), 'unixepoch') "
                "WHEN json_extract(f.metadata, '$.file_mtime') <= json_extract(f.metadata, '$.file_ctime') "
                "THEN datetime(json_extract(f.metadata, '$.file_mtime'), 'unixepoch') "
                "ELSE datetime(json_extract(f.metadata, '$.file_ctime'), 'unixepoch') "
                "END"
            )

            if created_from_date:
                query += f' AND date({created_date_expr}) >= date(?)'
                params.append(created_from_date)

            if created_to_date:
                query += f' AND date({created_date_expr}) <= date(?)'
                params.append(created_to_date)

            if min_size is not None:
                query += ' AND f.size_bytes >= ?'
                params.append(min_size)

            if max_size is not None:
                query += ' AND f.size_bytes <= ?'
                params.append(max_size)

            if min_duration is not None:
                query += ' AND f.duration_seconds >= ?'
                params.append(min_duration)

            if max_duration is not None:
                query += ' AND f.duration_seconds <= ?'
                params.append(max_duration)

            cursor.execute(query, params)
            row = cursor.fetchone()

            return {
                'total_count': row['total_count'],
                'total_size_bytes': row['total_size_bytes'],
                'total_duration_seconds': row['total_duration_seconds'],
                'total_proxy_size_bytes': row['total_proxy_size_bytes']
            }

    def get_dashboard_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive dashboard statistics.

        Returns dictionary with:
        - Library stats (files, storage, duration)
        - Processing stats (jobs, success rate)
        - Content breakdown (videos vs images, proxies, transcriptions)
        - Recent activity (this week, today)
        - Transcription stats
        - Analysis breakdown
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            from datetime import datetime, timedelta, timezone

            # Calculate date thresholds
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            week_ago = (now - timedelta(days=7)).isoformat()

            # 1. Library Overview
            cursor.execute('''
                SELECT
                    COUNT(*) as total_files,
                    COUNT(CASE WHEN f.file_type = 'video' THEN 1 END) as video_count,
                    COUNT(CASE WHEN f.file_type = 'image' THEN 1 END) as image_count,
                    COALESCE(SUM(f.size_bytes), 0) as total_size,
                    COALESCE(SUM(f.duration_seconds), 0) as total_duration
                FROM files f
                WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)
            ''')
            library_stats = dict(cursor.fetchone())

            # 2. Processing Statistics
            cursor.execute('''
                SELECT
                    COUNT(*) as total_jobs,
                    COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as completed_jobs,
                    COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_jobs,
                    COUNT(CASE WHEN status = 'IN_PROGRESS' THEN 1 END) as running_jobs
                FROM analysis_jobs
            ''')
            job_stats = dict(cursor.fetchone())

            # 3. Proxy Statistics
            cursor.execute('''
                SELECT
                    COUNT(DISTINCT p.source_file_id) as files_with_proxy,
                    COALESCE(SUM(p.size_bytes), 0) as proxy_storage
                FROM files p
                WHERE p.is_proxy = 1 AND p.source_file_id IS NOT NULL
            ''')
            proxy_stats = dict(cursor.fetchone())

            # 4. Transcription Statistics
            cursor.execute('''
                SELECT
                    COUNT(*) as total_transcripts,
                    COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as completed_transcripts,
                    COALESCE(SUM(duration_seconds), 0) as transcribed_duration,
                    (SELECT model_name FROM transcripts WHERE status = 'COMPLETED'
                     GROUP BY model_name ORDER BY COUNT(*) DESC LIMIT 1) as most_used_model
                FROM transcripts
            ''')
            transcript_stats = dict(cursor.fetchone())

            # 5. Recent Activity (this week)
            cursor.execute('''
                SELECT
                    COUNT(*) as files_this_week
                FROM files f
                WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)
                  AND f.uploaded_at >= ?
            ''', (week_ago,))
            files_this_week = cursor.fetchone()['files_this_week']

            cursor.execute('''
                SELECT
                    COUNT(*) as jobs_this_week
                FROM analysis_jobs
                WHERE started_at >= ?
            ''', (week_ago,))
            jobs_this_week = cursor.fetchone()['jobs_this_week']

            # 6. Recent Activity (today)
            cursor.execute('''
                SELECT
                    COUNT(*) as files_today
                FROM files f
                WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)
                  AND f.uploaded_at >= ?
            ''', (today_start,))
            files_today = cursor.fetchone()['files_today']

            cursor.execute('''
                SELECT
                    COUNT(*) as jobs_completed_today
                FROM analysis_jobs
                WHERE status = 'COMPLETED'
                  AND completed_at >= ?
            ''', (today_start,))
            jobs_completed_today = cursor.fetchone()['jobs_completed_today']

            # 7. Analysis Type Breakdown
            cursor.execute('''
                SELECT
                    analysis_type,
                    COUNT(*) as count
                FROM analysis_jobs
                GROUP BY analysis_type
                ORDER BY count DESC
                LIMIT 5
            ''')
            top_analysis_types = [dict(row) for row in cursor.fetchall()]

            # 8. Face Collections Count
            cursor.execute('SELECT COUNT(*) as collection_count FROM face_collections')
            collection_count = cursor.fetchone()['collection_count']

            # 9. Nova Analysis Count
            cursor.execute('SELECT COUNT(*) as nova_count FROM nova_jobs')
            nova_count = cursor.fetchone()['nova_count']

            # Calculate derived stats
            video_percent = (library_stats['video_count'] / library_stats['total_files'] * 100) if library_stats['total_files'] > 0 else 0
            image_percent = (library_stats['image_count'] / library_stats['total_files'] * 100) if library_stats['total_files'] > 0 else 0
            proxy_percent = (proxy_stats['files_with_proxy'] / library_stats['total_files'] * 100) if library_stats['total_files'] > 0 else 0
            success_rate = (job_stats['completed_jobs'] / job_stats['total_jobs'] * 100) if job_stats['total_jobs'] > 0 else 0
            transcript_percent = (transcript_stats['completed_transcripts'] / library_stats['video_count'] * 100) if library_stats['video_count'] > 0 else 0

            return {
                # Library Overview
                'total_files': library_stats['total_files'],
                'video_count': library_stats['video_count'],
                'image_count': library_stats['image_count'],
                'total_storage_bytes': library_stats['total_size'],
                'total_duration_seconds': library_stats['total_duration'],
                'video_percent': round(video_percent, 1),
                'image_percent': round(image_percent, 1),

                # Processing Stats
                'total_jobs': job_stats['total_jobs'],
                'completed_jobs': job_stats['completed_jobs'],
                'failed_jobs': job_stats['failed_jobs'],
                'running_jobs': job_stats['running_jobs'],
                'success_rate': round(success_rate, 1),

                # Proxy Stats
                'files_with_proxy': proxy_stats['files_with_proxy'],
                'proxy_storage_bytes': proxy_stats['proxy_storage'],
                'proxy_percent': round(proxy_percent, 1),

                # Transcription Stats
                'total_transcripts': transcript_stats['total_transcripts'],
                'completed_transcripts': transcript_stats['completed_transcripts'],
                'transcribed_duration_seconds': transcript_stats['transcribed_duration'],
                'most_used_model': transcript_stats['most_used_model'] or 'N/A',
                'transcript_percent': round(transcript_percent, 1),

                # Recent Activity
                'files_this_week': files_this_week,
                'jobs_this_week': jobs_this_week,
                'files_today': files_today,
                'jobs_completed_today': jobs_completed_today,

                # Analysis Breakdown
                'nova_count': nova_count,
                'rekognition_count': job_stats['total_jobs'] - nova_count,
                'top_analysis_types': top_analysis_types,

                # Collections
                'collection_count': collection_count
            }

    # Search methods
    def search_all(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        file_type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        status: Optional[str] = None,
        analysis_type: Optional[str] = None,
        model: Optional[str] = None,
        sort_by: str = 'relevance',
        sort_order: str = 'desc',
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Unified search across all data sources.

        Returns list of search result dictionaries with:
        - source_type: 'file', 'transcript', 'rekognition', 'nova', 'collection'
        - source_id: Primary key from source table
        - title: Display title
        - category: Result category
        - timestamp: Relevant date/time
        - match_field: Which field matched
        - size_bytes: File size (if applicable)
        - duration_seconds: Duration (if applicable)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Build source filter
            all_sources = ['file', 'transcript', 'rekognition', 'nova', 'collection']
            active_sources = sources if sources else all_sources

            # Prepare search pattern for LIKE
            search_pattern = f'%{query}%'

            # Build UNION query
            union_queries = []
            params = []

            # 1. Search in files
            if 'file' in active_sources:
                file_query = '''
                SELECT
                    'file' as source_type,
                    id as source_id,
                    filename as title,
                    file_type as category,
                    uploaded_at as timestamp,
                    CASE
                        WHEN filename LIKE ? THEN 'filename'
                        WHEN local_path LIKE ? THEN 'path'
                        WHEN metadata LIKE ? THEN 'metadata'
                        WHEN codec_video LIKE ? THEN 'codec_video'
                        WHEN codec_audio LIKE ? THEN 'codec_audio'
                    END as match_field,
                    size_bytes,
                    duration_seconds
                FROM files
                WHERE (
                    filename LIKE ? OR
                    local_path LIKE ? OR
                    metadata LIKE ? OR
                    codec_video LIKE ? OR
                    codec_audio LIKE ?
                )
                '''
                # Add file_type filter if specified
                if file_type:
                    file_query += ' AND file_type = ?'
                    params.extend([search_pattern] * 10 + [file_type])
                else:
                    params.extend([search_pattern] * 10)

                # Add date range filters
                if from_date:
                    file_query += ' AND uploaded_at >= ?'
                    params.append(from_date)
                if to_date:
                    file_query += ' AND uploaded_at <= ?'
                    params.append(to_date)

                union_queries.append(file_query)

            # 2. Search in transcripts
            if 'transcript' in active_sources:
                transcript_query = '''
                SELECT
                    'transcript' as source_type,
                    id as source_id,
                    file_name as title,
                    'Transcript (' || model_name || ')' as category,
                    created_at as timestamp,
                    'transcript' as match_field,
                    NULL as size_bytes,
                    duration_seconds
                FROM transcripts
                WHERE status = 'COMPLETED'
                AND (
                    transcript_text LIKE ? OR
                    file_name LIKE ?
                )
                '''
                params.extend([search_pattern, search_pattern])

                # Add model filter if specified
                if model:
                    transcript_query += ' AND model_name = ?'
                    params.append(model)

                # Add status filter if specified
                if status:
                    transcript_query += ' AND status = ?'
                    params.append(status)

                # Add date range filters
                if from_date:
                    transcript_query += ' AND created_at >= ?'
                    params.append(from_date)
                if to_date:
                    transcript_query += ' AND created_at <= ?'
                    params.append(to_date)

                union_queries.append(transcript_query)

            # 3. Search in Rekognition analysis results
            if 'rekognition' in active_sources:
                rekognition_query = '''
                SELECT
                    'rekognition' as source_type,
                    aj.id as source_id,
                    f.filename || ' - ' || aj.analysis_type as title,
                    aj.analysis_type as category,
                    aj.completed_at as timestamp,
                    'analysis_results' as match_field,
                    f.size_bytes,
                    f.duration_seconds
                FROM analysis_jobs aj
                JOIN files f ON aj.file_id = f.id
                WHERE aj.status = 'COMPLETED'
                AND aj.results IS NOT NULL
                AND CAST(aj.results AS TEXT) LIKE ?
                '''
                params.append(search_pattern)

                # Add file_type filter if specified
                if file_type:
                    rekognition_query += ' AND f.file_type = ?'
                    params.append(file_type)

                # Add analysis_type filter if specified
                if analysis_type:
                    rekognition_query += ' AND aj.analysis_type = ?'
                    params.append(analysis_type)

                # Add date range filters
                if from_date:
                    rekognition_query += ' AND aj.completed_at >= ?'
                    params.append(from_date)
                if to_date:
                    rekognition_query += ' AND aj.completed_at <= ?'
                    params.append(to_date)

                union_queries.append(rekognition_query)

            # 4. Search in Nova analysis
            if 'nova' in active_sources:
                nova_query = '''
                SELECT
                    'nova' as source_type,
                    nj.id as source_id,
                    f.filename || ' - Nova ' || nj.model as title,
                    'Nova Analysis' as category,
                    nj.completed_at as timestamp,
                    CASE
                        WHEN CAST(nj.summary_result AS TEXT) LIKE ? THEN 'summary'
                        WHEN CAST(nj.chapters_result AS TEXT) LIKE ? THEN 'chapters'
                        WHEN CAST(nj.elements_result AS TEXT) LIKE ? THEN 'elements'
                        WHEN CAST(nj.waterfall_classification_result AS TEXT) LIKE ? THEN 'waterfall_classification'
                    END as match_field,
                    f.size_bytes,
                    f.duration_seconds
                FROM nova_jobs nj
                JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id
                JOIN files f ON aj.file_id = f.id
                WHERE nj.status = 'COMPLETED'
                AND (
                    CAST(nj.summary_result AS TEXT) LIKE ? OR
                    CAST(nj.chapters_result AS TEXT) LIKE ? OR
                    CAST(nj.elements_result AS TEXT) LIKE ? OR
                    CAST(nj.waterfall_classification_result AS TEXT) LIKE ?
                )
                '''
                params.extend([search_pattern] * 8)

                # Add file_type filter if specified
                if file_type:
                    nova_query += ' AND f.file_type = ?'
                    params.append(file_type)

                # Add model filter if specified
                if model:
                    nova_query += ' AND nj.model = ?'
                    params.append(model)

                # Add date range filters
                if from_date:
                    nova_query += ' AND nj.completed_at >= ?'
                    params.append(from_date)
                if to_date:
                    nova_query += ' AND nj.completed_at <= ?'
                    params.append(to_date)

                union_queries.append(nova_query)

            # 5. Search in face collections
            if 'collection' in active_sources:
                collection_query = '''
                SELECT
                    'face_collection' as source_type,
                    id as source_id,
                    collection_id as title,
                    'Face Collection' as category,
                    created_at as timestamp,
                    'collection' as match_field,
                    NULL as size_bytes,
                    NULL as duration_seconds
                FROM face_collections
                WHERE collection_id LIKE ?
                '''
                params.append(search_pattern)

                # Add date range filters
                if from_date:
                    collection_query += ' AND created_at >= ?'
                    params.append(from_date)
                if to_date:
                    collection_query += ' AND created_at <= ?'
                    params.append(to_date)

                union_queries.append(collection_query)

            # Combine with UNION ALL
            if not union_queries:
                return []

            final_query = ' UNION ALL '.join(union_queries)

            # Add sorting
            if sort_by == 'date':
                final_query += f' ORDER BY timestamp {sort_order.upper()}'
            elif sort_by == 'name':
                final_query += f' ORDER BY title {sort_order.upper()}'
            else:  # relevance (default to date for now)
                final_query += f' ORDER BY timestamp {sort_order.upper()}'

            # Add pagination
            final_query += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            # Execute query
            cursor.execute(final_query, params)
            results = [dict(row) for row in cursor.fetchall()]

            return results

    def count_search_results(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        file_type: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        status: Optional[str] = None,
        analysis_type: Optional[str] = None,
        model: Optional[str] = None
    ) -> Dict[str, int]:
        """
        Count search results by source type.

        Returns: {
            'total': 145,
            'file': 23,
            'transcript': 67,
            'rekognition': 34,
            'nova': 19,
            'collection': 2
        }
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Build source filter
            all_sources = ['file', 'transcript', 'rekognition', 'nova', 'collection']
            active_sources = sources if sources else all_sources

            # Prepare search pattern for LIKE
            search_pattern = f'%{query}%'

            counts = {}
            total = 0

            # Count files
            if 'file' in active_sources:
                query_str = '''
                SELECT COUNT(*) as count FROM files
                WHERE (
                    filename LIKE ? OR
                    local_path LIKE ? OR
                    metadata LIKE ? OR
                    codec_video LIKE ? OR
                    codec_audio LIKE ?
                )
                '''
                params = [search_pattern] * 5

                if file_type:
                    query_str += ' AND file_type = ?'
                    params.append(file_type)
                if from_date:
                    query_str += ' AND uploaded_at >= ?'
                    params.append(from_date)
                if to_date:
                    query_str += ' AND uploaded_at <= ?'
                    params.append(to_date)

                cursor.execute(query_str, params)
                counts['file'] = cursor.fetchone()['count']
                total += counts['file']

            # Count transcripts
            if 'transcript' in active_sources:
                query_str = '''
                SELECT COUNT(*) as count FROM transcripts
                WHERE status = 'COMPLETED'
                AND (
                    transcript_text LIKE ? OR
                    file_name LIKE ?
                )
                '''
                params = [search_pattern, search_pattern]

                if model:
                    query_str += ' AND model_name = ?'
                    params.append(model)
                if status:
                    query_str += ' AND status = ?'
                    params.append(status)
                if from_date:
                    query_str += ' AND created_at >= ?'
                    params.append(from_date)
                if to_date:
                    query_str += ' AND created_at <= ?'
                    params.append(to_date)

                cursor.execute(query_str, params)
                counts['transcript'] = cursor.fetchone()['count']
                total += counts['transcript']

            # Count Rekognition results
            if 'rekognition' in active_sources:
                query_str = '''
                SELECT COUNT(*) as count FROM analysis_jobs aj
                JOIN files f ON aj.file_id = f.id
                WHERE aj.status = 'COMPLETED'
                AND aj.results IS NOT NULL
                AND CAST(aj.results AS TEXT) LIKE ?
                '''
                params = [search_pattern]

                if file_type:
                    query_str += ' AND f.file_type = ?'
                    params.append(file_type)
                if analysis_type:
                    query_str += ' AND aj.analysis_type = ?'
                    params.append(analysis_type)
                if from_date:
                    query_str += ' AND aj.completed_at >= ?'
                    params.append(from_date)
                if to_date:
                    query_str += ' AND aj.completed_at <= ?'
                    params.append(to_date)

                cursor.execute(query_str, params)
                counts['rekognition'] = cursor.fetchone()['count']
                total += counts['rekognition']

            # Count Nova results
            if 'nova' in active_sources:
                query_str = '''
                SELECT COUNT(*) as count FROM nova_jobs nj
                JOIN analysis_jobs aj ON nj.analysis_job_id = aj.id
                JOIN files f ON aj.file_id = f.id
                WHERE nj.status = 'COMPLETED'
                AND (
                    CAST(nj.summary_result AS TEXT) LIKE ? OR
                    CAST(nj.chapters_result AS TEXT) LIKE ? OR
                    CAST(nj.elements_result AS TEXT) LIKE ? OR
                    CAST(nj.waterfall_classification_result AS TEXT) LIKE ?
                )
                '''
                params = [search_pattern] * 4

                if file_type:
                    query_str += ' AND f.file_type = ?'
                    params.append(file_type)
                if model:
                    query_str += ' AND nj.model = ?'
                    params.append(model)
                if from_date:
                    query_str += ' AND nj.completed_at >= ?'
                    params.append(from_date)
                if to_date:
                    query_str += ' AND nj.completed_at <= ?'
                    params.append(to_date)

                cursor.execute(query_str, params)
                counts['nova'] = cursor.fetchone()['count']
                total += counts['nova']

            # Count collections
            if 'collection' in active_sources:
                query_str = '''
                SELECT COUNT(*) as count FROM face_collections
                WHERE collection_id LIKE ?
                '''
                params = [search_pattern]

                if from_date:
                    query_str += ' AND created_at >= ?'
                    params.append(from_date)
                if to_date:
                    query_str += ' AND created_at <= ?'
                    params.append(to_date)

                cursor.execute(query_str, params)
                counts['collection'] = cursor.fetchone()['count']
                total += counts['collection']

            counts['total'] = total
            return counts

    def get_search_filters(self) -> Dict[str, List[str]]:
        """
        Get available filter options from database.

        Queries distinct values for:
        - analysis_types
        - models (whisper + nova)
        - languages
        - statuses
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Get distinct analysis types
            cursor.execute('SELECT DISTINCT analysis_type FROM analysis_jobs ORDER BY analysis_type')
            analysis_types = [row['analysis_type'] for row in cursor.fetchall()]

            # Get distinct Whisper models
            cursor.execute('SELECT DISTINCT model_name FROM transcripts WHERE model_name IS NOT NULL ORDER BY model_name')
            whisper_models = [row['model_name'] for row in cursor.fetchall()]

            # Get distinct Nova models
            cursor.execute('SELECT DISTINCT model FROM nova_jobs WHERE model IS NOT NULL ORDER BY model')
            nova_models = [row['model'] for row in cursor.fetchall()]

            # Get distinct languages
            cursor.execute('SELECT DISTINCT language FROM transcripts WHERE language IS NOT NULL ORDER BY language')
            languages = [row['language'] for row in cursor.fetchall()]

            # Statuses (hardcoded common ones)
            statuses = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'SUBMITTED']

            # File types (hardcoded)
            file_types = ['video', 'image']

            return {
                'analysis_types': analysis_types,
                'models': {
                    'whisper': whisper_models,
                    'nova': nova_models
                },
                'languages': languages,
                'statuses': statuses,
                'file_types': file_types
            }

    # Helper methods for analysis_jobs integration
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
