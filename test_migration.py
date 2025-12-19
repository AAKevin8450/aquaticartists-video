"""Test the metadata migration on a few transcripts."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import Database
from app.utils.media_metadata import extract_media_metadata, MediaMetadataError

db = Database('data/app.db')

# Get first 3 completed transcripts missing metadata
transcripts = db.list_transcripts(status='COMPLETED', limit=10)
missing_metadata = [t for t in transcripts if t.get('resolution_width') is None][:3]

print(f"Testing on {len(missing_metadata)} transcripts:")
print()

for transcript in missing_metadata:
    file_path = transcript['file_path']
    file_name = transcript['file_name']

    print(f"File: {file_name}")
    print(f"  Path: {file_path[:60]}...")

    if not os.path.exists(file_path):
        print(f"  Status: FILE NOT FOUND")
        print()
        continue

    try:
        metadata = extract_media_metadata(file_path)
        print(f"  Resolution: {metadata.get('resolution_width')}x{metadata.get('resolution_height')}")
        print(f"  Duration: {metadata.get('duration_seconds')}s")
        print(f"  Frame Rate: {metadata.get('frame_rate')} fps")
        print(f"  Video Codec: {metadata.get('codec_video')}")
        print(f"  Audio Codec: {metadata.get('codec_audio')}")
        print(f"  Bitrate: {metadata.get('bitrate')} bps")
        print(f"  Status: SUCCESS")
    except MediaMetadataError as e:
        print(f"  Status: FAILED - {e}")
    except Exception as e:
        print(f"  Status: ERROR - {e}")

    print()

print("Test complete!")
