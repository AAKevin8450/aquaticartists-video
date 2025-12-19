"""
Run database migration 004: Enhanced file tracking with media metadata.
"""
import sqlite3
from pathlib import Path

def run_migration():
    """Run migration 004."""
    db_path = Path('data/app.db')
    migration_path = Path('migrations/004_enhance_file_tracking.sql')

    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return False

    if not migration_path.exists():
        print(f"Error: Migration file not found at {migration_path}")
        return False

    print(f"Running migration: {migration_path}")
    print(f"Database: {db_path}")

    # Read migration SQL
    with open(migration_path, 'r', encoding='utf-8') as f:
        migration_sql = f.read()

    # Connect to database
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        # Execute migration (split by semicolon for individual statements)
        statements = migration_sql.split(';')
        for i, statement in enumerate(statements):
            statement = statement.strip()
            if statement and not statement.startswith('--'):
                try:
                    cursor.execute(statement)
                    print(f"[OK] Executed statement {i+1}/{len(statements)}")
                except sqlite3.OperationalError as e:
                    # Skip errors for columns that already exist
                    if 'duplicate column name' in str(e).lower():
                        print(f"[SKIP] Already exists: {str(e)}")
                    else:
                        print(f"[ERROR] {e}")
                        print(f"Statement: {statement[:100]}...")
                        raise

        conn.commit()
        print("\n[SUCCESS] Migration completed successfully!")

        # Verify new columns exist
        cursor.execute("PRAGMA table_info(files)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"\nFiles table columns ({len(columns)}):")
        for col in columns:
            print(f"  - {col}")

        return True

    except Exception as e:
        print(f"\n[FAILED] Migration failed: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()

if __name__ == '__main__':
    success = run_migration()
    exit(0 if success else 1)
