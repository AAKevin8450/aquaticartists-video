"""Test script to verify Nova integration setup."""
import sys
from app import create_app

try:
    print("Creating Flask app...")
    app = create_app()
    print("[OK] Flask app created successfully")

    print("\nChecking Nova routes...")
    with app.app_context():
        nova_routes = [str(rule) for rule in app.url_map.iter_rules() if '/api/nova' in str(rule)]

        if nova_routes:
            print(f"[OK] Found {len(nova_routes)} Nova API endpoints:")
            for route in sorted(nova_routes):
                print(f"  - {route}")
        else:
            print("[ERROR] No Nova routes found!")
            sys.exit(1)

    print("\nTesting Nova service import...")
    from app.services.nova_service import NovaVideoService
    print("[OK] NovaVideoService imported successfully")

    print("\nTesting database Nova methods...")
    from app.database import get_db
    db = get_db()

    # Check if nova_jobs table exists
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nova_jobs'")
        result = cursor.fetchone()

        if result:
            print("[OK] nova_jobs table exists in database")
        else:
            print("[ERROR] nova_jobs table not found!")
            sys.exit(1)

    print("\n" + "="*60)
    print("[SUCCESS] ALL CHECKS PASSED - Nova integration is ready!")
    print("="*60)
    print("\nNext step: Test with actual video analysis")
    print("Run: python run.py")
    print("Then test: curl http://localhost:5700/api/nova/models")

except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
