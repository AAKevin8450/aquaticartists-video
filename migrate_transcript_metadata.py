"""
One-time migration script to populate video metadata for all existing transcripts.

This script extracts video metadata (duration, resolution, codecs, etc.) for all
transcripts that are missing this information and updates the database.
"""
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import Database
from app.utils.media_metadata import extract_media_metadata, MediaMetadataError


def migrate_transcript_metadata(db_path: str = 'data/app.db', dry_run: bool = False):
    """
    Migrate all existing transcripts to add video metadata.

    Args:
        db_path: Path to SQLite database
        dry_run: If True, don't actually update the database
    """
    print("=" * 80)
    print("TRANSCRIPT METADATA MIGRATION")
    print("=" * 80)
    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will update database)'}")
    print()

    db = Database(db_path)

    # Get all completed transcripts
    print("Fetching all completed transcripts...")
    transcripts = db.list_transcripts(status='COMPLETED', limit=100000)
    print(f"Found {len(transcripts)} completed transcripts")
    print()

    # Filter to those missing metadata
    missing_metadata = []
    for transcript in transcripts:
        if transcript.get('resolution_width') is None:
            missing_metadata.append(transcript)

    print(f"Transcripts missing metadata: {len(missing_metadata)}")
    if not missing_metadata:
        print("No migration needed!")
        return

    print()
    print("Starting metadata extraction...")
    print()

    # Process each transcript
    success_count = 0
    fail_count = 0
    file_not_found_count = 0

    for i, transcript in enumerate(missing_metadata, 1):
        file_path = transcript['file_path']
        file_name = transcript['file_name']
        transcript_id = transcript['id']

        # Progress indicator
        if i % 10 == 0 or i == len(missing_metadata):
            pct = (i / len(missing_metadata)) * 100
            print(f"Progress: {i}/{len(missing_metadata)} ({pct:.1f}%) | Success: {success_count} | Failed: {fail_count} | Not Found: {file_not_found_count}")

        # Check if file exists
        if not os.path.exists(file_path):
            file_not_found_count += 1
            continue

        # Extract metadata
        try:
            metadata = extract_media_metadata(file_path)

            if dry_run:
                success_count += 1
                if i <= 5:  # Show first 5 examples
                    print(f"\n  [{i}] {file_name}")
                    print(f"      Resolution: {metadata.get('resolution_width')}x{metadata.get('resolution_height')}")
                    print(f"      Duration: {metadata.get('duration_seconds')}s")
                    print(f"      Codecs: {metadata.get('codec_video')}/{metadata.get('codec_audio')}")
            else:
                # Update database
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE transcripts
                        SET resolution_width = ?,
                            resolution_height = ?,
                            frame_rate = ?,
                            codec_video = ?,
                            codec_audio = ?,
                            bitrate = ?
                        WHERE id = ?
                    ''', (
                        metadata.get('resolution_width'),
                        metadata.get('resolution_height'),
                        metadata.get('frame_rate'),
                        metadata.get('codec_video'),
                        metadata.get('codec_audio'),
                        metadata.get('bitrate'),
                        transcript_id
                    ))

                success_count += 1

        except MediaMetadataError as e:
            fail_count += 1
            if fail_count <= 5:  # Show first 5 errors
                print(f"\n  [ERROR] {file_name}: {e}")
        except Exception as e:
            fail_count += 1
            if fail_count <= 5:
                print(f"\n  [ERROR] {file_name}: {e}")

    print()
    print("=" * 80)
    print("MIGRATION COMPLETE")
    print("=" * 80)
    print(f"Total processed: {len(missing_metadata)}")
    print(f"Successfully updated: {success_count}")
    print(f"Failed (metadata extraction): {fail_count}")
    print(f"Failed (file not found): {file_not_found_count}")
    print()

    if dry_run:
        print("NOTE: This was a DRY RUN - no changes were made to the database")
        print("Run again with --live to actually update the database")
    else:
        print("Database has been updated with video metadata!")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Migrate transcript metadata')
    parser.add_argument('--db', default='data/app.db', help='Path to database file')
    parser.add_argument('--live', action='store_true', help='Actually update the database (default is dry run)')

    args = parser.parse_args()

    migrate_transcript_metadata(
        db_path=args.db,
        dry_run=not args.live
    )
