"""Simple API test without external dependencies."""
from app import create_app
from app.database import Database

# Create app context
app = create_app()

with app.test_client() as client:
    print("=" * 80)
    print("TESTING FILE MANAGEMENT API ENDPOINTS")
    print("=" * 80)

    # Test /api/files endpoint
    print("\n### Testing GET /api/files (first page) ###")
    response = client.get('/api/files?per_page=5')
    if response.status_code == 200:
        data = response.get_json()
        print(f"[OK] Success! Retrieved {len(data['files'])} files")
        print(f"  Total files: {data['pagination']['total']}")
        print(f"  Total pages: {data['pagination']['pages']}")

        if data['files']:
            print(f"\n  First file example:")
            file = data['files'][0]
            print(f"    - Filename: {file['filename']}")
            print(f"    - Type: {file['file_type']}")
            print(f"    - Size: {file['size_display']}")
            print(f"    - Local path: {file.get('local_path', 'N/A')[:60]}...")
            print(f"    - Transcripts: {file.get('completed_transcripts', 0)}/{file.get('total_transcripts', 0)}")
    else:
        print(f"[ERROR] Failed with status {response.status_code}")
        print(f"  Error: {response.data}")

    # Test /api/files with transcription filter
    print("\n### Testing GET /api/files?has_transcription=true (first 5) ###")
    response = client.get('/api/files?has_transcription=true&per_page=5')
    if response.status_code == 200:
        data = response.get_json()
        print(f"[OK] Success! Retrieved {len(data['files'])} files with transcripts")
        print(f"  Total files with transcripts: {data['pagination']['total']}")

        if data['files']:
            print(f"\n  Example file with transcript:")
            file = data['files'][0]
            print(f"    - {file['filename']}")
            print(f"    - Transcripts: {file['completed_transcripts']} completed")
    else:
        print(f"[ERROR] Failed with status {response.status_code}")

    # Test /api/s3-files endpoint
    print("\n### Testing GET /api/s3-files ###")
    response = client.get('/api/s3-files')
    if response.status_code == 200:
        data = response.get_json()
        print(f"[OK] Success! Retrieved {data['total']} S3 files")

        if data['s3_files']:
            print(f"\n  First 3 S3 files:")
            for i, file in enumerate(data['s3_files'][:3], 1):
                print(f"    {i}. {file['filename']}")
                print(f"       S3 key: {file['s3_key'][:60]}...")
                print(f"       Size: {file['size_display']}")
                print(f"       In database: {'Yes' if file['in_database'] else 'No'}")
    else:
        print(f"[ERROR] Failed with status {response.status_code}")
        print(f"  Error: {response.data}")

    print("\n" + "=" * 80)
    print("TESTS COMPLETE")
    print("=" * 80)
