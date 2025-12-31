"""File operations mixin for database."""
import json
import hashlib
import os
from datetime import datetime
from typing import Optional, List, Dict, Any


class FilesMixin:
    """Mixin providing file CRUD operations."""

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

    def get_file_with_transcript_summary(self, file_id: int) -> Optional[Dict[str, Any]]:
        """
        Get file record with associated transcript summary via LEFT JOIN.
        Matches files to transcripts via local_path.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    f.id, f.filename, f.local_path, f.duration_seconds,
                    t.transcript_summary
                FROM files f
                LEFT JOIN transcripts t ON f.local_path = t.file_path
                WHERE f.id = ?
            ''', (file_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

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

    def get_files_by_source_directory(self, directory_path: str) -> List[Dict[str, Any]]:
        """Get all files that were imported from a specific directory (including subdirs)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM files
                WHERE local_path IS NOT NULL
                AND json_extract(metadata, '$.source_directory') LIKE ?
            ''', (f"{directory_path}%",))
            files = [dict(row) for row in cursor.fetchall()]
            for file in files:
                if 'metadata' in file:
                    file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return files

    def get_file_by_fingerprint(self, filename: str, size_bytes: int, mtime: float,
                                mtime_tolerance: int = 2) -> Optional[Dict[str, Any]]:
        """Find file by fingerprint (name + size + approx mtime)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM files
                WHERE filename = ?
                AND size_bytes = ?
                AND ABS(CAST(json_extract(metadata, '$.file_mtime') AS REAL) - ?) < ?
                AND local_path IS NOT NULL
                LIMIT 1
            ''', (filename, size_bytes, mtime, mtime_tolerance))
            row = cursor.fetchone()
            if not row:
                return None
            file = dict(row)
            if 'metadata' in file:
                file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return file

    def update_file_local_path_and_metadata(self, file_id: int, new_local_path: str,
                                            new_source_directory: str) -> bool:
        """Update file path and source directory without touching related records."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Get current metadata
            cursor.execute('SELECT metadata FROM files WHERE id = ?', (file_id,))
            row = cursor.fetchone()
            if not row:
                return False

            metadata = self._parse_json_field(row['metadata'], default={})
            metadata['source_directory'] = new_source_directory

            # Update both local_path and metadata
            cursor.execute('''
                UPDATE files
                SET local_path = ?, metadata = ?
                WHERE id = ?
            ''', (new_local_path, json.dumps(metadata), file_id))
            return cursor.rowcount > 0

    def get_all_local_files(self) -> List[Dict[str, Any]]:
        """Get all files with local_path set (imported files only)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM files WHERE local_path IS NOT NULL')
            files = [dict(row) for row in cursor.fetchall()]
            for file in files:
                if 'metadata' in file:
                    file['metadata'] = self._parse_json_field(file['metadata'], default={})
            return files

    def bulk_delete_files_by_ids(self, file_ids: List[int]) -> int:
        """Delete multiple files by ID (cascades to related tables)."""
        if not file_ids:
            return 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ','.join('?' * len(file_ids))
            cursor.execute(f'DELETE FROM files WHERE id IN ({placeholders})', file_ids)
            return cursor.rowcount

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
