"""Check duration summary from transcripts table."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import Database

db = Database('data/app.db')

with db.get_connection() as conn:
    cursor = conn.cursor()

    # Check total duration from transcripts with metadata
    cursor.execute('''
        SELECT
            COUNT(*) as count,
            SUM(duration_seconds) as total_duration,
            COUNT(CASE WHEN duration_seconds IS NOT NULL THEN 1 END) as with_duration,
            COUNT(CASE WHEN resolution_width IS NOT NULL THEN 1 END) as with_metadata
        FROM transcripts
        WHERE status = 'COMPLETED'
    ''')

    row = cursor.fetchone()
    print(f"Transcripts Analysis:")
    print(f"  Total completed: {row['count']:,}")
    print(f"  With duration: {row['with_duration']:,}")
    print(f"  With metadata: {row['with_metadata']:,}")
    print(f"  Total duration: {row['total_duration']:,.2f} seconds ({row['total_duration']/3600:.2f} hours)")
    print()

    # Check sample
    cursor.execute('''
        SELECT file_name, duration_seconds, resolution_width
        FROM transcripts
        WHERE status = 'COMPLETED'
        ORDER BY created_at DESC
        LIMIT 10
    ''')

    print("Sample of 10 recent files:")
    for row in cursor.fetchall():
        meta_status = "WITH META" if row['resolution_width'] else "NO META"
        print(f"  [{meta_status}] {row['file_name']}: {row['duration_seconds']}s")
