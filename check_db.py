"""Quick database check script for transcripts."""
import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect('data/app.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Check WAL mode
cursor.execute('PRAGMA journal_mode')
print(f'Journal mode: {cursor.fetchone()[0]}')

# Check if there's a WAL file
import os
wal_file = 'data/app.db-wal'
shm_file = 'data/app.db-shm'
print(f'WAL file exists: {os.path.exists(wal_file)} ({os.path.getsize(wal_file) if os.path.exists(wal_file) else 0} bytes)')
print(f'SHM file exists: {os.path.exists(shm_file)} ({os.path.getsize(shm_file) if os.path.exists(shm_file) else 0} bytes)')

# Total count
cursor.execute('SELECT COUNT(*) as count FROM transcripts')
total = cursor.fetchone()['count']
print(f'\nTotal transcript records: {total}')

# Status breakdown
print('\nStatus breakdown:')
cursor.execute('SELECT status, COUNT(*) as count FROM transcripts GROUP BY status')
for row in cursor.fetchall():
    print(f'  {row["status"]}: {row["count"]}')

# Sample of recent records
print('\nMost recent 5 records:')
cursor.execute('''
    SELECT id, file_path, file_size_bytes, status, model_used,
           duration_seconds, language, created_at, completed_at
    FROM transcripts
    ORDER BY created_at DESC
    LIMIT 5
''')

for row in cursor.fetchall():
    print(f'\n  ID: {row["id"]}')
    print(f'  Path: {row["file_path"]}')
    print(f'  Size: {row["file_size_bytes"]:,} bytes')
    print(f'  Status: {row["status"]}')
    print(f'  Model: {row["model_used"]}')
    print(f'  Duration: {row["duration_seconds"]} sec' if row["duration_seconds"] else '  Duration: N/A')
    print(f'  Language: {row["language"]}' if row["language"] else '  Language: N/A')
    print(f'  Created: {row["created_at"]}')
    print(f'  Completed: {row["completed_at"]}' if row["completed_at"] else '  Completed: N/A')

# Check for data integrity - records with transcript text
print('\nData integrity check:')
cursor.execute('''
    SELECT
        COUNT(*) as total_completed,
        SUM(CASE WHEN transcript_text IS NOT NULL AND transcript_text != '' THEN 1 ELSE 0 END) as with_text,
        SUM(CASE WHEN transcript_segments IS NOT NULL THEN 1 ELSE 0 END) as with_segments,
        SUM(CASE WHEN duration_seconds IS NOT NULL THEN 1 ELSE 0 END) as with_duration
    FROM transcripts
    WHERE status = 'COMPLETED'
''')
integrity = cursor.fetchone()
if integrity['total_completed'] > 0:
    print(f'  Completed records: {integrity["total_completed"]}')
    print(f'  With transcript text: {integrity["with_text"]}')
    print(f'  With segments: {integrity["with_segments"]}')
    print(f'  With duration: {integrity["with_duration"]}')
else:
    print('  No completed records yet')

# Check average file size
cursor.execute('SELECT AVG(file_size_bytes) as avg_size FROM transcripts')
avg_size = cursor.fetchone()['avg_size']
if avg_size:
    print(f'\nAverage file size: {avg_size/1024/1024:.2f} MB')

conn.close()
