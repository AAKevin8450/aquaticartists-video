"""Test the duration query directly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import Database

db = Database('data/app.db')

# Test the get_all_files_summary method
summary = db.get_all_files_summary()
print(f"Summary from method:")
print(f"  Count: {summary['total_count']}")
print(f"  Size: {summary['total_size_bytes']:,} bytes")
print(f"  Duration: {summary['total_duration_seconds']} seconds ({summary['total_duration_seconds']/3600:.2f} hours)")
print()

# Test direct query
with db.get_connection() as conn:
    cursor = conn.cursor()

    # Check files table durations
    cursor.execute('SELECT COUNT(*), SUM(duration_seconds) FROM files WHERE (is_proxy = 0 OR is_proxy IS NULL)')
    row = cursor.fetchone()
    print(f"Files table:")
    print(f"  Count: {row[0]}")
    print(f"  Total duration: {row[1]} seconds")
    print()

    # Check transcripts table durations
    cursor.execute('SELECT COUNT(*), SUM(duration_seconds) FROM transcripts WHERE status = "COMPLETED"')
    row = cursor.fetchone()
    print(f"Transcripts table:")
    print(f"  Count: {row[0]}")
    print(f"  Total duration: {row[1]} seconds ({row[1]/3600:.2f} hours)")
    print()

    # Check the UNION query
    cursor.execute('''
        WITH all_files AS (
            SELECT
                f.id,
                f.duration_seconds,
                'files' as source
            FROM files f
            WHERE (f.is_proxy = 0 OR f.is_proxy IS NULL)

            UNION

            SELECT
                -t.id as id,
                MAX(t.duration_seconds) as duration_seconds,
                'transcripts' as source
            FROM transcripts t
            LEFT JOIN files f ON t.file_path = f.local_path
            WHERE f.id IS NULL AND t.status = 'COMPLETED'
            GROUP BY t.file_path, t.file_name, t.file_size, t.created_at
        )
        SELECT source, COUNT(*), SUM(duration_seconds)
        FROM all_files
        GROUP BY source
    ''')

    print("UNION query breakdown:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]} files, {row[2]} seconds total")
