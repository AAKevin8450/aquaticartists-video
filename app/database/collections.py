"""Face collection operations mixin for database."""
import json
from typing import Optional, List, Dict, Any


class CollectionsMixin:
    """Mixin providing face collection CRUD operations."""

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
