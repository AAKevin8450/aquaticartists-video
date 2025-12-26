"""
Service for importing files from directories with progress tracking.

This service handles:
- Async directory scanning and file import
- Progress tracking with file counts
- Cancellation support
- Metadata extraction
"""
import os
import mimetypes
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable


class ImportService:
    """Service for importing files from directories with progress tracking."""

    def __init__(self, db, app):
        """Initialize the import service with database and app instance."""
        self.db = db
        self.app = app

    def run_import_job_async(self, job_id: str, directory_path: str, recursive: bool = True):
        """
        Run import job asynchronously in a background thread.

        Args:
            job_id: Unique job identifier
            directory_path: Directory to import from
            recursive: Whether to scan subdirectories
        """
        def _run_job():
            # Run everything within app context
            with self.app.app_context():
                # Import these here to avoid circular imports
                from app.utils.validators import get_file_type, ValidationError
                from app.utils.media_metadata import extract_media_metadata, MediaMetadataError

                try:
                    # Update job status
                    self.db.update_import_job_status(job_id, 'IN_PROGRESS')
                    self.db.update_import_job(job_id, {
                        'current_operation': 'Starting import...'
                    })

                    # Get allowed extensions from app config
                    allowed_video = self.app.config['ALLOWED_VIDEO_EXTENSIONS']
                    allowed_image = self.app.config['ALLOWED_IMAGE_EXTENSIONS']

                    # Counters
                    imported = 0
                    skipped_existing = 0
                    skipped_unsupported = 0
                    errors = []
                    scanned = 0

                    # First pass: count total files to scan
                    total_files = 0
                    if recursive:
                        for root, dirs, files in os.walk(directory_path, followlinks=True):
                            total_files += len(files)
                    else:
                        total_files = sum(1 for entry in os.scandir(directory_path) if entry.is_file())

                    self.db.update_import_job_progress(job_id, total_files=total_files)

                    def handle_file(file_path: str):
                        nonlocal imported, skipped_existing, skipped_unsupported, scanned, errors

                        # Check for cancellation
                        if self.db.is_import_job_cancelled(job_id):
                            return False  # Signal to stop

                        scanned += 1
                        abs_path = os.path.abspath(file_path)
                        filename = os.path.basename(abs_path)

                        try:
                            file_type = get_file_type(filename, allowed_video, allowed_image)
                        except ValidationError:
                            skipped_unsupported += 1
                            # Update progress every 10 files
                            if scanned % 10 == 0:
                                self.db.update_import_job_progress(
                                    job_id,
                                    files_scanned=scanned,
                                    files_imported=imported,
                                    files_skipped_existing=skipped_existing,
                                    files_skipped_unsupported=skipped_unsupported,
                                    current_operation=f'Importing files... ({filename})'
                                )
                            return True

                        if self.db.get_file_by_local_path(abs_path):
                            skipped_existing += 1
                            # Update progress every 10 files
                            if scanned % 10 == 0:
                                self.db.update_import_job_progress(
                                    job_id,
                                    files_scanned=scanned,
                                    files_imported=imported,
                                    files_skipped_existing=skipped_existing,
                                    files_skipped_unsupported=skipped_unsupported,
                                    current_operation=f'Importing files... ({filename})'
                                )
                            return True

                        try:
                            file_stat = os.stat(abs_path)
                        except OSError as e:
                            errors.append({'path': abs_path, 'error': str(e)})
                            # Update progress every 10 files
                            if scanned % 10 == 0:
                                self.db.update_import_job_progress(
                                    job_id,
                                    files_scanned=scanned,
                                    files_imported=imported,
                                    files_skipped_existing=skipped_existing,
                                    files_skipped_unsupported=skipped_unsupported,
                                    current_operation=f'Importing files... ({filename})'
                                )
                            return True

                        content_type = mimetypes.guess_type(abs_path)[0] or 'application/octet-stream'

                        media_metadata = {}
                        try:
                            media_metadata = extract_media_metadata(abs_path)
                        except MediaMetadataError:
                            pass  # Continue without metadata

                        self.db.create_source_file(
                            filename=filename,
                            s3_key=None,
                            file_type=file_type,
                            size_bytes=file_stat.st_size,
                            content_type=content_type,
                            local_path=abs_path,
                            resolution_width=media_metadata.get('resolution_width'),
                            resolution_height=media_metadata.get('resolution_height'),
                            frame_rate=media_metadata.get('frame_rate'),
                            codec_video=media_metadata.get('codec_video'),
                            codec_audio=media_metadata.get('codec_audio'),
                            duration_seconds=media_metadata.get('duration_seconds'),
                            bitrate=media_metadata.get('bitrate'),
                            metadata={
                                'imported_from': 'directory',
                                'source_directory': directory_path,
                                'original_size_bytes': file_stat.st_size,
                                'file_mtime': file_stat.st_mtime,
                                'file_ctime': file_stat.st_ctime
                            }
                        )
                        imported += 1

                        # Update progress every 10 files
                        if scanned % 10 == 0:
                            self.db.update_import_job_progress(
                                job_id,
                                files_scanned=scanned,
                                files_imported=imported,
                                files_skipped_existing=skipped_existing,
                                files_skipped_unsupported=skipped_unsupported,
                                current_operation=f'Importing files... ({filename})'
                            )

                        return True

                    # Process files
                    cancelled = False
                    if recursive:
                        seen_dirs = set()
                        for root, dirs, files in os.walk(directory_path, followlinks=True):
                            real_root = os.path.realpath(root)
                            if real_root in seen_dirs:
                                dirs[:] = []
                                continue
                            seen_dirs.add(real_root)

                            pruned_dirs = []
                            for name in dirs:
                                real_path = os.path.realpath(os.path.join(root, name))
                                if real_path not in seen_dirs:
                                    pruned_dirs.append(name)
                            dirs[:] = pruned_dirs

                            for name in files:
                                if not handle_file(os.path.join(root, name)):
                                    cancelled = True
                                    break

                            if cancelled:
                                break
                    else:
                        for entry in os.scandir(directory_path):
                            if entry.is_file():
                                if not handle_file(entry.path):
                                    cancelled = True
                                    break

                    # Final progress update
                    self.db.update_import_job_progress(
                        job_id,
                        files_scanned=scanned,
                        files_imported=imported,
                        files_skipped_existing=skipped_existing,
                        files_skipped_unsupported=skipped_unsupported,
                        current_operation='Completed'
                    )

                    # Check if cancelled
                    if self.db.is_import_job_cancelled(job_id):
                        return

                    # Store results
                    result_data = {
                        'scanned': scanned,
                        'imported': imported,
                        'skipped_existing': skipped_existing,
                        'skipped_unsupported': skipped_unsupported,
                        'errors': errors
                    }

                    # Mark job as completed
                    self.db.complete_import_job(job_id, result_data)

                except Exception as e:
                    # Mark job as failed
                    import traceback
                    error_details = f"{str(e)}\n{traceback.format_exc()}"
                    self.db.complete_import_job(job_id, {}, error_message=error_details)

        # Start background thread
        thread = threading.Thread(target=_run_job, daemon=True)
        thread.start()

    @staticmethod
    def generate_job_id() -> str:
        """Generate a unique job ID."""
        return f"import_{uuid.uuid4().hex[:12]}"
