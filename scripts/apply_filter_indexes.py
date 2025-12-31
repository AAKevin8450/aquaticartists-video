#!/usr/bin/env python
"""Apply performance indexes for file filtering to existing database.

Run this script once to add indexes that improve file filtering performance.
These indexes will also be created automatically on next app restart.

Usage:
    python -m scripts.apply_filter_indexes [--analyze]

Options:
    --analyze   Run ANALYZE after creating indexes to update query planner stats
"""
import sqlite3
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Database
from dotenv import load_dotenv

load_dotenv()


def apply_indexes(analyze: bool = False):
    """Apply performance indexes to existing database."""
    db_path = os.getenv('DATABASE_PATH', 'data/app.db')
    db = Database(db_path)

    with db.get_connection() as conn:
        cursor = conn.cursor()

        # Check current index count
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index'")
        before_count = cursor.fetchone()[0]
        print(f"Current index count: {before_count}")

        # Indexes to add for filter performance
        indexes = [
            # For has_proxy filter
            ('idx_files_source_proxy', 'files', 'source_file_id, is_proxy'),
            # For has_transcription filter
            ('idx_transcripts_file_path_status', 'transcripts', 'file_path, status'),
            # For is_proxy filtering in main query
            ('idx_files_is_proxy', 'files', 'is_proxy'),
            # For uploaded_at date range filters
            ('idx_files_uploaded_at_date', 'files', 'date(uploaded_at)'),
        ]

        created = 0
        for idx_name, table, columns in indexes:
            try:
                cursor.execute(f'''
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {table}({columns})
                ''')
                # Check if it was actually created
                cursor.execute(f"SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx_name,))
                if cursor.fetchone():
                    print(f"  + Created/verified: {idx_name} ON {table}({columns})")
                    created += 1
            except sqlite3.OperationalError as e:
                print(f"  - Failed {idx_name}: {e}")

        # Try to add nova_embedding_metadata index if table exists
        try:
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_nova_embed_file_id
                ON nova_embedding_metadata(file_id)
            ''')
            print("  + Created/verified: idx_nova_embed_file_id ON nova_embedding_metadata(file_id)")
            created += 1
        except sqlite3.OperationalError:
            print("  - Skipped idx_nova_embed_file_id (table may not exist)")

        conn.commit()

        # Check new index count
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index'")
        after_count = cursor.fetchone()[0]
        print(f"\nIndex count: {before_count} -> {after_count} (+{after_count - before_count})")

        if analyze:
            print("\nRunning ANALYZE to update query planner statistics...")
            cursor.execute("ANALYZE")
            conn.commit()
            print("ANALYZE complete.")

        # Check character_count column population
        print("\n--- Character Count Check ---")
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(character_count) as has_char_count,
                COUNT(*) - COUNT(character_count) as missing_char_count
            FROM transcripts
            WHERE status = 'COMPLETED'
        """)
        row = cursor.fetchone()
        print(f"Completed transcripts: {row[0]}")
        print(f"  With character_count: {row[1]}")
        print(f"  Missing character_count: {row[2]}")

        if row[2] > 0:
            print(f"\nWARNING: {row[2]} transcripts are missing character_count.")
            print("Consider running: UPDATE transcripts SET character_count = LENGTH(transcript_text) WHERE character_count IS NULL")

        # Show file count for context
        cursor.execute("SELECT COUNT(*) FROM files WHERE is_proxy = 0 OR is_proxy IS NULL")
        file_count = cursor.fetchone()[0]
        print(f"\nTotal source files: {file_count}")


if __name__ == '__main__':
    analyze = '--analyze' in sys.argv
    apply_indexes(analyze=analyze)
