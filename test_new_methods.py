"""Test the new database methods."""
from app.database import Database

db = Database('data/app.db')

print("=" * 80)
print("TESTING NEW DATABASE METHODS")
print("=" * 80)

# Test list_all_files_with_stats
print("\n### Testing list_all_files_with_stats (limit 10) ###")
try:
    files = db.list_all_files_with_stats(limit=10, offset=0)
    print(f"Successfully retrieved {len(files)} files")

    for i, file in enumerate(files[:5], 1):
        print(f"\n{i}. {file['filename']}")
        print(f"   Source: {file.get('source_table', 'unknown')}")
        print(f"   Type: {file['file_type']}")
        print(f"   Size: {file['size_bytes']:,} bytes")
        print(f"   Has S3: {'Yes' if file.get('s3_key') else 'No'}")
        print(f"   Local path: {file.get('local_path', 'N/A')[:60]}...")
        print(f"   Transcripts: {file.get('total_transcripts', 0)}")
        print(f"   Analyses: {file.get('total_analyses', 0)}")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

# Test count_all_files
print("\n### Testing count_all_files ###")
try:
    total = db.count_all_files()
    print(f"Total files: {total}")

    # Count with transcription filter
    with_transcripts = db.count_all_files(has_transcription=True)
    print(f"Files with transcripts: {with_transcripts}")

    # Count videos only
    videos = db.count_all_files(file_type='video')
    print(f"Total videos: {videos}")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
