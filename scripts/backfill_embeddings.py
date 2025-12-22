#!/usr/bin/env python3
"""
Backfill embeddings for existing transcripts and Nova jobs.
Run with: python -m scripts.backfill_embeddings
"""
import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tqdm import tqdm
from app.database import Database
from app.services.embedding_manager import EmbeddingManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def backfill_transcripts(
    manager: EmbeddingManager,
    db: Database,
    force: bool = False,
    limit: Optional[int] = None
) -> Dict[str, int]:
    """Backfill embeddings for all completed transcripts."""

    # Get all completed transcripts
    with db.get_connection() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT id, file_name FROM transcripts
            WHERE status = 'completed' AND transcript_text IS NOT NULL
            ORDER BY id
        '''
        if limit:
            query += f' LIMIT {limit}'
        cursor.execute(query)
        transcripts = cursor.fetchall()

    stats = {'processed': 0, 'skipped': 0, 'failed': 0, 'total_chunks': 0}

    for t in tqdm(transcripts, desc="Transcripts"):
        try:
            result = manager.process_transcript(t['id'], force=force)
            stats['processed'] += 1
            stats['total_chunks'] += result.get('embedded', 0)
            stats['skipped'] += result.get('skipped', 0)
        except Exception as e:
            logger.error(f"Failed transcript {t['id']}: {e}")
            stats['failed'] += 1

    return stats


def backfill_nova_jobs(
    manager: EmbeddingManager,
    db: Database,
    force: bool = False,
    limit: Optional[int] = None
) -> Dict[str, int]:
    """Backfill embeddings for all completed Nova jobs."""

    with db.get_connection() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT id, analysis_types FROM nova_jobs
            WHERE status = 'COMPLETED' AND (summary_result IS NOT NULL OR chapters_result IS NOT NULL OR elements_result IS NOT NULL)
            ORDER BY id
        '''
        if limit:
            query += f' LIMIT {limit}'
        cursor.execute(query)
        jobs = cursor.fetchall()

    stats = {'processed': 0, 'skipped': 0, 'failed': 0}

    for job in tqdm(jobs, desc="Nova Jobs"):
        try:
            result = manager.process_nova_job(job['id'], force=force)
            stats['processed'] += 1
            stats['skipped'] += result.get('skipped', 0)
        except Exception as e:
            logger.error(f"Failed Nova job {job['id']}: {e}")
            stats['failed'] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description='Backfill Nova embeddings')
    parser.add_argument('--force', action='store_true', help='Re-embed existing content')
    parser.add_argument('--transcripts-only', action='store_true')
    parser.add_argument('--nova-only', action='store_true')
    parser.add_argument('--limit', type=int, help='Limit number of items')
    args = parser.parse_args()

    db = Database()
    manager = EmbeddingManager(db)

    # Check vector extension
    with db.get_connection() as conn:
        if not db._load_vector_extension(conn):
            logger.error("sqlite-vec extension not available!")
            logger.error("Set SQLITE_VEC_PATH environment variable")
            sys.exit(1)

    logger.info("Starting embedding backfill...")
    logger.info(f"Dimension: {manager.embeddings_service.dimension}")
    logger.info(f"Model: {manager.embeddings_service.MODEL_ID}")

    if not args.nova_only:
        logger.info("\n=== Processing Transcripts ===")
        t_stats = backfill_transcripts(manager, db, args.force, args.limit)
        logger.info(f"Transcripts: {t_stats}")

    if not args.transcripts_only:
        logger.info("\n=== Processing Nova Jobs ===")
        n_stats = backfill_nova_jobs(manager, db, args.force, args.limit)
        logger.info(f"Nova Jobs: {n_stats}")

    # Final stats
    final = db.get_embedding_stats()
    logger.info(f"\n=== Final Stats ===")
    logger.info(f"Total embeddings: {final['total_embeddings']}")
    logger.info(f"By source: {final['by_source_and_model']}")


if __name__ == '__main__':
    main()
