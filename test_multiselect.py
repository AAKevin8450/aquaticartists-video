#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick test script to verify multi-select implementation.
"""
import sys
import io
from app import create_app

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_app_creation():
    """Test that the app can be created successfully."""
    print("Testing app creation...")
    app = create_app()
    print("[PASS] App created successfully")
    return app

def test_blueprints(app):
    """Test that all blueprints are registered."""
    print("\nTesting blueprints...")

    # Check if analysis blueprint is registered
    blueprints = [bp.name for bp in app.blueprints.values()]
    required = ['main', 'upload', 'video_analysis', 'image_analysis', 'collections', 'history', 'analysis']

    for bp_name in required:
        if bp_name in blueprints:
            print(f"[PASS] Blueprint '{bp_name}' registered")
        else:
            print(f"[FAIL] Blueprint '{bp_name}' NOT registered")
            return False

    return True

def test_routes(app):
    """Test that the new routes exist."""
    print("\nTesting routes...")

    with app.test_client() as client:
        # Test video analysis route
        response = client.get('/video-analysis')
        if response.status_code == 200:
            print("[PASS] GET /video-analysis works")

            # Check if checkboxes are in the HTML
            html = response.data.decode('utf-8')
            if 'type="checkbox"' in html and 'analysis-type-checkbox' in html:
                print("[PASS] Video analysis page has checkboxes")
            else:
                print("[FAIL] Video analysis page missing checkboxes")

            if 'selectAllBtn' in html and 'deselectAllBtn' in html:
                print("[PASS] Video analysis page has Select All/Deselect All buttons")
            else:
                print("[FAIL] Video analysis page missing control buttons")
        else:
            print(f"[FAIL] GET /video-analysis failed with status {response.status_code}")

        # Test image analysis route
        response = client.get('/image-analysis')
        if response.status_code == 200:
            print("[PASS] GET /image-analysis works")

            # Check if checkboxes are in the HTML
            html = response.data.decode('utf-8')
            if 'type="checkbox"' in html and 'analysis-type-checkbox' in html:
                print("[PASS] Image analysis page has checkboxes")
            else:
                print("[FAIL] Image analysis page missing checkboxes")

            if 'selectAllBtn' in html and 'deselectAllBtn' in html:
                print("[PASS] Image analysis page has Select All/Deselect All buttons")
            else:
                print("[FAIL] Image analysis page missing control buttons")
        else:
            print(f"[FAIL] GET /image-analysis failed with status {response.status_code}")

def test_api_endpoints(app):
    """Test that API endpoints exist (will fail without proper payload, but should not 404)."""
    print("\nTesting API endpoints...")

    with app.test_client() as client:
        # Test video analysis API
        response = client.post('/api/analysis/video/start',
                              json={},
                              content_type='application/json')
        if response.status_code != 404:
            print(f"[PASS] POST /api/analysis/video/start exists (status: {response.status_code})")
        else:
            print("[FAIL] POST /api/analysis/video/start returns 404")

        # Test image analysis API
        response = client.post('/api/analysis/image/analyze',
                              json={},
                              content_type='application/json')
        if response.status_code != 404:
            print(f"[PASS] POST /api/analysis/image/analyze exists (status: {response.status_code})")
        else:
            print("[FAIL] POST /api/analysis/image/analyze returns 404")

if __name__ == '__main__':
    print("=" * 60)
    print("Multi-Select Analysis Implementation Tests")
    print("=" * 60)

    try:
        app = test_app_creation()
        test_blueprints(app)
        test_routes(app)
        test_api_endpoints(app)

        print("\n" + "=" * 60)
        print("All tests completed!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start the Flask app: python run.py")
        print("2. Navigate to http://localhost:5700/video-analysis")
        print("3. Follow the testing checklist in MULTI_SELECT_TESTING.md")

    except Exception as e:
        print(f"\n[FAIL] Error during testing: {e}")
        import traceback
        traceback.print_exc()
