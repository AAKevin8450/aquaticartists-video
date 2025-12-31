"""
File management routes package.

This package provides modular file management routes:
- core.py: Main file CRUD operations and legacy routes
- shared.py: BatchJob class and shared utilities
- batch.py: Batch processing operations
- s3_files.py: S3 file browser operations
- directory_browser.py: Directory browsing
- import_jobs.py: Import job operations
- rescan_jobs.py: Rescan job operations

Blueprints are exported for registration in the main app.
"""
from app.routes.file_management.shared import (
    BatchJob,
    get_batch_job,
    set_batch_job,
    delete_batch_job,
    normalize_transcription_provider,
    select_latest_completed_transcript,
)

# Import main blueprint (contains legacy routes still being migrated)
from app.routes.file_management.core import bp

# Import blueprints from submodules
from app.routes.file_management.directory_browser import bp as directory_browser_bp
from app.routes.file_management.import_jobs import bp as import_jobs_bp
from app.routes.file_management.rescan_jobs import bp as rescan_jobs_bp
from app.routes.file_management.s3_files import bp as s3_files_bp
from app.routes.file_management.batch import bp as batch_bp

__all__ = [
    # Main blueprint
    'bp',
    # Shared utilities
    'BatchJob',
    'get_batch_job',
    'set_batch_job',
    'delete_batch_job',
    'normalize_transcription_provider',
    'select_latest_completed_transcript',
    # Blueprints
    'directory_browser_bp',
    'import_jobs_bp',
    'rescan_jobs_bp',
    's3_files_bp',
    'batch_bp',
]
