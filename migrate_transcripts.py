"""
One-time migration to import all transcript-only files into the files table.

This unifies file management so that ALL files the system knows about
are in the files table with proper positive IDs.
"""
from app import create_app
from app.database import get_db

def main():
    print("=" * 60)
    print("TRANSCRIPT FILES MIGRATION")
    print("=" * 60)
    print("This will import all transcript-only files into the files table.")
    print("Files will NOT be moved, copied, or modified.")
    print("Only database records will be created.")
    print()

    # Initialize Flask app
    app = create_app()
    with app.app_context():
        db = get_db()

        # Run the migration
        print("Starting migration...")
        result = db.import_all_transcripts_as_files()

        # Display results
        print()
        print("=" * 60)
        print("MIGRATION RESULTS")
        print("=" * 60)
        print(f"Total transcript files found: {result['total']}")
        print(f"Successfully imported: {result['imported']}")
        print(f"Skipped (already imported): {result['skipped']}")
        print(f"Errors: {len(result['errors'])}")
        print()

        if result['errors']:
            print("ERRORS:")
            for error in result['errors'][:10]:  # Show first 10 errors
                print(f"  - {error['file_path']}: {error['error']}")
            if len(result['errors']) > 10:
                print(f"  ... and {len(result['errors']) - 10} more errors")
            print()

        if result['imported'] > 0:
            print(f"[SUCCESS] Imported {result['imported']} files into files table")
            print("  These files can now have proxies created and be analyzed")
        else:
            print("[SUCCESS] No new files to import (all transcript files already in files table)")

        print()
        print("Migration complete!")

if __name__ == '__main__':
    main()
