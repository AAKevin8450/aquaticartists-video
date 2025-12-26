"""
Backfill transcript summaries for existing transcripts.

Usage:
    python -m scripts.backfill_transcript_summaries
    python -m scripts.backfill_transcript_summaries --force  # Overwrite existing
    python -m scripts.backfill_transcript_summaries --limit 10  # Process only 10
    python -m scripts.backfill_transcript_summaries --dry-run  # Preview only
"""
import argparse
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app import create_app
from app.database import get_db
from app.services.nova_transcript_summary_service import NovaTranscriptSummaryService, NovaTranscriptSummaryError


def main():
    parser = argparse.ArgumentParser(description='Backfill transcript summaries for existing transcripts')
    parser.add_argument('--force', action='store_true', help='Overwrite existing summaries')
    parser.add_argument('--limit', type=int, help='Limit number of transcripts to process')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        db = get_db()
        service = NovaTranscriptSummaryService(
            region=app.config['AWS_REGION'],
            aws_access_key=app.config.get('AWS_ACCESS_KEY_ID'),
            aws_secret_key=app.config.get('AWS_SECRET_ACCESS_KEY')
        )

        # Get all completed transcripts
        transcripts = db.list_transcripts(status='COMPLETED')

        # Filter transcripts
        eligible_transcripts = []
        for t in transcripts:
            if not args.force and t.get('transcript_summary'):
                continue  # Skip if already has summary and not forcing
            if not t.get('transcript_text') or not t.get('transcript_text').strip():
                print(f"⚠️  Skipping transcript {t['id']} - empty transcript text")
                continue
            eligible_transcripts.append(t)

        total = len(eligible_transcripts)
        if args.limit:
            eligible_transcripts = eligible_transcripts[:args.limit]

        print(f"\n{'='*80}")
        print(f"TRANSCRIPT SUMMARY BACKFILL")
        print(f"{'='*80}")
        print(f"Total transcripts: {len(transcripts)}")
        print(f"Eligible for processing: {total}")
        print(f"Will process: {len(eligible_transcripts)}")
        print(f"Force overwrite: {args.force}")
        print(f"Dry run: {args.dry_run}")
        print(f"{'='*80}\n")

        if not eligible_transcripts:
            print("✓ No transcripts need summary generation.")
            return

        if args.dry_run:
            print("DRY RUN - Showing what would be processed:\n")
            for i, t in enumerate(eligible_transcripts, 1):
                file_info = db.get_file(t['file_id']) if t.get('file_id') else {}
                filename = file_info.get('filename', 'Unknown')
                text_len = len(t.get('transcript_text', ''))
                has_summary = bool(t.get('transcript_summary'))
                print(f"  {i:3d}. Transcript #{t['id']:<5} | File: {filename:<40} | "
                      f"Text: {text_len:>6} chars | Has summary: {has_summary}")
            print(f"\nWould process {len(eligible_transcripts)} transcript(s).")
            return

        # Process transcripts
        success_count = 0
        failed_count = 0
        total_tokens = 0
        start_time = time.time()

        for i, t in enumerate(eligible_transcripts, 1):
            transcript_id = t['id']
            file_id = t.get('file_id')
            file_info = db.get_file(file_id) if file_id else {}
            filename = file_info.get('filename', 'Unknown')

            print(f"[{i}/{len(eligible_transcripts)}] Processing transcript #{transcript_id} ({filename})...")

            try:
                summary_result = service.summarize_transcript(
                    transcript_text=t['transcript_text'],
                    max_chars=1000
                )

                summary_text = summary_result['summary']
                tokens = summary_result.get('tokens_total', 0)
                truncated = summary_result.get('was_truncated', False)

                db.update_transcript_summary(transcript_id, summary_text)

                total_tokens += tokens
                success_count += 1

                truncated_flag = " [TRUNCATED]" if truncated else ""
                print(f"  ✓ Generated {len(summary_text)} char summary ({tokens} tokens){truncated_flag}")

            except NovaTranscriptSummaryError as e:
                failed_count += 1
                print(f"  ✗ Failed: {e}")
            except Exception as e:
                failed_count += 1
                print(f"  ✗ Unexpected error: {e}")

            # Small delay to avoid rate limiting
            if i < len(eligible_transcripts):
                time.sleep(0.5)

        elapsed = time.time() - start_time

        # Summary
        print(f"\n{'='*80}")
        print(f"SUMMARY")
        print(f"{'='*80}")
        print(f"Processed: {success_count + failed_count}")
        print(f"Success: {success_count}")
        print(f"Failed: {failed_count}")
        print(f"Total tokens: {total_tokens:,}")
        print(f"Elapsed time: {elapsed:.1f}s")
        if success_count > 0:
            print(f"Average time per transcript: {elapsed/success_count:.1f}s")
        print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
