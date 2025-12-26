"""
View transcript summaries for files.

Usage:
    python -m scripts.view_transcript_summaries
    python -m scripts.view_transcript_summaries --with-summary  # Only show files with summaries
    python -m scripts.view_transcript_summaries --without-summary  # Only show files without summaries
    python -m scripts.view_transcript_summaries --limit 5
"""
import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app import create_app
from app.database import get_db


def truncate_text(text, max_length=80):
    """Truncate text to max_length, adding ... if truncated."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."


def main():
    parser = argparse.ArgumentParser(description='View transcript summaries')
    parser.add_argument('--with-summary', action='store_true', help='Show only files with summaries')
    parser.add_argument('--without-summary', action='store_true', help='Show only files without summaries')
    parser.add_argument('--limit', type=int, help='Limit number of results')
    parser.add_argument('--full', action='store_true', help='Show full summaries (not truncated)')
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        db = get_db()

        # Get all completed transcripts
        transcripts = db.list_transcripts(status='COMPLETED')

        # Filter based on arguments
        filtered = []
        for t in transcripts:
            has_summary = bool(t.get('transcript_summary'))
            if args.with_summary and not has_summary:
                continue
            if args.without_summary and has_summary:
                continue
            filtered.append(t)

        if args.limit:
            filtered = filtered[:args.limit]

        # Count stats
        total_transcripts = len(transcripts)
        with_summary = sum(1 for t in transcripts if t.get('transcript_summary'))
        without_summary = total_transcripts - with_summary

        print(f"\n{'='*100}")
        print(f"TRANSCRIPT SUMMARIES")
        print(f"{'='*100}")
        print(f"Total completed transcripts: {total_transcripts}")
        print(f"With summaries: {with_summary}")
        print(f"Without summaries: {without_summary}")
        print(f"Showing: {len(filtered)}")
        print(f"{'='*100}\n")

        if not filtered:
            print("No transcripts to display.\n")
            return

        # Display results
        for i, t in enumerate(filtered, 1):
            file_id = t.get('file_id')
            file_info = db.get_file(file_id) if file_id else {}
            filename = file_info.get('filename', 'Unknown')

            transcript_length = len(t.get('transcript_text', ''))
            summary = t.get('transcript_summary', '')
            summary_length = len(summary) if summary else 0

            print(f"{i:3d}. File: {filename}")
            print(f"     Transcript ID: {t['id']} | Length: {transcript_length:,} chars | Model: {t.get('model', 'unknown')}")

            if summary:
                print(f"     Summary: ({summary_length} chars)")
                if args.full:
                    # Show full summary with proper wrapping
                    import textwrap
                    wrapped = textwrap.fill(summary, width=94, initial_indent='       ', subsequent_indent='       ')
                    print(wrapped)
                else:
                    print(f"       {truncate_text(summary, 90)}")
            else:
                print(f"     Summary: [NONE]")

            print()

        print(f"{'='*100}\n")


if __name__ == '__main__':
    main()
