"""
Service for rescanning directories and reconciling file changes.

This service handles:
- Detecting moved/renamed folders
- Identifying deleted files
- Finding new files
- Fingerprint-based file matching
"""
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime


class RescanService:
    """Service for rescanning directories and reconciling file changes."""

    def __init__(self, db):
        """Initialize the rescan service with a database instance."""
        self.db = db

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

        # Supported video and image extensions
        video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm', '.m4v'}
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
        supported_extensions = video_extensions | image_extensions

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
        Get all database files that were originally imported from this directory.

        Args:
            directory_path: Directory path to query

        Returns:
            List of database file dictionaries with fingerprints and stats
        """
        db_files = self.db.get_files_by_source_directory(directory_path)
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

        # Build fingerprint indexes
        disk_by_fingerprint = {}
        disk_by_path = {f['path']: f for f in disk_files}

        for f in disk_files:
            fp = f['fingerprint']
            if fp not in disk_by_fingerprint:
                disk_by_fingerprint[fp] = []
            disk_by_fingerprint[fp].append(f)

        db_by_fingerprint = {}
        db_by_path = {f['local_path']: f for f in db_files}

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
        matched_disk_paths = set()

        # Pass 1: Exact path matches (unchanged files)
        for db_file in db_files:
            if db_file['local_path'] in disk_by_path:
                disk_file = disk_by_path[db_file['local_path']]
                results['matched'].append((db_file, disk_file))
                matched_db_ids.add(db_file['id'])
                matched_disk_paths.add(disk_file['path'])

        # Pass 2: Fingerprint matches (moved files) - only if smart mode
        if mode == 'smart':
            for db_file in db_files:
                if db_file['id'] in matched_db_ids:
                    continue

                fp = db_file['fingerprint']
                candidates = [
                    f for f in disk_by_fingerprint.get(fp, [])
                    if f['path'] not in matched_disk_paths
                ]

                if len(candidates) == 1:
                    # Unique match - file was moved
                    results['moved'].append((db_file, candidates[0]))
                    matched_db_ids.add(db_file['id'])
                    matched_disk_paths.add(candidates[0]['path'])
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
            if disk_file['path'] not in matched_disk_paths:
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

        # Handle new files - just report them for now, don't auto-import
        # The user should use the regular import flow for new files
        if options.get('import_new', False):
            new_selection = set(selected.get('new', [])) if selected.get('new') else None

            for disk_file in reconcile_results['new']:
                if new_selection is not None and disk_file['path'] not in new_selection:
                    results['skipped'] += 1
                    continue

                # Note: Auto-import would require S3 upload logic
                # For now, we'll just skip this and let users import manually
                results['skipped'] += 1

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
