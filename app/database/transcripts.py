"""Transcript operations mixin for database."""
import json
from typing import Optional, List, Dict, Any


class TranscriptsMixin:
    """Mixin providing transcript CRUD operations."""

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

    def update_transcript_summary(self, transcript_id: int, transcript_summary: str) -> None:
        """Update transcript summary text."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE transcripts
                SET transcript_summary = ?
                WHERE id = ?
            ''', (transcript_summary, transcript_id))

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
