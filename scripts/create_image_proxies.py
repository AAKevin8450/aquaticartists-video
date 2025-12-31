#!/usr/bin/env python3
"""
Create optimized image proxies for Nova 2 Lite analysis.

This script generates 896px (shorter side) proxies for existing images
in the database that don't have proxies yet.

Run with: python -m scripts.create_image_proxies [--dry-run] [--force] [--limit N]
"""
import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tqdm import tqdm
from app.database import Database
from app.services.image_proxy_service import (
    ImageProxyService,
    ImageProxyError,
    build_image_proxy_filename
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Proxy directory
PROXY_IMAGE_DIR = Path('proxy_image')


def get_images_needing_proxy(db: Database, force: bool = False, limit: Optional[int] = None) -> List[Dict]:
    """
    Get list of images that need proxies created.

    Args:
        db: Database instance
        force: If True, include images that already have proxies
        limit: Maximum number of images to return

    Returns:
        List of image file records
    """
    with db.get_connection() as conn:
        cursor = conn.cursor()

        if force:
            # Get all images (will recreate proxies)
            query = '''
                SELECT f.id, f.filename, f.local_path, f.size_bytes,
                       f.resolution_width, f.resolution_height, f.content_type
                FROM files f
                WHERE f.file_type = 'image'
                  AND (f.is_proxy = 0 OR f.is_proxy IS NULL)
                  AND f.local_path IS NOT NULL
                ORDER BY f.id
            '''
        else:
            # Get images without proxies
            query = '''
                SELECT f.id, f.filename, f.local_path, f.size_bytes,
                       f.resolution_width, f.resolution_height, f.content_type
                FROM files f
                WHERE f.file_type = 'image'
                  AND (f.is_proxy = 0 OR f.is_proxy IS NULL)
                  AND f.local_path IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM files p
                      WHERE p.source_file_id = f.id AND p.is_proxy = 1
                  )
                ORDER BY f.id
            '''

        if limit:
            query += f' LIMIT {limit}'

        cursor.execute(query)
        return [dict(row) for row in cursor.fetchall()]


def create_image_proxies(
    dry_run: bool = True,
    force: bool = False,
    limit: Optional[int] = None
) -> Dict[str, int]:
    """
    Create image proxies for existing images in the database.

    Args:
        dry_run: If True, only report what would be done
        force: If True, recreate proxies even if they exist
        limit: Maximum number of images to process

    Returns:
        Dict with processing statistics
    """
    db_path = os.getenv('DATABASE_PATH', 'data/app.db')
    db = Database(db_path)

    # Ensure proxy directory exists
    PROXY_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # Get images needing proxies
    logger.info("Scanning database for images...")
    images = get_images_needing_proxy(db, force=force, limit=limit)

    stats = {
        'total_images': len(images),
        'proxies_created': 0,
        'proxies_skipped': 0,
        'errors': 0,
        'total_original_size': 0,
        'total_proxy_size': 0,
        'needs_resize': 0,
        'no_resize_needed': 0
    }

    if not images:
        logger.info("No images found that need proxies.")
        return stats

    logger.info(f"\n{'='*60}")
    logger.info(f"Found {len(images)} images to process")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info(f"Force: {force}")
    logger.info(f"{'='*60}\n")

    # Initialize proxy service
    proxy_service = ImageProxyService()

    for image in tqdm(images, desc="Creating image proxies"):
        file_id = image['id']
        filename = image['filename']
        local_path = image['local_path']

        # Check if local file exists
        if not local_path or not os.path.isfile(local_path):
            logger.warning(f"Skipping {filename} (ID: {file_id}): file not found at {local_path}")
            stats['errors'] += 1
            continue

        try:
            # Get original file size
            original_size = os.path.getsize(local_path)
            stats['total_original_size'] += original_size

            # Get dimensions
            width = image.get('resolution_width')
            height = image.get('resolution_height')

            if not width or not height:
                # Try to get dimensions from file
                try:
                    width, height = proxy_service.get_image_dimensions(local_path)
                except ImageProxyError:
                    logger.warning(f"Skipping {filename} (ID: {file_id}): could not read dimensions")
                    stats['errors'] += 1
                    continue

            # Check if resize is needed
            needs_resize = proxy_service.needs_proxy(width, height)

            if needs_resize:
                stats['needs_resize'] += 1
            else:
                stats['no_resize_needed'] += 1
                logger.info(f"Skipping {filename}: no resize needed ({width}x{height}, threshold: 896px)")
                stats['proxies_skipped'] += 1
                continue

            # Generate proxy filename and path
            proxy_filename = build_image_proxy_filename(filename, file_id)
            proxy_local_path = str(PROXY_IMAGE_DIR / proxy_filename)

            # Calculate target dimensions for logging
            target_width, target_height = proxy_service.calculate_target_dimensions(width, height)

            if dry_run:
                logger.info(
                    f"WOULD CREATE: {filename} ({width}x{height}) -> "
                    f"{proxy_filename} ({target_width}x{target_height})"
                )
                stats['proxies_created'] += 1
                continue

            # Delete existing proxy if force mode and proxy exists
            if force:
                existing_proxy = db.get_proxy_for_source(file_id)
                if existing_proxy:
                    old_path = existing_proxy.get('local_path')
                    if old_path and os.path.isfile(old_path):
                        try:
                            os.remove(old_path)
                        except Exception as e:
                            logger.warning(f"Failed to delete old proxy: {e}")
                    db.delete_file(existing_proxy['id'])

            # Create the proxy
            result = proxy_service.create_proxy(
                source_path=local_path,
                output_path=proxy_local_path
            )

            proxy_size = result['proxy_size_bytes']
            proxy_dimensions = result['proxy_dimensions']
            stats['total_proxy_size'] += proxy_size

            # Determine content type
            output_format = result.get('format', 'JPEG')
            content_type = 'image/jpeg' if output_format == 'JPEG' else 'image/png'

            # Create database record
            from datetime import datetime
            import json

            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO files (
                        filename, s3_key, file_type, size_bytes, content_type,
                        is_proxy, source_file_id, local_path,
                        resolution_width, resolution_height, frame_rate,
                        codec_video, codec_audio, duration_seconds, bitrate,
                        metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    proxy_filename,
                    None,  # s3_key
                    'image',
                    proxy_size,
                    content_type,
                    1,  # is_proxy
                    file_id,  # source_file_id
                    proxy_local_path,
                    proxy_dimensions[0],  # resolution_width
                    proxy_dimensions[1],  # resolution_height
                    None,  # frame_rate
                    None,  # codec_video
                    None,  # codec_audio
                    None,  # duration_seconds
                    None,  # bitrate
                    json.dumps({
                        'proxy_type': 'nova_image',
                        'target_dimension': 896,
                        'was_resized': result['was_resized'],
                        'format': result['format'],
                        'proxy_generated_at': datetime.utcnow().isoformat() + 'Z'
                    })
                ))
                conn.commit()

            stats['proxies_created'] += 1
            logger.info(
                f"Created: {filename} ({width}x{height}, {original_size/1024:.1f}KB) -> "
                f"{proxy_filename} ({proxy_dimensions[0]}x{proxy_dimensions[1]}, {proxy_size/1024:.1f}KB) "
                f"[{result['savings_percent']:.1f}% reduction]"
            )

        except ImageProxyError as e:
            logger.error(f"Error processing {filename} (ID: {file_id}): {e}")
            stats['errors'] += 1
        except Exception as e:
            logger.error(f"Unexpected error processing {filename} (ID: {file_id}): {e}")
            stats['errors'] += 1

    # Print summary
    total_savings = stats['total_original_size'] - stats['total_proxy_size']
    savings_pct = (total_savings / stats['total_original_size'] * 100) if stats['total_original_size'] > 0 else 0

    logger.info(f"\n{'='*60}")
    logger.info("Image Proxy Creation Summary:")
    logger.info(f"{'='*60}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    logger.info(f"")
    logger.info(f"Images found: {stats['total_images']}")
    logger.info(f"  - Needs resize (>896px): {stats['needs_resize']}")
    logger.info(f"  - No resize needed: {stats['no_resize_needed']}")
    logger.info(f"")
    logger.info(f"Results:")
    logger.info(f"  - Proxies created: {stats['proxies_created']}")
    logger.info(f"  - Skipped (no resize): {stats['proxies_skipped']}")
    logger.info(f"  - Errors: {stats['errors']}")
    logger.info(f"")

    if not dry_run and stats['proxies_created'] > 0:
        logger.info(f"Storage:")
        logger.info(f"  - Original size: {stats['total_original_size']/1024/1024:.2f} MB")
        logger.info(f"  - Proxy size: {stats['total_proxy_size']/1024/1024:.2f} MB")
        logger.info(f"  - Savings: {total_savings/1024/1024:.2f} MB ({savings_pct:.1f}%)")

    logger.info(f"{'='*60}")

    if dry_run:
        logger.info("\nThis was a DRY RUN. Use --no-dry-run to create proxies.")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Create optimized image proxies for Nova 2 Lite analysis'
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
        help='Actually create the proxies'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Recreate proxies even if they already exist'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Maximum number of images to process'
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
        logger.warning("LIVE MODE - Proxies will be created!")
        if args.force:
            logger.warning("FORCE MODE - Existing proxies will be recreated!")
        response = input("Continue? [y/N]: ")
        if response.lower() != 'y':
            logger.info("Aborted.")
            return

    create_image_proxies(dry_run=dry_run, force=args.force, limit=args.limit)


if __name__ == '__main__':
    main()
