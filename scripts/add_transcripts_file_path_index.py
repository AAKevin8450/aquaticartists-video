"""
Migration script to add missing index on transcripts.file_path

This index dramatically improves filter performance by avoiding full table scans
when joining transcripts with files table.

Run this once to apply the index to your existing database:
    python -m scripts.add_transcripts_file_path_index
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


def add_index():
    """Add the missing index on transcripts.file_path"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    try:
        print(f"Adding index on transcripts.file_path in {DATABASE_PATH}...")

        # Check if index already exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_transcripts_file_path'
        """)

        if cursor.fetchone():
            print("[OK] Index idx_transcripts_file_path already exists")
        else:
            # Create the index
            cursor.execute("""
                CREATE INDEX idx_transcripts_file_path
                ON transcripts(file_path)
            """)
            conn.commit()
            print("[OK] Index idx_transcripts_file_path created successfully")

        # Show index info
        cursor.execute("""
            SELECT COUNT(*) FROM transcripts
        """)
        count = cursor.fetchone()[0]
        print(f"  Indexed {count:,} transcript records")

        # List all indexes on transcripts table
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name='transcripts'
            ORDER BY name
        """)
        indexes = [row[0] for row in cursor.fetchall()]
        print(f"\nAll indexes on transcripts table:")
        for idx in indexes:
            print(f"  - {idx}")

    except Exception as e:
        print(f"[ERROR] {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

    return True


if __name__ == '__main__':
    print("Transcripts File Path Index Migration")
    print("=" * 50)
    success = add_index()
    print("=" * 50)
    if success:
        print("\n[SUCCESS] Migration completed successfully")
        print("  Filter performance should be significantly improved!")
    else:
        print("\n[FAILED] Migration failed")
        sys.exit(1)
