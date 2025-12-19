"""Verify metadata migration results."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import Database

db = Database('data/app.db')

# Check transcripts with metadata
print("Checking metadata population...")
print()

transcripts = db.list_transcripts(status='COMPLETED', limit=10)

with_metadata = 0
without_metadata = 0

print("Sample of 10 recent transcripts:")
print()

for t in transcripts:
    has_meta = t.get('resolution_width') is not None
    status = "HAS METADATA" if has_meta else "MISSING METADATA"

    if has_meta:
        with_metadata += 1
        print(f"[{status}] {t['file_name']}")
        print(f"  Resolution: {t.get('resolution_width')}x{t.get('resolution_height')}")
        print(f"  Duration: {t.get('duration_seconds')}s")
        print(f"  Codec: {t.get('codec_video')}/{t.get('codec_audio')}")
    else:
        without_metadata += 1
        print(f"[{status}] {t['file_name']}")

    print()

print(f"Summary: {with_metadata} with metadata, {without_metadata} without")
