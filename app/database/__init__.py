"""
Database package for AWS Video & Image Analysis Application.

This package provides a modular database layer using mixins for different domains.
The Database class combines all mixins into a unified interface.

Usage:
    from app.database import get_db

    db = get_db()
    file = db.get_file(file_id)
"""

from app.database.base import DatabaseBase
from app.database.files import FilesMixin
from app.database.transcripts import TranscriptsMixin
from app.database.embeddings import EmbeddingsMixin
from app.database.nova_jobs import NovaJobsMixin
from app.database.analysis_jobs import AnalysisJobsMixin
from app.database.async_jobs import AsyncJobsMixin
from app.database.search import SearchMixin
from app.database.billing_cache import BillingCacheMixin
from app.database.batch_jobs import BedrockBatchJobsMixin


class Database(
    DatabaseBase,
    FilesMixin,
    TranscriptsMixin,
    EmbeddingsMixin,
    NovaJobsMixin,
    AnalysisJobsMixin,
    AsyncJobsMixin,
    SearchMixin,
    BillingCacheMixin,
    BedrockBatchJobsMixin
):
    """
    Unified database interface combining all domain-specific mixins.

    Inherits from:
        - DatabaseBase: Connection management, schema creation, JSON helpers
        - FilesMixin: File CRUD operations (create, get, list, delete files)
        - TranscriptsMixin: Transcript operations (create, update, list transcripts)
        - EmbeddingsMixin: Vector embedding operations (create, search embeddings)
        - NovaJobsMixin: Nova analysis job operations
        - AnalysisJobsMixin: Analysis job operations
        - AsyncJobsMixin: Rescan and import job operations
        - SearchMixin: Search and statistics operations
        - BillingCacheMixin: AWS billing cache operations
        - BedrockBatchJobsMixin: Bedrock batch job tracking operations
    """
    pass


# Singleton instance for application-wide database access
_db_instance = None


def init_db(app) -> Database:
    """
    Initialize database with Flask app.

    This function creates the singleton database instance using the
    DATABASE_PATH from the Flask app configuration.

    Args:
        app: Flask application instance

    Returns:
        Database instance
    """
    global _db_instance
    db_path = app.config.get('DATABASE_PATH', 'data/app.db')
    _db_instance = Database(db_path)
    return _db_instance


def get_db(db_path: str = None) -> Database:
    """
    Get the singleton Database instance.

    Args:
        db_path: Optional path to database file. If not provided, uses
                 DATABASE_PATH environment variable or defaults to 'data/app.db'.

    Returns:
        Database instance
    """
    global _db_instance
    import os

    if _db_instance is None:
        path = db_path or os.getenv('DATABASE_PATH', 'data/app.db')
        _db_instance = Database(path)

    return _db_instance


def reset_db():
    """Reset the singleton instance (for testing)."""
    global _db_instance
    _db_instance = None


# Re-export for backward compatibility
__all__ = ['Database', 'get_db', 'init_db', 'reset_db']
