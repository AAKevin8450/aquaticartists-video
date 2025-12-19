"""Check database status for file management debugging."""
import sqlite3

conn = sqlite3.connect('data/app.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("=" * 80)
print("DATABASE STATUS CHECK")
print("=" * 80)

# Check files table
print("\n### FILES TABLE ###")
cursor.execute('SELECT COUNT(*) as count FROM files')
files_count = cursor.fetchone()['count']
print(f'Total files in database: {files_count}')

if files_count > 0:
    cursor.execute('''
        SELECT id, filename, s3_key, file_type, size_bytes, uploaded_at
        FROM files
        ORDER BY uploaded_at DESC
        LIMIT 5
    ''')
    print('\nMost recent 5 files:')
    for row in cursor.fetchall():
        print(f'  [{row["id"]}] {row["filename"]} ({row["file_type"]}) - {row["s3_key"][:50]}...')

# Check transcripts table
print("\n### TRANSCRIPTS TABLE ###")
cursor.execute('SELECT COUNT(*) as count FROM transcripts')
transcripts_count = cursor.fetchone()['count']
print(f'Total transcripts in database: {transcripts_count}')

if transcripts_count > 0:
    cursor.execute('SELECT status, COUNT(*) as count FROM transcripts GROUP BY status')
    print('\nStatus breakdown:')
    for row in cursor.fetchall():
        print(f'  {row["status"]}: {row["count"]}')

    cursor.execute('''
        SELECT id, file_name, file_path, model_name, status, created_at
        FROM transcripts
        ORDER BY created_at DESC
        LIMIT 5
    ''')
    print('\nMost recent 5 transcripts:')
    for row in cursor.fetchall():
        print(f'  [{row["id"]}] {row["file_name"]} - {row["model_name"]} - {row["status"]}')
        print(f'       Path: {row["file_path"][:70]}...')

# Check which transcript files are NOT in the files table
print("\n### TRANSCRIPTS WITHOUT FILES TABLE ENTRY ###")
cursor.execute('''
    SELECT DISTINCT t.file_path, t.file_name, COUNT(*) as transcript_count
    FROM transcripts t
    LEFT JOIN files f ON t.file_path = f.local_path
    WHERE f.id IS NULL
    GROUP BY t.file_path, t.file_name
    LIMIT 10
''')
orphaned = cursor.fetchall()
if orphaned:
    print(f'Found {len(orphaned)} file paths with transcripts but NO entry in files table:')
    for row in orphaned:
        print(f'  {row["file_name"]} ({row["transcript_count"]} transcripts)')
        print(f'    Path: {row["file_path"][:70]}...')
else:
    print('All transcripts have corresponding file entries')

conn.close()

print("\n" + "=" * 80)
