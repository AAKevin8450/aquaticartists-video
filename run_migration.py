"""
Run database migrations for Nova integration.
"""
import sqlite3
import os
from pathlib import Path

def run_migration(db_path: str, migration_file: str):
    """Run a SQL migration file."""
    # Read migration file
    migration_path = Path(migration_file)
    if not migration_path.exists():
        print(f"Error: Migration file not found: {migration_file}")
        return False

    with open(migration_path, 'r', encoding='utf-8') as f:
        sql = f.read()

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Execute migration as a script (handles multi-line statements properly)
        cursor.executescript(sql)
        conn.commit()
        print(f"[OK] Migration completed successfully: {migration_file}")
        return True

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Migration failed: {e}")
        return False

    finally:
        conn.close()


if __name__ == '__main__':
    # Database path from environment or default
    db_path = os.getenv('DATABASE_PATH', 'data/app.db')
    migration_file = 'migrations/001_add_nova_jobs.sql'

    print(f"Running migration: {migration_file}")
    print(f"Target database: {db_path}")

    success = run_migration(db_path, migration_file)

    if success:
        # Verify table was created
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nova_jobs'")
        result = cursor.fetchone()
        conn.close()

        if result:
            print("[OK] Verified: nova_jobs table exists")
        else:
            print("[WARN] nova_jobs table not found after migration")
    else:
        print("Migration failed - see error above")
