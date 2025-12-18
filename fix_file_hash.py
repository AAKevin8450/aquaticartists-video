"""
Fix file_hash column constraint issue.
SQLite doesn't support ALTER COLUMN to change NOT NULL, so we need to recreate the table.
"""
import sqlite3
import os

db_path = 'data/app.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("Fixing file_hash column constraint...")

try:
    # Step 1: Create new table without file_hash NOT NULL constraint
    cursor.execute('''
        CREATE TABLE transcripts_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_size_bytes INTEGER NOT NULL,
            file_modified_time FLOAT NOT NULL,
            duration_seconds FLOAT,
            language TEXT,
            model_used TEXT NOT NULL,
            transcript_text TEXT,
            transcript_segments JSON,
            word_timestamps JSON,
            confidence_score FLOAT,
            processing_time_seconds FLOAT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            metadata JSON,
            file_hash TEXT
        )
    ''')
    print("[OK] Created new table schema")

    # Step 2: Copy data from old table
    cursor.execute('''
        INSERT INTO transcripts_new
        SELECT id, file_path, file_size_bytes, file_modified_time, duration_seconds,
               language, model_used, transcript_text, transcript_segments, word_timestamps,
               confidence_score, processing_time_seconds, status, error_message,
               created_at, completed_at, metadata, file_hash
        FROM transcripts
    ''')
    print(f"[OK] Copied {cursor.rowcount} records to new table")

    # Step 3: Drop old table
    cursor.execute('DROP TABLE transcripts')
    print("[OK] Dropped old table")

    # Step 4: Rename new table
    cursor.execute('ALTER TABLE transcripts_new RENAME TO transcripts')
    print("[OK] Renamed new table to transcripts")

    # Step 5: Recreate index
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_transcripts_status
        ON transcripts(status)
    ''')
    print("[OK] Recreated index")

    conn.commit()
    print("\n[SUCCESS] Migration completed successfully!")
    print("file_hash column is now nullable")

except Exception as e:
    print(f"[ERROR] Migration failed: {e}")
    import traceback
    traceback.print_exc()
    conn.rollback()

conn.close()
