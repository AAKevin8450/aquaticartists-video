"""
Backfill file_mtime/file_ctime metadata for files with local paths.
"""
import json
import os

from app.database import Database


def _parse_metadata(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def main():
    db = Database('data/app.db')
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, local_path, metadata FROM files WHERE local_path IS NOT NULL')
        rows = cursor.fetchall()

    scanned = 0
    updated = 0
    missing = 0

    for row in rows:
        scanned += 1
        local_path = row['local_path']
        if not local_path or not os.path.exists(local_path):
            missing += 1
            continue

        metadata = _parse_metadata(row['metadata'])
        updates = {}

        try:
            file_stat = os.stat(local_path)
        except OSError:
            missing += 1
            continue

        if not isinstance(metadata.get('file_mtime'), (int, float)):
            updates['file_mtime'] = file_stat.st_mtime
        if not isinstance(metadata.get('file_ctime'), (int, float)):
            updates['file_ctime'] = file_stat.st_ctime

        if updates:
            db.update_file_metadata(row['id'], updates)
            updated += 1

    print(f"Scanned: {scanned}")
    print(f"Updated: {updated}")
    print(f"Missing path/stat: {missing}")


if __name__ == '__main__':
    main()
