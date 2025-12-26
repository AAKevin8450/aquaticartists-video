"""
Migration script to add raw_response column to nova_jobs table

This column stores the full JSON response from Nova API for debugging,
auditing, and reprocessing purposes.

Run this once to apply the migration to your existing database:
    python -m scripts.add_nova_raw_response_column
"""

import sqlite3
import os
import sys
from pathlib import Path

# Add parent directory to path so we can import app config
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

DATABASE_PATH = os.getenv('DATABASE_PATH', 'data/app.db')


def add_column():
    """Add raw_response column to nova_jobs table"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    try:
        print(f"Adding raw_response column to nova_jobs table in {DATABASE_PATH}...")

        # Check if column already exists
        cursor.execute("PRAGMA table_info(nova_jobs)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'raw_response' in columns:
            print("[OK] Column raw_response already exists")
        else:
            # Add the column
            cursor.execute("ALTER TABLE nova_jobs ADD COLUMN raw_response TEXT")
            conn.commit()
            print("[OK] Column raw_response added successfully")

        # Show updated schema
        cursor.execute("PRAGMA table_info(nova_jobs)")
        columns = cursor.fetchall()
        print(f"\nNova jobs table now has {len(columns)} columns:")
        for col in columns:
            col_id, name, col_type, notnull, default, pk = col
            print(f"  - {name} ({col_type})")

    except Exception as e:
        print(f"[ERROR] {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

    return True


if __name__ == '__main__':
    print("Nova Jobs Raw Response Column Migration")
    print("=" * 50)
    success = add_column()
    print("=" * 50)
    if success:
        print("\n[SUCCESS] Migration completed successfully")
        print("  Nova API responses will now be stored in raw_response column")
    else:
        print("\n[FAILED] Migration failed")
        sys.exit(1)
