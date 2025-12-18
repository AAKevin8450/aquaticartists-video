"""
Database migration script to add missing file_modified_time column.
"""
import sqlite3
import os

db_path = 'data/app.db'

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check if column exists
cursor.execute("PRAGMA table_info(transcripts)")
columns = [row[1] for row in cursor.fetchall()]

if 'file_modified_time' in columns:
    print("Column 'file_modified_time' already exists. No migration needed.")
else:
    print("Adding 'file_modified_time' column to transcripts table...")
    try:
        # Add the missing column with a default value of 0.0
        cursor.execute('''
            ALTER TABLE transcripts
            ADD COLUMN file_modified_time FLOAT NOT NULL DEFAULT 0.0
        ''')
        conn.commit()
        print("[OK] Successfully added 'file_modified_time' column")

        # Update existing records with actual file modified times
        cursor.execute("SELECT id, file_path FROM transcripts")
        records = cursor.fetchall()

        print(f"Updating {len(records)} existing records with actual file modification times...")
        for record_id, file_path in records:
            if os.path.exists(file_path):
                mtime = os.path.getmtime(file_path)
                cursor.execute(
                    "UPDATE transcripts SET file_modified_time = ? WHERE id = ?",
                    (mtime, record_id)
                )
                print(f"  [OK] Updated record {record_id}: {os.path.basename(file_path)}")
            else:
                print(f"  [WARN] File not found for record {record_id}: {file_path}")

        conn.commit()
        print("[OK] Migration completed successfully!")

    except Exception as e:
        print(f"[ERROR] Migration failed: {e}")
        conn.rollback()

conn.close()
