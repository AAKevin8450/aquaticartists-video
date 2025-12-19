"""Test the file summary functionality."""
from app import create_app

# Create app context
app = create_app()

with app.test_client() as client:
    print("=" * 80)
    print("TESTING FILE SUMMARY FUNCTIONALITY")
    print("=" * 80)

    # Test 1: Get all files summary
    print("\n### Test 1: All files summary ###")
    response = client.get('/api/files?per_page=5')
    if response.status_code == 200:
        data = response.get_json()
        summary = data.get('summary', {})
        print(f"[OK] Summary retrieved successfully")
        print(f"  Total Count: {summary.get('total_count', 0):,}")
        print(f"  Total Size: {summary.get('total_size_display', 'N/A')}")
        print(f"  Total Duration: {summary.get('total_duration_display', 'N/A')}")
    else:
        print(f"[ERROR] Failed with status {response.status_code}")

    # Test 2: Filter by has_transcription=true
    print("\n### Test 2: Files with transcription summary ###")
    response = client.get('/api/files?has_transcription=true&per_page=5')
    if response.status_code == 200:
        data = response.get_json()
        summary = data.get('summary', {})
        print(f"[OK] Summary for transcribed files")
        print(f"  Total Count: {summary.get('total_count', 0):,}")
        print(f"  Total Size: {summary.get('total_size_display', 'N/A')}")
        print(f"  Total Duration: {summary.get('total_duration_display', 'N/A')}")
    else:
        print(f"[ERROR] Failed with status {response.status_code}")

    # Test 3: Filter by video type
    print("\n### Test 3: Video files only summary ###")
    response = client.get('/api/files?file_type=video&per_page=5')
    if response.status_code == 200:
        data = response.get_json()
        summary = data.get('summary', {})
        print(f"[OK] Summary for video files")
        print(f"  Total Count: {summary.get('total_count', 0):,}")
        print(f"  Total Size: {summary.get('total_size_display', 'N/A')}")
        print(f"  Total Duration: {summary.get('total_duration_display', 'N/A')}")
    else:
        print(f"[ERROR] Failed with status {response.status_code}")

    # Test 4: Search filter
    print("\n### Test 4: Search filter summary (search='C0293') ###")
    response = client.get('/api/files?search=C0293&per_page=5')
    if response.status_code == 200:
        data = response.get_json()
        summary = data.get('summary', {})
        print(f"[OK] Summary for search results")
        print(f"  Total Count: {summary.get('total_count', 0):,}")
        print(f"  Total Size: {summary.get('total_size_display', 'N/A')}")
        print(f"  Total Duration: {summary.get('total_duration_display', 'N/A')}")
    else:
        print(f"[ERROR] Failed with status {response.status_code}")

    print("\n" + "=" * 80)
    print("TESTS COMPLETE")
    print("=" * 80)
