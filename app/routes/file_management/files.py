"""
Core file CRUD endpoints placeholder.

NOTE: Core file CRUD routes are currently in core.py (the original file_management.py).
This module is reserved for future extraction of:
- GET /files (page route)
- GET /api/files (list files)
- GET /api/files/<int:file_id> (get file details)
- DELETE /api/files/<int:file_id> (delete file)
- GET /api/files/<int:file_id>/s3-files
- GET /api/files/<int:file_id>/nova-analyses
- POST /api/files/<int:file_id>/create-proxy
- POST /api/files/<int:file_id>/start-analysis
- POST /api/files/<int:file_id>/start-transcription
- POST /api/files/<int:file_id>/start-nova

These routes are currently handled by the main blueprint in core.py.
This file can be used in a future refactoring session to extract and
organize these routes separately.
"""
# Future extraction target - routes currently in core.py
