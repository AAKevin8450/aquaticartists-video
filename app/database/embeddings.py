"""Embedding operations mixin for database."""
import json
import struct
from datetime import datetime
from typing import Optional, List, Dict, Any


class EmbeddingsMixin:
    """Mixin providing vector embedding operations."""

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
