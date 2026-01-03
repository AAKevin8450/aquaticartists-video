"""
Backfill script to create thumbnails for existing video proxy files.

This script extracts middle frames from video proxies and updates the database
metadata to include thumbnail paths.

Usage:
    python -m scripts.backfill_video_thumbnails [--no-dry-run] [--force] [--limit N]
"""
import sys
import os
import json
import subprocess
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import get_db


def extract_thumbnail(proxy_path: str, thumbnail_path: str, duration_seconds: float = None) -> bool:
    """
    Extract middle frame from proxy video as JPEG thumbnail.

    Args:
        proxy_path: Path to proxy video file
        thumbnail_path: Where to save thumbnail JPEG
        duration_seconds: Video duration in seconds (uses midpoint if provided, else 0.5s)

    Returns:
        True if successful, False otherwise
    """
    timestamp = duration_seconds / 2 if duration_seconds else 0.5

    command = [
        'ffmpeg',
        '-y',
        '-i', proxy_path,
        '-ss', str(timestamp),
        '-vframes', '1',
        '-vf', 'scale=320:-1',
        '-f', 'image2',
        thumbnail_path
    ]

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.returncode == 0


def backfill_thumbnails(dry_run=True, limit=None, force=False):
    """
    Backfill thumbnails for existing video proxies.

    Args:
        dry_run: If True, only show what would be updated without making changes
        limit: Maximum number of proxies to process (None = all)
        force: If True, regenerate thumbnails even if they exist
    """
    db = get_db()

    # Query for video proxies
    with db.get_connection() as conn:
        cursor = conn.cursor()

        query = """
            SELECT id, filename, local_path, metadata, duration_seconds
            FROM files
            WHERE is_proxy = 1 AND file_type = 'video' AND local_path IS NOT NULL
            ORDER BY id
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query)
        proxies = cursor.fetchall()

    total_proxies = len(proxies)
    print(f"\n{'=' * 80}")
    print(f"Found {total_proxies} video proxies to process")
    print(f"Mode: {'DRY RUN (no changes will be made)' if dry_run else 'LIVE (changes will be saved)'}")
    print(f"Force regenerate: {'Yes' if force else 'No'}")
    print(f"{'=' * 80}\n")

    if total_proxies == 0:
        print("No video proxies to process. Exiting.")
        return

    if not dry_run:
        confirm = input(f"\nAre you sure you want to process {total_proxies} proxies? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Aborted.")
            return

    processed = 0
    skipped = 0
    errors = 0
    created = 0

    for proxy in proxies:
        proxy_id = proxy['id']
        proxy_filename = proxy['filename']
        local_path = proxy['local_path']
        duration_seconds = proxy['duration_seconds']

        # Parse metadata
        try:
            metadata = json.loads(proxy['metadata']) if proxy['metadata'] else {}
        except json.JSONDecodeError:
            metadata = {}

        # Check if thumbnail already exists
        existing_thumbnail = metadata.get('thumbnail_path')
        if existing_thumbnail and not force:
            if os.path.isfile(existing_thumbnail):
                print(f"[{proxy_id}] SKIP: Thumbnail already exists - {existing_thumbnail}")
                skipped += 1
                continue

        # Verify proxy file exists
        if not os.path.isfile(local_path):
            print(f"[{proxy_id}] ERROR: Proxy file not found - {local_path}")
            errors += 1
            continue

        # Build thumbnail filename and path
        # Pattern: {name}_{file_id}_thumbnail.jpg
        # Extract source_file_id from filename (pattern: name_id_720p15.ext)
        try:
            # Parse filename to get name and source_file_id
            stem = Path(proxy_filename).stem
            parts = stem.split('_')
            if len(parts) >= 2:
                # Last part before spec is file_id
                source_file_id = parts[-2]
                name = '_'.join(parts[:-2])  # Everything before file_id and spec
            else:
                # Fallback: use proxy_id
                source_file_id = str(proxy_id)
                name = stem

            thumbnail_filename = f"{name}_{source_file_id}_thumbnail.jpg"
        except Exception as e:
            print(f"[{proxy_id}] ERROR: Failed to parse filename - {e}")
            errors += 1
            continue

        thumbnail_dir = Path('proxy_video')
        thumbnail_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = str(thumbnail_dir / thumbnail_filename)

        print(f"[{proxy_id}] Processing: {proxy_filename}")
        print(f"           Proxy: {local_path}")
        print(f"           Thumbnail: {thumbnail_path}")
        print(f"           Duration: {duration_seconds}s" if duration_seconds else "           Duration: Unknown (using 0.5s)")

        if dry_run:
            print(f"           [DRY RUN] Would create thumbnail")
            processed += 1
            continue

        # Extract thumbnail
        try:
            success = extract_thumbnail(local_path, thumbnail_path, duration_seconds)
            if success:
                print(f"           [OK] Thumbnail created")

                # Update metadata
                metadata['thumbnail_path'] = thumbnail_path

                # Update database
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE files SET metadata = ? WHERE id = ?",
                        (json.dumps(metadata), proxy_id)
                    )
                    conn.commit()

                print(f"           [OK] Database updated")
                created += 1
                processed += 1
            else:
                print(f"           [FAIL] Failed to create thumbnail")
                errors += 1
        except Exception as e:
            print(f"           [ERROR] {e}")
            errors += 1

        print()

    print(f"\n{'=' * 80}")
    print(f"SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total proxies: {total_proxies}")
    print(f"Processed: {processed}")
    print(f"Created: {created}")
    print(f"Skipped: {skipped}")
    print(f"Errors: {errors}")
    print(f"{'=' * 80}\n")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Backfill thumbnails for existing video proxy files'
    )
    parser.add_argument(
        '--no-dry-run',
        action='store_true',
        help='Actually create thumbnails (default is dry-run mode)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Regenerate thumbnails even if they already exist'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of proxies to process'
    )

    args = parser.parse_args()

    backfill_thumbnails(
        dry_run=not args.no_dry_run,
        limit=args.limit,
        force=args.force
    )
