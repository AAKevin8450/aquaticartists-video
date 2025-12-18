"""
Verify transcripts table has all required columns.
"""
import sqlite3

# Expected schema from database.py
EXPECTED_COLUMNS = {
    'id': 'INTEGER',
    'file_path': 'TEXT',
    'file_size_bytes': 'INTEGER',
    'file_modified_time': 'FLOAT',
    'duration_seconds': 'FLOAT',
    'language': 'TEXT',
    'model_used': 'TEXT',
    'transcript_text': 'TEXT',
    'transcript_segments': 'JSON',
    'word_timestamps': 'JSON',
    'confidence_score': 'FLOAT',
    'processing_time_seconds': 'FLOAT',
    'status': 'TEXT',
    'error_message': 'TEXT',
    'created_at': 'TIMESTAMP',
    'completed_at': 'TIMESTAMP',
    'metadata': 'JSON'
}

conn = sqlite3.connect('data/app.db')
cursor = conn.cursor()

# Get actual schema
cursor.execute("PRAGMA table_info(transcripts)")
actual_columns = {}
for row in cursor.fetchall():
    col_id, col_name, col_type, not_null, default_val, pk = row
    actual_columns[col_name] = col_type

print("Schema Verification for 'transcripts' table:")
print("=" * 70)

missing_columns = []
type_mismatches = []

for col_name, expected_type in EXPECTED_COLUMNS.items():
    if col_name not in actual_columns:
        missing_columns.append(col_name)
        print(f"[MISSING] {col_name} ({expected_type})")
    else:
        actual_type = actual_columns[col_name]
        # SQLite is flexible with types, just check if column exists
        print(f"[OK] {col_name}: {actual_type}")

# Check for extra columns not in expected schema
extra_columns = set(actual_columns.keys()) - set(EXPECTED_COLUMNS.keys())
if extra_columns:
    print("\nExtra columns (not in expected schema):")
    for col_name in extra_columns:
        print(f"  [INFO] {col_name}: {actual_columns[col_name]}")

print("\n" + "=" * 70)
if missing_columns:
    print(f"[ERROR] Missing {len(missing_columns)} required column(s):")
    for col in missing_columns:
        print(f"  - {col}")
    print("\nACTION REQUIRED: Run migration to add missing columns")
else:
    print("[SUCCESS] All required columns present!")
    print(f"Total columns: {len(actual_columns)}")

conn.close()
