"""
Service for rescanning directories and reconciling file changes.

This service handles:
- Detecting moved/renamed folders
- Identifying deleted files
- Finding new files
- Fingerprint-based file matching
- Importing new files discovered during rescan
"""
import os
import mimetypes
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Callable
from datetime import datetime
import uuid
import threading


class RescanService:
    """Service for rescanning directories and reconciling file changes."""

    def __init__(self, db, app=None):
        """Initialize the rescan service with a database instance and optional app."""
        self.db = db
        self.app = app

    @staticmethod
    def get_file_fingerprint(filename: str, size_bytes: int, mtime: float) -> str:
        """Generate a fingerprint for file matching."""
        return f"{filename}|{size_bytes}|{int(mtime)}"

    def scan_directory(self, directory_path: str, recursive: bool = True) -> List[Dict[str, Any]]:
        """
        Scan directory and return list of discovered files with fingerprints.

        Args:
            directory_path: Directory to scan
            recursive: Whether to scan subdirectories

        Returns:
            List of file dictionaries with metadata and fingerprints
        """
        discovered_files = []
        directory = Path(directory_path)

        if not directory.exists():
            raise ValueError(f"Directory does not exist: {directory_path}")

        if not directory.is_dir():
            raise ValueError(f"Path is not a directory: {directory_path}")

        # Get allowed extensions from app config or use defaults
        if self.app:
            allowed_video = self.app.config.get('ALLOWED_VIDEO_EXTENSIONS',
                {'mp4', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'webm', 'm4v'})
            allowed_image = self.app.config.get('ALLOWED_IMAGE_EXTENSIONS',
                {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'})
        else:
            allowed_video = {'mp4', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'webm', 'm4v'}
            allowed_image = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'}

        # Build supported extensions set (config uses no dots, add dot prefix)
        supported_extensions = {f'.{ext}' for ext in allowed_video | allowed_image}

        # Scan directory
        pattern = '**/*' if recursive else '*'
        for file_path in directory.glob(pattern):
            if not file_path.is_file():
                continue

            # Check if supported file type
            if file_path.suffix.lower() not in supported_extensions:
                continue

            try:
                stat = file_path.stat()
                discovered_files.append({
                    'path': str(file_path.absolute()),
                    'filename': file_path.name,
                    'size_bytes': stat.st_size,
                    'mtime': stat.st_mtime,
                    'fingerprint': self.get_file_fingerprint(
                        file_path.name,
                        stat.st_size,
                        stat.st_mtime
                    )
                })
            except (OSError, PermissionError) as e:
                # Skip files that can't be accessed
                print(f"Warning: Could not access {file_path}: {e}")
                continue

        return discovered_files

    def get_database_files_for_directory(self, directory_path: str) -> List[Dict[str, Any]]:
        """
        Get all database files whose current local_path is within this directory.

        This correctly scopes the rescan to only compare files that are currently
        expected to be in the scanned directory, preventing files from other
        directories from being incorrectly marked as "deleted".

        Args:
            directory_path: Directory path to query

        Returns:
            List of database file dictionaries with fingerprints and stats
        """
        # Only get files whose current path is within this directory
        db_files = self.db.get_files_by_current_directory(directory_path)
        result = []

        for file in db_files:
            metadata = file.get('metadata', {})
            mtime = metadata.get('file_mtime', 0)

            # Get relationship stats
            has_proxy = False
            has_analysis = False
            has_transcripts = False

            # Check for proxy
            proxy = self.db.get_proxy_for_source(file['id'])
            if proxy:
                has_proxy = True

            # Check for analysis jobs
            with self.db.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    'SELECT COUNT(*) as count FROM analysis_jobs WHERE file_id = ?',
                    (file['id'],)
                )
                row = cursor.fetchone()
                if row and row['count'] > 0:
                    has_analysis = True

                cursor.execute(
                    'SELECT COUNT(*) as count FROM transcripts WHERE file_path = ? OR file_id = ?',
                    (file['local_path'], file['id'])
                )
                row = cursor.fetchone()
                if row and row['count'] > 0:
                    has_transcripts = True

            result.append({
                'id': file['id'],
                'local_path': file['local_path'],
                'filename': file['filename'],
                'size_bytes': file['size_bytes'],
                'mtime': mtime,
                'fingerprint': self.get_file_fingerprint(
                    file['filename'],
                    file['size_bytes'],
                    mtime
                ),
                'has_proxy': has_proxy,
                'has_analysis': has_analysis,
                'has_transcripts': has_transcripts,
                'metadata': metadata
            })

        return result

    @staticmethod
    def normalize_path(path: str) -> str:
        """Normalize path separators for consistent comparison."""
        return path.replace('\\', '/') if path else path

    def reconcile(self, directory_path: str, mode: str = 'smart') -> Dict[str, List]:
        """
        Main reconciliation logic.

        Args:
            directory_path: Directory to rescan
            mode: 'smart' (fingerprint matching) or 'simple' (delete & reimport)

        Returns:
            Dictionary with categorized file changes:
            {
                'matched': [(db_file, disk_file), ...],      # Same path
                'moved': [(db_file, disk_file), ...],        # Different path, same fingerprint
                'deleted': [db_file, ...],                    # In DB but not on disk
                'new': [disk_file, ...],                      # On disk but not in DB
                'ambiguous': [(db_file, [disk_files]), ...]  # Multiple matches
            }
        """
        # Scan filesystem
        disk_files = self.scan_directory(directory_path)
        db_files = self.get_database_files_for_directory(directory_path)

        # Build fingerprint indexes with normalized paths for comparison
        disk_by_fingerprint = {}
        disk_by_path = {self.normalize_path(f['path']): f for f in disk_files}

        for f in disk_files:
            fp = f['fingerprint']
            if fp not in disk_by_fingerprint:
                disk_by_fingerprint[fp] = []
            disk_by_fingerprint[fp].append(f)

        db_by_fingerprint = {}
        db_by_path = {self.normalize_path(f['local_path']): f for f in db_files}

        for f in db_files:
            fp = f['fingerprint']
            if fp not in db_by_fingerprint:
                db_by_fingerprint[fp] = []
            db_by_fingerprint[fp].append(f)

        results = {
            'matched': [],
            'moved': [],
            'deleted': [],
            'new': [],
            'ambiguous': []
        }

        matched_db_ids = set()
        matched_disk_paths = set()  # Store normalized paths

        # Pass 1: Exact path matches (unchanged files)
        for db_file in db_files:
            normalized_db_path = self.normalize_path(db_file['local_path'])
            if normalized_db_path in disk_by_path:
                disk_file = disk_by_path[normalized_db_path]
                results['matched'].append((db_file, disk_file))
                matched_db_ids.add(db_file['id'])
                matched_disk_paths.add(self.normalize_path(disk_file['path']))

        # Pass 2: Fingerprint matches (moved files) - only if smart mode
        if mode == 'smart':
            for db_file in db_files:
                if db_file['id'] in matched_db_ids:
                    continue

                fp = db_file['fingerprint']
                candidates = [
                    f for f in disk_by_fingerprint.get(fp, [])
                    if self.normalize_path(f['path']) not in matched_disk_paths
                ]

                if len(candidates) == 1:
                    # Unique match - file was moved
                    results['moved'].append((db_file, candidates[0]))
                    matched_db_ids.add(db_file['id'])
                    matched_disk_paths.add(self.normalize_path(candidates[0]['path']))
                elif len(candidates) > 1:
                    # Multiple candidates - ambiguous
                    results['ambiguous'].append((db_file, candidates))
                    matched_db_ids.add(db_file['id'])

        # Pass 3: Identify deleted files (in DB, not on disk)
        for db_file in db_files:
            if db_file['id'] not in matched_db_ids:
                results['deleted'].append(db_file)

        # Pass 4: Identify new files (on disk, not in DB)
        for disk_file in disk_files:
            if self.normalize_path(disk_file['path']) not in matched_disk_paths:
                results['new'].append(disk_file)

        return results

    def apply_changes(self, reconcile_results: Dict[str, List],
                     options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply reconciliation changes to database.

        Args:
            reconcile_results: Output from reconcile()
            options: {
                'update_moved': True,       # Update paths for moved files
                'delete_missing': True,     # Delete files not found on disk
                'import_new': True,         # Import new files
                'handle_ambiguous': 'skip', # 'skip', 'delete', or 'first_match'
                'selected_files': {         # Optional: specific files to process
                    'moved': [file_ids],
                    'deleted': [file_ids],
                    'new': [file_paths]
                }
            }

        Returns:
            {
                'updated': int,
                'deleted': int,
                'imported': int,
                'skipped': int,
                'errors': [...]
            }
        """
        results = {
            'updated': 0,
            'deleted': 0,
            'imported': 0,
            'skipped': 0,
            'errors': []
        }

        selected = options.get('selected_files', {})

        # Handle moved files
        if options.get('update_moved', True):
            moved_selection = set(selected.get('moved', [])) if selected.get('moved') else None

            for db_file, disk_file in reconcile_results['moved']:
                # Skip if selection provided and this file not in it
                if moved_selection is not None and db_file['id'] not in moved_selection:
                    results['skipped'] += 1
                    continue

                try:
                    # Extract source directory from new path
                    new_path = Path(disk_file['path'])
                    new_source_dir = str(new_path.parent)

                    success = self.db.update_file_local_path_and_metadata(
                        db_file['id'],
                        disk_file['path'],
                        new_source_dir
                    )

                    if success:
                        results['updated'] += 1
                    else:
                        results['errors'].append({
                            'file_id': db_file['id'],
                            'error': 'Failed to update path'
                        })
                except Exception as e:
                    results['errors'].append({
                        'file_id': db_file['id'],
                        'error': str(e)
                    })

        # Handle deleted files
        if options.get('delete_missing', True):
            deleted_selection = set(selected.get('deleted', [])) if selected.get('deleted') else None

            file_ids_to_delete = []
            for db_file in reconcile_results['deleted']:
                # Skip if selection provided and this file not in it
                if deleted_selection is not None and db_file['id'] not in deleted_selection:
                    results['skipped'] += 1
                    continue

                file_ids_to_delete.append(db_file['id'])

            if file_ids_to_delete:
                try:
                    deleted_count = self.db.bulk_delete_files_by_ids(file_ids_to_delete)
                    results['deleted'] = deleted_count
                except Exception as e:
                    results['errors'].append({
                        'error': f'Bulk delete failed: {str(e)}'
                    })

        # Handle new files - import them into the database
        if options.get('import_new', False):
            new_selection = set(selected.get('new', [])) if selected.get('new') else None
            directory_path = options.get('directory_path', '')

            # Count files to import for skip_metadata decision
            files_to_import = []
            selection_normalized = {self.normalize_path(p) for p in new_selection} if new_selection else None

            for disk_file in reconcile_results['new']:
                disk_path_normalized = self.normalize_path(disk_file['path'])
                if selection_normalized is not None:
                    if disk_path_normalized not in selection_normalized:
                        results['skipped'] += 1
                        continue
                files_to_import.append(disk_file)

            # Skip metadata extraction for bulk imports (>50 files) - much faster
            skip_metadata = len(files_to_import) > 50

            for disk_file in files_to_import:
                try:
                    imported = self.import_file(
                        disk_file['path'],
                        directory_path,
                        skip_metadata=skip_metadata
                    )
                    if imported:
                        results['imported'] += 1
                    else:
                        results['skipped'] += 1
                except Exception as e:
                    results['errors'].append({
                        'path': disk_file['path'],
                        'error': str(e)
                    })

        # Handle ambiguous matches
        handle_ambiguous = options.get('handle_ambiguous', 'skip')
        if handle_ambiguous == 'delete':
            for db_file, candidates in reconcile_results['ambiguous']:
                try:
                    self.db.delete_file(db_file['id'])
                    results['deleted'] += 1
                except Exception as e:
                    results['errors'].append({
                        'file_id': db_file['id'],
                        'error': str(e)
                    })
        elif handle_ambiguous == 'first_match':
            for db_file, candidates in reconcile_results['ambiguous']:
                if candidates:
                    try:
                        disk_file = candidates[0]
                        new_path = Path(disk_file['path'])
                        new_source_dir = str(new_path.parent)

                        success = self.db.update_file_local_path_and_metadata(
                            db_file['id'],
                            disk_file['path'],
                            new_source_dir
                        )

                        if success:
                            results['updated'] += 1
                        else:
                            results['errors'].append({
                                'file_id': db_file['id'],
                                'error': 'Failed to update path'
                            })
                    except Exception as e:
                        results['errors'].append({
                            'file_id': db_file['id'],
                            'error': str(e)
                        })

        return results

    def import_file(self, file_path: str, source_directory: str = '',
                    skip_metadata: bool = False) -> bool:
        """
        Import a single file into the database.

        Args:
            file_path: Full path to the file
            source_directory: Directory path for metadata
            skip_metadata: If True, skip ffprobe metadata extraction (faster for bulk imports)

        Returns:
            True if imported successfully, False if skipped
        """
        from app.utils.validators import get_file_type, ValidationError
        from app.utils.media_metadata import extract_media_metadata, MediaMetadataError

        abs_path = os.path.abspath(file_path)
        filename = os.path.basename(abs_path)

        # Get allowed extensions from app config or use defaults (no dots, as get_file_type expects)
        if self.app:
            allowed_video = self.app.config.get('ALLOWED_VIDEO_EXTENSIONS',
                {'mp4', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'webm', 'm4v'})
            allowed_image = self.app.config.get('ALLOWED_IMAGE_EXTENSIONS',
                {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'})
        else:
            allowed_video = {'mp4', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'webm', 'm4v'}
            allowed_image = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'}

        # Validate file type
        try:
            file_type = get_file_type(filename, allowed_video, allowed_image)
        except ValidationError:
            return False  # Unsupported file type

        # Check if already exists
        if self.db.get_file_by_local_path(abs_path):
            return False  # Already in database

        # Get file stats
        try:
            file_stat = os.stat(abs_path)
        except OSError:
            return False

        # Determine content type
        content_type = mimetypes.guess_type(abs_path)[0] or 'application/octet-stream'

        # Extract media metadata (skip for bulk imports to improve speed)
        media_metadata = {}
        if not skip_metadata:
            try:
                media_metadata = extract_media_metadata(abs_path)
            except MediaMetadataError:
                pass  # Continue without metadata

        # Use file's parent directory if source_directory not provided
        if not source_directory:
            source_directory = str(Path(abs_path).parent)

        # Create file record
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
                'imported_from': 'rescan',
                'source_directory': source_directory,
                'original_size_bytes': file_stat.st_size,
                'file_mtime': file_stat.st_mtime,
                'file_ctime': file_stat.st_ctime
            }
        )

        return True

    def scan_directory_with_progress(self, directory_path: str, recursive: bool = True,
                                     progress_callback: Optional[Callable] = None,
                                     job_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Scan directory with progress tracking.

        Args:
            directory_path: Directory to scan
            recursive: Whether to scan subdirectories
            progress_callback: Function to call with progress updates (files_scanned, total_estimate)
            job_id: Job ID for cancellation check

        Returns:
            List of file dictionaries with metadata and fingerprints
        """
        discovered_files = []
        directory = Path(directory_path)

        if not directory.exists():
            raise ValueError(f"Directory does not exist: {directory_path}")

        if not directory.is_dir():
            raise ValueError(f"Path is not a directory: {directory_path}")

        # Get allowed extensions from app config or use defaults
        if self.app:
            allowed_video = self.app.config.get('ALLOWED_VIDEO_EXTENSIONS',
                {'mp4', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'webm', 'm4v'})
            allowed_image = self.app.config.get('ALLOWED_IMAGE_EXTENSIONS',
                {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'})
        else:
            allowed_video = {'mp4', 'mov', 'avi', 'mkv', 'flv', 'wmv', 'webm', 'm4v'}
            allowed_image = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp'}

        # Build supported extensions set (config uses no dots, add dot prefix)
        supported_extensions = {f'.{ext}' for ext in allowed_video | allowed_image}

        # Scan directory
        pattern = '**/*' if recursive else '*'
        files_scanned = 0

        for file_path in directory.glob(pattern):
            # Check for cancellation
            if job_id and self.db.is_rescan_job_cancelled(job_id):
                break

            if not file_path.is_file():
                continue

            # Check if supported file type
            if file_path.suffix.lower() not in supported_extensions:
                continue

            try:
                stat = file_path.stat()
                discovered_files.append({
                    'path': str(file_path.absolute()),
                    'filename': file_path.name,
                    'size_bytes': stat.st_size,
                    'mtime': stat.st_mtime,
                    'fingerprint': self.get_file_fingerprint(
                        file_path.name,
                        stat.st_size,
                        stat.st_mtime
                    )
                })

                files_scanned += 1

                # Report progress every 10 files
                if progress_callback and files_scanned % 10 == 0:
                    progress_callback(files_scanned, len(discovered_files))

            except (OSError, PermissionError) as e:
                # Skip files that can't be accessed
                print(f"Warning: Could not access {file_path}: {e}")
                continue

        # Final progress update
        if progress_callback:
            progress_callback(files_scanned, len(discovered_files))

        return discovered_files

    def reconcile_with_progress(self, directory_path: str, mode: str = 'smart',
                               progress_callback: Optional[Callable] = None,
                               job_id: Optional[str] = None) -> Dict[str, List]:
        """
        Reconcile with progress tracking.

        Args:
            directory_path: Directory to rescan
            mode: 'smart' (fingerprint matching) or 'simple' (delete & reimport)
            progress_callback: Function to call with progress updates
            job_id: Job ID for cancellation check

        Returns:
            Dictionary with categorized file changes
        """
        # Update status
        if job_id and progress_callback:
            self.db.update_rescan_job(job_id, {
                'current_operation': 'Scanning filesystem...',
                'status': 'IN_PROGRESS'
            })

        # Scan filesystem with progress
        disk_files = self.scan_directory_with_progress(
            directory_path,
            recursive=True,
            progress_callback=lambda scanned, total: (
                self.db.update_rescan_job_progress(
                    job_id,
                    files_scanned=scanned,
                    total_files=total,
                    current_operation='Scanning filesystem...'
                ) if job_id else None
            ),
            job_id=job_id
        )

        # Check for cancellation
        if job_id and self.db.is_rescan_job_cancelled(job_id):
            return {
                'matched': [],
                'moved': [],
                'deleted': [],
                'new': [],
                'ambiguous': []
            }

        # Update status
        if job_id:
            self.db.update_rescan_job(job_id, {
                'current_operation': 'Loading database files...'
            })

        db_files = self.get_database_files_for_directory(directory_path)

        # Update status
        if job_id:
            self.db.update_rescan_job(job_id, {
                'current_operation': 'Reconciling files...'
            })

        # Build fingerprint indexes with normalized paths for comparison
        disk_by_fingerprint = {}
        disk_by_path = {self.normalize_path(f['path']): f for f in disk_files}

        for f in disk_files:
            fp = f['fingerprint']
            if fp not in disk_by_fingerprint:
                disk_by_fingerprint[fp] = []
            disk_by_fingerprint[fp].append(f)

        db_by_fingerprint = {}
        db_by_path = {self.normalize_path(f['local_path']): f for f in db_files}

        for f in db_files:
            fp = f['fingerprint']
            if fp not in db_by_fingerprint:
                db_by_fingerprint[fp] = []
            db_by_fingerprint[fp].append(f)

        results = {
            'matched': [],
            'moved': [],
            'deleted': [],
            'new': [],
            'ambiguous': []
        }

        matched_db_ids = set()
        matched_disk_paths = set()  # Store normalized paths

        # Pass 1: Exact path matches (unchanged files)
        for db_file in db_files:
            normalized_db_path = self.normalize_path(db_file['local_path'])
            if normalized_db_path in disk_by_path:
                disk_file = disk_by_path[normalized_db_path]
                results['matched'].append((db_file, disk_file))
                matched_db_ids.add(db_file['id'])
                matched_disk_paths.add(self.normalize_path(disk_file['path']))

        # Pass 2: Fingerprint matches (moved files) - only if smart mode
        if mode == 'smart':
            for db_file in db_files:
                if db_file['id'] in matched_db_ids:
                    continue

                fp = db_file['fingerprint']
                candidates = [
                    f for f in disk_by_fingerprint.get(fp, [])
                    if self.normalize_path(f['path']) not in matched_disk_paths
                ]

                if len(candidates) == 1:
                    # Unique match - file was moved
                    results['moved'].append((db_file, candidates[0]))
                    matched_db_ids.add(db_file['id'])
                    matched_disk_paths.add(self.normalize_path(candidates[0]['path']))
                elif len(candidates) > 1:
                    # Multiple candidates - ambiguous
                    results['ambiguous'].append((db_file, candidates))
                    matched_db_ids.add(db_file['id'])

        # Pass 3: Identify deleted files (in DB, not on disk)
        for db_file in db_files:
            if db_file['id'] not in matched_db_ids:
                results['deleted'].append(db_file)

        # Pass 4: Identify new files (on disk, not in DB)
        for disk_file in disk_files:
            if self.normalize_path(disk_file['path']) not in matched_disk_paths:
                results['new'].append(disk_file)

        return results

    def run_rescan_job_async(self, job_id: str, directory_path: str, recursive: bool = True):
        """
        Run rescan job asynchronously in a background thread.

        Args:
            job_id: Unique job identifier
            directory_path: Directory to scan
            recursive: Whether to scan subdirectories
        """
        def _run_job():
            try:
                # Update job status
                self.db.update_rescan_job_status(job_id, 'IN_PROGRESS')

                # Run reconciliation with progress tracking
                results = self.reconcile_with_progress(
                    directory_path,
                    mode='smart',
                    job_id=job_id
                )

                # Check if cancelled
                if self.db.is_rescan_job_cancelled(job_id):
                    return

                # Prepare summary
                summary = {
                    'total_on_disk': len(results['matched']) + len(results['moved']) + len(results['new']),
                    'total_in_database': len(results['matched']) + len(results['moved']) + len(results['deleted']),
                    'matched': len(results['matched']),
                    'moved': len(results['moved']),
                    'deleted': len(results['deleted']),
                    'new': len(results['new']),
                    'ambiguous': len(results['ambiguous'])
                }

                # Store results
                result_data = {
                    'summary': summary,
                    'details': {
                        'moved': [
                            {
                                'db_file': {
                                    'id': db_file['id'],
                                    'path': db_file['local_path'],
                                    'filename': db_file['filename'],
                                    'has_proxy': db_file['has_proxy'],
                                    'has_analysis': db_file['has_analysis'],
                                    'has_transcripts': db_file['has_transcripts']
                                },
                                'disk_file': {
                                    'path': disk_file['path'],
                                    'filename': disk_file['filename'],
                                    'size_bytes': disk_file['size_bytes']
                                }
                            }
                            for db_file, disk_file in results['moved']
                        ],
                        'deleted': [
                            {
                                'id': db_file['id'],
                                'path': db_file['local_path'],
                                'filename': db_file['filename'],
                                'has_proxy': db_file['has_proxy'],
                                'has_analysis': db_file['has_analysis'],
                                'has_transcripts': db_file['has_transcripts']
                            }
                            for db_file in results['deleted']
                        ],
                        'new': [
                            {
                                'path': disk_file['path'],
                                'filename': disk_file['filename'],
                                'size_bytes': disk_file['size_bytes']
                            }
                            for disk_file in results['new']
                        ],
                        'ambiguous': [
                            {
                                'db_file': {
                                    'id': db_file['id'],
                                    'path': db_file['local_path'],
                                    'filename': db_file['filename']
                                },
                                'candidates': [
                                    {
                                        'path': c['path'],
                                        'filename': c['filename']
                                    }
                                    for c in candidates
                                ]
                            }
                            for db_file, candidates in results['ambiguous']
                        ]
                    }
                }

                # Mark job as completed
                self.db.complete_rescan_job(job_id, result_data)

            except Exception as e:
                # Mark job as failed
                self.db.complete_rescan_job(job_id, {}, error_message=str(e))

        # Start background thread
        thread = threading.Thread(target=_run_job, daemon=True)
        thread.start()

    @staticmethod
    def generate_job_id() -> str:
        """Generate a unique job ID."""
        return f"rescan_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def generate_apply_job_id() -> str:
        """Generate a unique apply job ID."""
        return f"apply_{uuid.uuid4().hex[:12]}"

    def run_apply_job_async(self, job_id: str, directory_path: str,
                            selected_files: Dict[str, List],
                            actions: Dict[str, Any]):
        """
        Run apply changes job asynchronously in a background thread.

        Args:
            job_id: Unique job identifier
            directory_path: Directory being processed
            selected_files: Dict with 'moved', 'deleted', 'new' lists
            actions: Dict with action flags
        """
        def _run_job():
            try:
                # Update job status
                self.db.update_import_job_status(job_id, 'IN_PROGRESS')
                self.db.update_import_job(job_id, {
                    'current_operation': 'Starting...'
                })

                # Run reconciliation first
                self.db.update_import_job(job_id, {
                    'current_operation': 'Scanning directory...'
                })

                reconcile_results = self.reconcile(directory_path, mode='smart')

                # Check for cancellation
                if self.db.is_import_job_cancelled(job_id):
                    return

                # Prepare for apply
                results = {
                    'updated': 0,
                    'deleted': 0,
                    'imported': 0,
                    'skipped': 0,
                    'errors': []
                }

                selected = selected_files or {}
                total_operations = 0
                completed_operations = 0

                # Count total operations
                if actions.get('update_moved', False) and selected.get('moved'):
                    total_operations += len(selected['moved'])
                if actions.get('delete_missing', False) and selected.get('deleted'):
                    total_operations += len(selected['deleted'])
                if actions.get('import_new', False) and selected.get('new'):
                    total_operations += len(selected['new'])

                self.db.update_import_job_progress(job_id, total_files=total_operations)

                # Handle moved files
                if actions.get('update_moved', False):
                    moved_selection = set(selected.get('moved', [])) if selected.get('moved') else None

                    self.db.update_import_job(job_id, {
                        'current_operation': 'Updating moved files...'
                    })

                    for db_file, disk_file in reconcile_results['moved']:
                        if self.db.is_import_job_cancelled(job_id):
                            return

                        if moved_selection is not None and db_file['id'] not in moved_selection:
                            results['skipped'] += 1
                            continue

                        try:
                            new_path = Path(disk_file['path'])
                            new_source_dir = str(new_path.parent)
                            success = self.db.update_file_local_path_and_metadata(
                                db_file['id'], disk_file['path'], new_source_dir
                            )
                            if success:
                                results['updated'] += 1
                            else:
                                results['errors'].append({
                                    'file_id': db_file['id'],
                                    'error': 'Failed to update path'
                                })
                        except Exception as e:
                            results['errors'].append({
                                'file_id': db_file['id'],
                                'error': str(e)
                            })

                        completed_operations += 1
                        self.db.update_import_job_progress(
                            job_id,
                            files_scanned=completed_operations,
                            files_imported=results['imported']
                        )

                # Handle deleted files
                if actions.get('delete_missing', False):
                    deleted_selection = set(selected.get('deleted', [])) if selected.get('deleted') else None

                    self.db.update_import_job(job_id, {
                        'current_operation': 'Removing deleted files...'
                    })

                    file_ids_to_delete = []
                    for db_file in reconcile_results['deleted']:
                        if self.db.is_import_job_cancelled(job_id):
                            return

                        if deleted_selection is not None and db_file['id'] not in deleted_selection:
                            results['skipped'] += 1
                            completed_operations += 1
                            continue

                        file_ids_to_delete.append(db_file['id'])
                        completed_operations += 1

                    if file_ids_to_delete:
                        try:
                            deleted_count = self.db.bulk_delete_files_by_ids(file_ids_to_delete)
                            results['deleted'] = deleted_count
                        except Exception as e:
                            results['errors'].append({
                                'error': f'Bulk delete failed: {str(e)}'
                            })

                    self.db.update_import_job_progress(
                        job_id,
                        files_scanned=completed_operations,
                        files_imported=results['imported']
                    )

                # Handle new files - import with full metadata
                if actions.get('import_new', False):
                    new_selection = set(selected.get('new', [])) if selected.get('new') else None
                    selection_normalized = {self.normalize_path(p) for p in new_selection} if new_selection else None

                    # Build list of files to import
                    files_to_import = []
                    for disk_file in reconcile_results['new']:
                        disk_path_normalized = self.normalize_path(disk_file['path'])
                        if selection_normalized is not None:
                            if disk_path_normalized not in selection_normalized:
                                results['skipped'] += 1
                                continue
                        files_to_import.append(disk_file)

                    # Import files one by one with progress updates
                    for i, disk_file in enumerate(files_to_import):
                        if self.db.is_import_job_cancelled(job_id):
                            return

                        # Update progress
                        self.db.update_import_job(job_id, {
                            'current_operation': f'Importing {i+1}/{len(files_to_import)}: {disk_file["filename"]}'
                        })

                        try:
                            # Import with full metadata extraction
                            imported = self.import_file(
                                disk_file['path'],
                                directory_path,
                                skip_metadata=False  # Full metadata for async imports
                            )
                            if imported:
                                results['imported'] += 1
                            else:
                                results['skipped'] += 1
                        except Exception as e:
                            results['errors'].append({
                                'path': disk_file['path'],
                                'error': str(e)
                            })

                        completed_operations += 1
                        self.db.update_import_job_progress(
                            job_id,
                            files_scanned=completed_operations,
                            files_imported=results['imported']
                        )

                # Complete the job
                self.db.complete_import_job(job_id, results)

            except Exception as e:
                # Mark job as failed
                self.db.complete_import_job(job_id, {}, error_message=str(e))

        # Start background thread
        thread = threading.Thread(target=_run_job, daemon=True)
        thread.start()
