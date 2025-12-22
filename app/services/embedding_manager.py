"""
Embedding Manager - Orchestrates embedding generation and storage.
Handles chunking, hashing, and idempotent storage of embeddings.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.database import Database
from app.services.nova_embeddings_service import (
    NovaEmbeddingsService,
    NovaEmbeddingsError,
    EmbeddingPurpose
)

logger = logging.getLogger(__name__)


@dataclass
class ChunkInfo:
    """Information about a text chunk."""
    text: str
    start_char: int
    end_char: int
    chunk_index: int
    total_chunks: int


class EmbeddingManager:
    """Manages embedding generation and storage with chunking support."""

    # Chunking configuration
    DEFAULT_CHUNK_SIZE = 4000  # Characters per chunk (well under 8K token limit)
    DEFAULT_CHUNK_OVERLAP = 200  # Overlap between chunks

    # Sentence-ending patterns for smart chunking
    SENTENCE_END_PATTERN = re.compile(r'[.!?]\s+')

    def __init__(
        self,
        db: Database,
        embeddings_service: Optional[NovaEmbeddingsService] = None
    ):
        self.db = db
        self.embeddings_service = embeddings_service or self._create_default_service()

    def _create_default_service(self) -> NovaEmbeddingsService:
        """Create embeddings service from environment variables."""
        return NovaEmbeddingsService(
            region=os.getenv('AWS_REGION', 'us-east-1'),
            dimension=int(os.getenv('NOVA_EMBED_DIMENSION', '1024')),
            aws_access_key=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
            s3_bucket=os.getenv('S3_BUCKET_NAME')
        )

    def _chunk_text(
        self,
        text: str,
        chunk_size: int = None,
        overlap: int = None
    ) -> List[ChunkInfo]:
        """
        Split text into chunks with overlap, respecting sentence boundaries.
        """
        chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        overlap = overlap or self.DEFAULT_CHUNK_OVERLAP

        if len(text) <= chunk_size:
            return [ChunkInfo(
                text=text,
                start_char=0,
                end_char=len(text),
                chunk_index=0,
                total_chunks=1
            )]

        chunks = []
        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(start + chunk_size, len(text))

            # Try to find a sentence boundary near the end
            if end < len(text):
                # Look for sentence end in last 20% of chunk
                search_start = int(end - chunk_size * 0.2)
                chunk_text = text[start:end]

                matches = list(self.SENTENCE_END_PATTERN.finditer(chunk_text[search_start - start:]))
                if matches:
                    # Use the last sentence boundary found
                    last_match = matches[-1]
                    end = start + search_start - start + last_match.end()

            chunks.append(ChunkInfo(
                text=text[start:end].strip(),
                start_char=start,
                end_char=end,
                chunk_index=chunk_index,
                total_chunks=0  # Updated after loop
            ))

            # Move start, accounting for overlap
            start = end - overlap if end < len(text) else len(text)
            chunk_index += 1

        # Update total_chunks
        for chunk in chunks:
            chunk.total_chunks = len(chunks)

        return chunks

    @staticmethod
    def _compute_hash(content: str) -> str:
        """Compute deterministic hash for content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:32]

    def process_transcript(
        self,
        transcript_id: int,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Process a transcript: chunk, embed, and store.

        Args:
            transcript_id: ID of transcript in database
            force: If True, re-embed even if hash exists

        Returns:
            Dict with processing statistics
        """
        # Fetch transcript
        transcript = self.db.get_transcript(transcript_id)
        if not transcript:
            raise ValueError(f"Transcript {transcript_id} not found")

        text = transcript.get('transcript_text', '')
        if not text or not text.strip():
            logger.warning(f"Transcript {transcript_id} has no text")
            return {'status': 'skipped', 'reason': 'empty_text'}

        # Chunk the text
        chunks = self._chunk_text(text)

        stats = {
            'transcript_id': transcript_id,
            'total_chunks': len(chunks),
            'embedded': 0,
            'skipped': 0,
            'failed': 0
        }

        model_name = self.embeddings_service.MODEL_ID

        for chunk in chunks:
            content_hash = self._compute_hash(chunk.text)

            # Check if already embedded (idempotency)
            if not force:
                existing = self.db.get_embedding_by_hash(
                    source_type='transcript',
                    source_id=transcript_id,
                    model_name=model_name,
                    content_hash=content_hash
                )
                if existing:
                    stats['skipped'] += 1
                    continue

            try:
                # Generate embedding
                embedding = self.embeddings_service.embed_text(chunk.text)

                # Store embedding
                self.db.create_nova_embedding(
                    embedding_vector=embedding,
                    source_type='transcript',
                    source_id=transcript_id,
                    model_name=model_name,
                    content_hash=content_hash,
                    file_id=transcript.get('file_id')
                )
                stats['embedded'] += 1

            except NovaEmbeddingsError as e:
                logger.error(f"Failed to embed chunk {chunk.chunk_index}: {e}")
                stats['failed'] += 1

        stats['status'] = 'completed'
        return stats

    def process_nova_job(
        self,
        nova_job_id: int,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Process Nova analysis results: embed summary, chapters, elements.

        Args:
            nova_job_id: ID of nova_jobs record
            force: If True, re-embed even if hash exists

        Returns:
            Dict with processing statistics
        """
        # Fetch Nova job
        job = self.db.get_nova_job(nova_job_id)
        if not job:
            raise ValueError(f"Nova job {nova_job_id} not found")

        if job.get('status') != 'COMPLETED':
            return {'status': 'skipped', 'reason': 'job_not_completed'}

        # Get results from the appropriate fields
        stats = {
            'nova_job_id': nova_job_id,
            'embedded': 0,
            'skipped': 0,
            'failed': 0
        }

        model_name = self.embeddings_service.MODEL_ID

        # Embed summary
        summary_result = job.get('summary_result')
        if summary_result:
            # Extract text from summary result
            if isinstance(summary_result, dict):
                summary_text = summary_result.get('text', str(summary_result))
            elif isinstance(summary_result, str):
                summary_text = summary_result
            else:
                summary_text = str(summary_result)

            if summary_text:
                self._embed_content(
                    content=summary_text,
                    source_type='nova_analysis',
                    source_id=nova_job_id,
                    model_name=model_name,
                    file_id=job.get('file_id'),
                    force=force,
                    stats=stats
                )

        # Embed chapters
        chapters_result = job.get('chapters_result')
        if chapters_result and isinstance(chapters_result, list):
            for i, chapter in enumerate(chapters_result):
                content = f"Chapter: {chapter.get('title', 'Untitled')}\n"
                content += f"Summary: {chapter.get('summary', '')}"

                self._embed_content(
                    content=content,
                    source_type='nova_analysis',
                    source_id=nova_job_id,
                    model_name=model_name,
                    file_id=job.get('file_id'),
                    force=force,
                    stats=stats
                )

        # Embed elements
        elements_result = job.get('elements_result')
        if elements_result and isinstance(elements_result, list):
            for element in elements_result:
                content = f"Type: {element.get('type', 'Unknown')}\n"
                content += f"Name: {element.get('name', '')}\n"
                content += f"Description: {element.get('description', '')}"

                self._embed_content(
                    content=content,
                    source_type='nova_analysis',
                    source_id=nova_job_id,
                    model_name=model_name,
                    file_id=job.get('file_id'),
                    force=force,
                    stats=stats
                )

        stats['status'] = 'completed'
        return stats

    def _embed_content(
        self,
        content: str,
        source_type: str,
        source_id: int,
        model_name: str,
        file_id: Optional[int],
        force: bool,
        stats: Dict[str, int]
    ):
        """Helper to embed a single piece of content."""
        if not content or not content.strip():
            return

        content_hash = self._compute_hash(content)

        if not force:
            existing = self.db.get_embedding_by_hash(
                source_type=source_type,
                source_id=source_id,
                model_name=model_name,
                content_hash=content_hash
            )
            if existing:
                stats['skipped'] += 1
                return

        try:
            embedding = self.embeddings_service.embed_text(content)
            self.db.create_nova_embedding(
                embedding_vector=embedding,
                source_type=source_type,
                source_id=source_id,
                model_name=model_name,
                content_hash=content_hash,
                file_id=file_id
            )
            stats['embedded'] += 1
        except NovaEmbeddingsError as e:
            logger.error(f"Failed to embed content: {e}")
            stats['failed'] += 1
