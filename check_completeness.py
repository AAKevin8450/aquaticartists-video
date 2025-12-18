"""Check which transcript records are incomplete."""
import sqlite3
import os

conn = sqlite3.connect('data/app.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("Checking transcript completeness:")
print("=" * 100)

cursor.execute('''
    SELECT id, file_path, status,
           CASE WHEN transcript_text IS NULL OR transcript_text = '' THEN 'MISSING' ELSE 'OK' END as text_status,
           CASE WHEN transcript_segments IS NULL THEN 'MISSING' ELSE 'OK' END as segments_status,
           CASE WHEN word_timestamps IS NULL THEN 'MISSING' ELSE 'OK' END as timestamps_status,
           duration_seconds, language, confidence_score, processing_time_seconds,
           LENGTH(transcript_text) as text_length
    FROM transcripts
    ORDER BY id
''')

incomplete_count = 0
for row in cursor.fetchall():
    is_complete = (row['text_status'] == 'OK' and
                   row['segments_status'] == 'OK' and
                   row['timestamps_status'] == 'OK')

    status_symbol = '[OK]' if is_complete else '[INCOMPLETE]'

    print(f"\n{status_symbol} ID {row['id']}: {os.path.basename(row['file_path'])}")
    print(f"  Status: {row['status']}")
    print(f"  Transcript Text: {row['text_status']} ({row['text_length']} chars)" if row['text_length'] else f"  Transcript Text: {row['text_status']}")
    print(f"  Segments: {row['segments_status']}")
    print(f"  Timestamps: {row['timestamps_status']}")
    print(f"  Duration: {row['duration_seconds']} sec" if row['duration_seconds'] else "  Duration: N/A")
    print(f"  Language: {row['language']}" if row['language'] else "  Language: N/A")
    print(f"  Confidence: {row['confidence_score']:.2f}" if row['confidence_score'] else "  Confidence: N/A")
    print(f"  Processing Time: {row['processing_time_seconds']:.2f} sec" if row['processing_time_seconds'] else "  Processing Time: N/A")

    if not is_complete:
        incomplete_count += 1

print("\n" + "=" * 100)
print(f"Total records: {cursor.rowcount}")
print(f"Complete records: {cursor.rowcount - incomplete_count}")
print(f"Incomplete records: {incomplete_count}")

if incomplete_count == 0:
    print("\n[SUCCESS] All records are complete!")
else:
    print(f"\n[WARNING] {incomplete_count} record(s) are missing data")

conn.close()
