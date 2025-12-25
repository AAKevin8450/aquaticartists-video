#!/usr/bin/env python3
"""
Reconcile proxy video files with database records.
Fixes orphaned proxy files and missing database records after rescan operations.

Run with: python -m scripts.reconcile_proxies [--dry-run] [--delete-orphans]
"""
import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tqdm import tqdm
from app.database import Database
from app.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Proxy filename pattern: {originalname}_{source_file_id}_720p15.{ext}
PROXY_PATTERN = re.compile(r'^(.+)_(\d+)_720p15\.(\w+)$')


def parse_proxy_filename(filename: str) -> Optional[Tuple[str, int, str]]:
    """
    Parse proxy filename to extract source_file_id.

    Returns:
        Tuple of (original_name, source_file_id, extension) or None if invalid
    """
    match = PROXY_PATTERN.match(filename)
    if match:
        original_name = match.group(1)
        source_file_id = int(match.group(2))
        extension = match.group(3)
        return (original_name, source_file_id, extension)
    return None


def scan_proxy_folder(proxy_dir: Path) -> Dict[int, Dict]:
    """
    Scan proxy_video folder and return dict keyed by source_file_id.

    Returns:
        Dict mapping source_file_id to file info (path, size, name)
    """
    proxy_files = {}

    for file_path in proxy_dir.iterdir():
        if not file_path.is_file():
            continue

        parsed = parse_proxy_filename(file_path.name)
        if not parsed:
            logger.warning(f"Unrecognized proxy filename: {file_path.name}")
            continue

        original_name, source_file_id, extension = parsed
        file_size = file_path.stat().st_size

        if source_file_id in proxy_files:
            logger.warning(f"Duplicate proxy for source_file_id {source_file_id}: {file_path.name}")
            continue

        proxy_files[source_file_id] = {
            'path': file_path,
            'size': file_size,
            'name': file_path.name,
            'original_name': original_name,
            'extension': extension
        }

    return proxy_files


def get_database_state(db: Database) -> Tuple[Dict[int, Dict], set, set]:
    """
    Get current database state for proxies.

    Returns:
        Tuple of (proxy_records, valid_source_ids, all_file_ids)
        - proxy_records: Dict mapping source_file_id to proxy record
        - valid_source_ids: Set of source file IDs that exist in DB
        - all_file_ids: Set of all file IDs
    """
    proxy_records = {}
    valid_source_ids = set()
    all_file_ids = set()

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Get all proxy records
        cursor.execute('''
            SELECT id, source_file_id, filename, size_bytes, local_path
            FROM files
            WHERE is_proxy = 1
        ''')

        for row in cursor.fetchall():
            proxy_records[row['source_file_id']] = {
                'id': row['id'],
                'source_file_id': row['source_file_id'],
                'filename': row['filename'],
                'size_bytes': row['size_bytes'],
                'local_path': row['local_path']
            }

        # Get all valid source file IDs
        cursor.execute('SELECT id FROM files WHERE is_proxy = 0')
        valid_source_ids = {row['id'] for row in cursor.fetchall()}

        # Get all file IDs
        cursor.execute('SELECT id FROM files')
        all_file_ids = {row['id'] for row in cursor.fetchall()}

    return proxy_records, valid_source_ids, all_file_ids


def reconcile_proxies(
    dry_run: bool = True,
    delete_orphans: bool = False
) -> Dict[str, int]:
    """
    Reconcile proxy files with database records.

    Actions:
    1. Find proxy files on disk without DB records -> add records
    2. Find proxy DB records without disk files -> delete records
    3. Find orphaned proxies (source file deleted) -> optionally delete
    4. Update file sizes for existing records

    Args:
        dry_run: If True, only report what would be done
        delete_orphans: If True, delete orphaned proxy files (source deleted)

    Returns:
        Dict with reconciliation statistics
    """
    # Get database path from config
    db_path = os.getenv('DATABASE_PATH', 'data/app.db')
    db = Database(db_path)
    proxy_dir = Path('proxy_video')

    if not proxy_dir.exists():
        logger.error(f"Proxy directory not found: {proxy_dir}")
        return {}

    logger.info("Scanning proxy_video folder...")
    disk_proxies = scan_proxy_folder(proxy_dir)

    logger.info("Loading database state...")
    db_proxies, valid_source_ids, all_file_ids = get_database_state(db)

    stats = {
        'disk_files': len(disk_proxies),
        'db_records': len(db_proxies),
        'added_records': 0,
        'deleted_records': 0,
        'deleted_orphan_files': 0,
        'updated_sizes': 0,
        'orphaned_files': 0,
        'invalid_source_ids': 0
    }

    # Calculate sizes
    disk_size_gb = sum(p['size'] for p in disk_proxies.values()) / (1024**3)
    db_size_gb = sum(p['size_bytes'] for p in db_proxies.values() if p['size_bytes']) / (1024**3)

    logger.info(f"\n{'='*60}")
    logger.info(f"Current State:")
    logger.info(f"  Proxy files on disk: {len(disk_proxies)} ({disk_size_gb:.2f} GB)")
    logger.info(f"  Proxy records in DB: {len(db_proxies)} ({db_size_gb:.2f} GB)")
    logger.info(f"  Valid source files: {len(valid_source_ids)}")
    logger.info(f"{'='*60}\n")

    # Action 1: Find disk files without DB records
    logger.info("Checking for proxy files missing from database...")
    missing_in_db = set(disk_proxies.keys()) - set(db_proxies.keys())

    for source_file_id in tqdm(missing_in_db, desc="Missing in DB"):
        proxy_info = disk_proxies[source_file_id]

        # Check if source file exists
        if source_file_id not in valid_source_ids:
            stats['orphaned_files'] += 1
            if delete_orphans:
                logger.info(f"DELETE ORPHAN: {proxy_info['name']} (source {source_file_id} deleted)")
                if not dry_run:
                    try:
                        proxy_info['path'].unlink()
                        stats['deleted_orphan_files'] += 1
                    except Exception as e:
                        logger.error(f"Failed to delete {proxy_info['name']}: {e}")
            else:
                logger.warning(f"ORPHAN: {proxy_info['name']} (source {source_file_id} not in DB)")
        else:
            # Add proxy record
            logger.info(f"ADD RECORD: {proxy_info['name']} -> source {source_file_id}")
            if not dry_run:
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO files (
                                filename, size_bytes, file_type, content_type, s3_key,
                                is_proxy, source_file_id, local_path
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            proxy_info['name'],
                            proxy_info['size'],
                            'video',
                            f"video/{proxy_info['extension']}",
                            None,  # Proxies don't have S3 keys
                            1,  # is_proxy
                            source_file_id,
                            str(proxy_info['path'])
                        ))
                        conn.commit()
                        stats['added_records'] += 1
                except Exception as e:
                    logger.error(f"Failed to add record for {proxy_info['name']}: {e}")

    # Action 2: Find DB records without disk files
    logger.info("\nChecking for database records without disk files...")
    missing_on_disk = set(db_proxies.keys()) - set(disk_proxies.keys())

    for source_file_id in tqdm(missing_on_disk, desc="Missing on disk"):
        proxy_record = db_proxies[source_file_id]
        logger.info(f"DELETE RECORD: {proxy_record['filename']} (file not on disk)")

        if not dry_run:
            try:
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('DELETE FROM files WHERE id = ?', (proxy_record['id'],))
                    conn.commit()
                    stats['deleted_records'] += 1
            except Exception as e:
                logger.error(f"Failed to delete record {proxy_record['id']}: {e}")

    # Action 3: Update file sizes for existing records
    logger.info("\nChecking file sizes...")
    common_ids = set(disk_proxies.keys()) & set(db_proxies.keys())

    for source_file_id in tqdm(common_ids, desc="Checking sizes"):
        disk_size = disk_proxies[source_file_id]['size']
        db_size = db_proxies[source_file_id]['size_bytes']

        if disk_size != db_size:
            proxy_name = disk_proxies[source_file_id]['name']
            logger.info(f"UPDATE SIZE: {proxy_name} ({db_size} -> {disk_size} bytes)")

            if not dry_run:
                try:
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            'UPDATE files SET size_bytes = ? WHERE id = ?',
                            (disk_size, db_proxies[source_file_id]['id'])
                        )
                        conn.commit()
                        stats['updated_sizes'] += 1
                except Exception as e:
                    logger.error(f"Failed to update size for {proxy_name}: {e}")

    # Action 4: Report invalid source_file_ids on disk
    invalid_source_ids = set()
    for source_file_id in disk_proxies.keys():
        if source_file_id not in all_file_ids:
            invalid_source_ids.add(source_file_id)
            stats['invalid_source_ids'] += 1

    if invalid_source_ids:
        logger.warning(f"\nFound {len(invalid_source_ids)} proxy files with invalid source_file_ids (never existed):")
        for sid in sorted(invalid_source_ids):
            logger.warning(f"  Source ID {sid}: {disk_proxies[sid]['name']}")

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info("Reconciliation Summary:")
    logger.info(f"{'='*60}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info(f"")
    logger.info(f"Files on disk: {stats['disk_files']} ({disk_size_gb:.2f} GB)")
    logger.info(f"Records in DB: {stats['db_records']} ({db_size_gb:.2f} GB)")
    logger.info(f"")
    logger.info(f"Actions taken:")
    logger.info(f"  Added records: {stats['added_records']}")
    logger.info(f"  Deleted records: {stats['deleted_records']}")
    logger.info(f"  Updated sizes: {stats['updated_sizes']}")
    logger.info(f"  Deleted orphan files: {stats['deleted_orphan_files']}")
    logger.info(f"")
    logger.info(f"Issues found:")
    logger.info(f"  Orphaned files (source deleted): {stats['orphaned_files']}")
    logger.info(f"  Invalid source IDs: {stats['invalid_source_ids']}")
    logger.info(f"{'='*60}")

    if dry_run:
        logger.info("\nThis was a DRY RUN. Use --no-dry-run to apply changes.")
    if stats['orphaned_files'] > 0 and not delete_orphans:
        logger.info(f"\nUse --delete-orphans to delete {stats['orphaned_files']} orphaned proxy files.")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Reconcile proxy video files with database records'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='Only show what would be done (default: True)'
    )
    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Actually perform the reconciliation'
    )
    parser.add_argument(
        '--delete-orphans',
        action='store_true',
        help='Delete orphaned proxy files whose source files no longer exist'
    )
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt'
    )

    args = parser.parse_args()

    # Handle dry_run flag
    dry_run = not args.no_dry_run

    if not dry_run and not args.yes:
        logger.warning("⚠️  LIVE MODE - Changes will be applied to database and files!")
        response = input("Continue? [y/N]: ")
        if response.lower() != 'y':
            logger.info("Aborted.")
            return

    if args.delete_orphans and dry_run:
        logger.warning("⚠️  --delete-orphans ignored in dry-run mode")

    reconcile_proxies(dry_run=dry_run, delete_orphans=args.delete_orphans)


if __name__ == '__main__':
    main()
