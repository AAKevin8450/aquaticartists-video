# Nova Embeddings Implementation Plan
**Date:** December 21, 2025
**Status:** Planned
**Last Updated:** December 21, 2025 (Comprehensive Review)

## 1. Overview

This plan outlines the implementation of semantic search capabilities using **AWS Nova Multimodal Embeddings** and local SQLite vector storage (`sqlite-vec`). The goal is to enable natural language search across video transcripts and Nova analysis results (summaries, chapters, detected elements) with deterministic re-embedding, traceable metadata, and a UI toggle that preserves existing search behavior by default.

### 1.1. Key References
- [AWS Nova Embeddings User Guide](https://docs.aws.amazon.com/nova/latest/userguide/nova-embeddings.html)
- [Nova Embeddings Request/Response Schema](https://docs.aws.amazon.com/nova/latest/userguide/embeddings-schema.html)
- [AWS Blog: Nova Multimodal Embeddings](https://aws.amazon.com/blogs/aws/amazon-nova-multimodal-embeddings-now-available-in-amazon-bedrock/)
- [sqlite-vec Documentation](https://alexgarcia.xyz/sqlite-vec/)
- [sqlite-vec KNN Queries](https://alexgarcia.xyz/sqlite-vec/features/knn.html)

---

## 2. AWS Nova Multimodal Embeddings Specification

### 2.1. Model Details

| Property | Value |
|----------|-------|
| **Model ID** | `amazon.nova-2-multimodal-embeddings-v1:0` |
| **Region** | us-east-1 (currently only available region) |
| **Supported Dimensions** | 256, 384, 1024, 3072 |
| **Max Context (Sync)** | 8K tokens text / 30s video / 30s audio |
| **Max Context (Async)** | 50K chars text / 2 hours video / 2 hours audio |
| **Supported Modalities** | Text, Image, Document, Video, Audio |

### 2.2. Dimension Selection Guide

| Dimension | Use Case | Storage per Vector | Accuracy |
|-----------|----------|-------------------|----------|
| **256** | High volume, cost-sensitive | 1 KB | Good |
| **384** | Balanced for smaller datasets | 1.5 KB | Better |
| **1024** | Recommended default | 4 KB | High |
| **3072** | Maximum accuracy needs | 12 KB | Highest |

**Recommendation:** Use **1024** dimensions for this application (good accuracy vs. storage tradeoff for 3,000+ transcripts).

### 2.3. Request Schema (Synchronous API)

```json
{
    "schemaVersion": "nova-multimodal-embed-v1",
    "taskType": "SINGLE_EMBEDDING",
    "singleEmbeddingParams": {
        "embeddingPurpose": "GENERIC_INDEX",
        "embeddingDimension": 1024,
        "text": {
            "truncationMode": "END",
            "value": "Your text content here"
        }
    }
}
```

### 2.4. Request Schema (Asynchronous API - for long content)

```python
response = bedrock_runtime.start_async_invoke(
    modelId="amazon.nova-2-multimodal-embeddings-v1:0",
    outputDataConfig={
        "s3OutputDataConfig": {
            "s3Uri": "s3://video-analysis-app-676206912644/embeddings/"
        }
    },
    modelInput={
        "schemaVersion": "nova-multimodal-embed-v1",
        "taskType": "SEGMENTED_EMBEDDING",
        "segmentedEmbeddingParams": {
            "embeddingPurpose": "GENERIC_INDEX",
            "embeddingDimension": 1024,
            "text": {
                "truncationMode": "END",
                "value": "Long transcript text...",
                "segmentationConfig": {
                    "maxLengthChars": 32000
                }
            }
        }
    }
)
```

### 2.5. Embedding Purpose Options

| Purpose | Use Case |
|---------|----------|
| `GENERIC_INDEX` | General-purpose indexing (recommended for storage) |
| `GENERIC_RETRIEVAL` | Query-time embedding |
| `TEXT_RETRIEVAL` | Text-specific retrieval optimization |
| `CLASSIFICATION` | Classification tasks |
| `CLUSTERING` | Clustering tasks |

**Strategy:** Use `GENERIC_INDEX` for stored embeddings, `GENERIC_RETRIEVAL` for query embeddings.

### 2.6. Response Schema

```json
{
    "embeddings": [
        {
            "embeddingType": "TEXT",
            "embedding": [0.123, -0.456, ...],
            "truncatedCharLength": null
        }
    ]
}
```

### 2.7. File Size Limits

| API | Text Limit | Video Limit | Audio Limit |
|-----|------------|-------------|-------------|
| **Sync** | 1 MB / 50K chars | 30s / 100 MB | 30s / 100 MB |
| **Async** | 634 MB | 2 hours / 2 GB | 2 hours / 1 GB |

---

## 3. Architecture

### 3.1. Components

```
┌─────────────────────────────────────────────────────────────────┐
│                      User Interface                              │
│  ┌─────────────────┐    ┌─────────────────────────────────────┐ │
│  │ Semantic Toggle │────│ Search Input: "water feature pump"  │ │
│  └─────────────────┘    └─────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Search API Layer                              │
│  /api/search?semantic=true&q=water+feature+pump                 │
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────────────────────────┐ │
│  │ Query Embedding │────│ Vector Search (KNN)                 │ │
│  │ (Nova API)      │    │ (sqlite-vec MATCH)                  │ │
│  └─────────────────┘    └─────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Storage Layer                                 │
│  ┌────────────────────────┐    ┌─────────────────────────────┐  │
│  │ nova_embeddings (vec0) │◄───│ nova_embedding_metadata     │  │
│  │ embedding float[1024]  │    │ source_type, source_id, ... │  │
│  └────────────────────────┘    └─────────────────────────────┘  │
│                                          │                       │
│                    ┌─────────────────────┼─────────────────────┐ │
│                    ▼                     ▼                     ▼ │
│  ┌─────────────────────┐  ┌─────────────────┐  ┌─────────────┐  │
│  │ transcripts         │  │ nova_jobs       │  │ files       │  │
│  │ (transcript_text)   │  │ (summary, etc.) │  │ (file_name) │  │
│  └─────────────────────┘  └─────────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2. Data Flow

#### Ingestion Flow

1. **Transcripts** (most content):
   - If < 8K tokens: Sync API, single embedding
   - If > 8K tokens: Async API with segmentation (32K char chunks)
   - Store chunk embeddings with `segment_index` metadata

2. **Nova Analysis Results**:
   - **Summaries**: Embed full summary text (usually < 8K tokens)
   - **Chapters**: Embed "Title: {title}\nSummary: {summary}" per chapter
   - **Elements**: Embed "Type: {type}\nName: {name}\nDescription: {description}"

3. **Storage**:
   - Generate embedding via Nova API
   - Compute SHA-256 hash of source content
   - Check for existing embedding with same hash (idempotency)
   - Store vector in `nova_embeddings` (vec0)
   - Store metadata in `nova_embedding_metadata`

#### Search Flow

1. User enters query "how to install a water pump"
2. Generate query embedding with `embeddingPurpose: GENERIC_RETRIEVAL`
3. KNN search against `nova_embeddings` using `MATCH` operator
4. Join with metadata to get source IDs
5. Fetch actual content from `transcripts` or `nova_jobs`
6. Return ranked results with snippets

---

## 4. Implementation Steps

### Phase 1: Core Service & Database Updates

#### 1.1. Update NovaEmbeddingsService

**File:** `app/services/nova_embeddings_service.py`

**Current Issue:** Service uses generic `{'input': [...]}` format, not Nova's schema.

**Required Changes:**

```python
"""
AWS Nova Multimodal Embeddings service using Amazon Bedrock.
Supports both synchronous and asynchronous embedding generation.
"""
from __future__ import annotations

import hashlib
import json
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError


class EmbeddingPurpose(Enum):
    GENERIC_INDEX = "GENERIC_INDEX"
    GENERIC_RETRIEVAL = "GENERIC_RETRIEVAL"
    TEXT_RETRIEVAL = "TEXT_RETRIEVAL"
    CLASSIFICATION = "CLASSIFICATION"
    CLUSTERING = "CLUSTERING"


class NovaEmbeddingsError(Exception):
    """Nova embeddings errors."""
    pass


class NovaEmbeddingsService:
    """Service for generating Nova embeddings via Bedrock."""

    # Model configuration
    MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"
    SCHEMA_VERSION = "nova-multimodal-embed-v1"

    # Limits
    MAX_SYNC_TOKENS = 8000  # ~8K tokens
    MAX_SYNC_CHARS = 50000  # 50K characters
    MAX_ASYNC_CHARS = 634_000_000  # 634 MB

    # Supported dimensions
    VALID_DIMENSIONS = [256, 384, 1024, 3072]

    def __init__(
        self,
        region: str = "us-east-1",
        dimension: int = 1024,
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        s3_bucket: Optional[str] = None
    ):
        if dimension not in self.VALID_DIMENSIONS:
            raise ValueError(f"Invalid dimension {dimension}. Must be one of {self.VALID_DIMENSIONS}")

        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('bedrock-runtime', **session_kwargs)
        self.dimension = dimension
        self.s3_bucket = s3_bucket
        self.region = region

    def _build_sync_request(
        self,
        text: str,
        purpose: EmbeddingPurpose = EmbeddingPurpose.GENERIC_INDEX
    ) -> Dict[str, Any]:
        """Build synchronous embedding request payload."""
        return {
            "schemaVersion": self.SCHEMA_VERSION,
            "taskType": "SINGLE_EMBEDDING",
            "singleEmbeddingParams": {
                "embeddingPurpose": purpose.value,
                "embeddingDimension": self.dimension,
                "text": {
                    "truncationMode": "END",
                    "value": text
                }
            }
        }

    def _build_async_request(
        self,
        text: str,
        purpose: EmbeddingPurpose = EmbeddingPurpose.GENERIC_INDEX,
        max_segment_chars: int = 32000
    ) -> Dict[str, Any]:
        """Build asynchronous segmented embedding request payload."""
        return {
            "schemaVersion": self.SCHEMA_VERSION,
            "taskType": "SEGMENTED_EMBEDDING",
            "segmentedEmbeddingParams": {
                "embeddingPurpose": purpose.value,
                "embeddingDimension": self.dimension,
                "text": {
                    "truncationMode": "END",
                    "value": text,
                    "segmentationConfig": {
                        "maxLengthChars": max_segment_chars
                    }
                }
            }
        }

    def _extract_embedding(self, response_body: Dict[str, Any]) -> List[float]:
        """Extract embedding vector from sync response."""
        embeddings = response_body.get('embeddings', [])
        if not embeddings:
            raise NovaEmbeddingsError("No embeddings in response")

        first = embeddings[0]
        if isinstance(first, dict) and 'embedding' in first:
            return first['embedding']
        raise NovaEmbeddingsError(f"Unexpected response format: {type(first)}")

    def embed_text(
        self,
        text: str,
        purpose: EmbeddingPurpose = EmbeddingPurpose.GENERIC_INDEX
    ) -> List[float]:
        """Generate embedding for text (sync API, <8K tokens)."""
        if not text or not text.strip():
            raise NovaEmbeddingsError("Text input is empty")

        text = text.strip()
        if len(text) > self.MAX_SYNC_CHARS:
            raise NovaEmbeddingsError(
                f"Text too long for sync API ({len(text)} chars). "
                f"Max: {self.MAX_SYNC_CHARS}. Use embed_text_async() instead."
            )

        payload = self._build_sync_request(text, purpose)

        try:
            response = self.client.invoke_model(
                modelId=self.MODEL_ID,
                body=json.dumps(payload).encode('utf-8'),
                accept='application/json',
                contentType='application/json'
            )
        except ClientError as e:
            raise NovaEmbeddingsError(f"Nova embeddings request failed: {e}")

        body = response.get('body')
        if hasattr(body, 'read'):
            body = body.read().decode('utf-8')

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise NovaEmbeddingsError(f"Failed to parse response: {e}")

        return self._extract_embedding(data)

    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a search query (optimized for retrieval)."""
        return self.embed_text(query, purpose=EmbeddingPurpose.GENERIC_RETRIEVAL)

    def start_async_embedding(
        self,
        text: str,
        output_prefix: str = "embeddings/",
        max_segment_chars: int = 32000
    ) -> str:
        """Start async embedding job for long text. Returns invocation ARN."""
        if not self.s3_bucket:
            raise NovaEmbeddingsError("S3 bucket required for async embedding")

        payload = self._build_async_request(text, max_segment_chars=max_segment_chars)
        s3_uri = f"s3://{self.s3_bucket}/{output_prefix}"

        try:
            response = self.client.start_async_invoke(
                modelId=self.MODEL_ID,
                modelInput=payload,
                outputDataConfig={
                    "s3OutputDataConfig": {"s3Uri": s3_uri}
                }
            )
            return response['invocationArn']
        except ClientError as e:
            raise NovaEmbeddingsError(f"Async embedding start failed: {e}")

    def get_async_status(self, invocation_arn: str) -> Dict[str, Any]:
        """Get status of async embedding job."""
        try:
            return self.client.get_async_invoke(invocationArn=invocation_arn)
        except ClientError as e:
            raise NovaEmbeddingsError(f"Failed to get async status: {e}")

    def wait_for_async_completion(
        self,
        invocation_arn: str,
        poll_interval: int = 5,
        max_wait: int = 3600
    ) -> Dict[str, Any]:
        """Wait for async job to complete. Returns final status."""
        elapsed = 0
        while elapsed < max_wait:
            status = self.get_async_status(invocation_arn)
            state = status.get('status')

            if state == 'Completed':
                return status
            elif state == 'Failed':
                raise NovaEmbeddingsError(f"Async job failed: {status.get('failureMessage')}")

            time.sleep(poll_interval)
            elapsed += poll_interval

        raise NovaEmbeddingsError(f"Async job timed out after {max_wait}s")

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """Compute SHA-256 hash of content for idempotency."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
```

#### 1.2. Add Vector Search Methods to Database

**File:** `app/database.py`

**Add these methods to the Database class:**

```python
def search_embeddings(
    self,
    query_vector: List[float],
    limit: int = 20,
    source_types: Optional[List[str]] = None,
    min_similarity: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Perform KNN vector search using sqlite-vec.

    Args:
        query_vector: Embedding vector for the query
        limit: Maximum results to return
        source_types: Filter by source type ('transcript', 'nova_analysis')
        min_similarity: Minimum cosine similarity (0.0-1.0)

    Returns:
        List of matches with distance, source_type, source_id, etc.
    """
    self._validate_embedding_dimension(query_vector)

    with self.get_connection() as conn:
        if not self._load_vector_extension(conn):
            raise RuntimeError("SQLite vector extension not available")

        query_blob = self._serialize_embedding(query_vector)
        cursor = conn.cursor()

        # Build query with optional source_type filter
        sql = '''
            SELECT
                e.rowid,
                e.distance,
                m.source_type,
                m.source_id,
                m.file_id,
                m.model_name,
                m.content_hash,
                m.created_at
            FROM nova_embeddings e
            JOIN nova_embedding_metadata m ON e.rowid = m.rowid
            WHERE e.embedding MATCH ?
        '''
        params = [query_blob]

        if source_types:
            placeholders = ','.join('?' * len(source_types))
            sql += f' AND m.source_type IN ({placeholders})'
            params.extend(source_types)

        sql += f' ORDER BY e.distance LIMIT {limit}'

        cursor.execute(sql, params)
        results = [dict(row) for row in cursor.fetchall()]

        # Convert L2 distance to similarity score (optional normalization)
        for r in results:
            # For normalized vectors, similarity ≈ 1 - (distance² / 2)
            r['similarity'] = max(0, 1 - (r['distance'] ** 2) / 2)

        # Filter by minimum similarity if specified
        if min_similarity > 0:
            results = [r for r in results if r['similarity'] >= min_similarity]

        return results

def get_content_for_embedding_results(
    self,
    results: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Fetch actual content for embedding search results.
    Enriches results with text content from source tables.
    """
    if not results:
        return []

    # Group by source type for efficient fetching
    transcript_ids = [r['source_id'] for r in results if r['source_type'] == 'transcript']
    nova_ids = [r['source_id'] for r in results if r['source_type'] == 'nova_analysis']

    enriched = []

    with self.get_connection() as conn:
        cursor = conn.cursor()

        # Fetch transcripts
        if transcript_ids:
            placeholders = ','.join('?' * len(transcript_ids))
            cursor.execute(f'''
                SELECT id, file_name, file_path, transcript_text, language, model_name
                FROM transcripts WHERE id IN ({placeholders})
            ''', transcript_ids)
            transcripts = {row['id']: dict(row) for row in cursor.fetchall()}
        else:
            transcripts = {}

        # Fetch Nova jobs
        if nova_ids:
            placeholders = ','.join('?' * len(nova_ids))
            cursor.execute(f'''
                SELECT id, file_id, model_name, analysis_type, results
                FROM nova_jobs WHERE id IN ({placeholders})
            ''', nova_ids)
            nova_jobs = {row['id']: dict(row) for row in cursor.fetchall()}
        else:
            nova_jobs = {}

    # Enrich results
    for r in results:
        enriched_result = r.copy()

        if r['source_type'] == 'transcript':
            source = transcripts.get(r['source_id'], {})
            enriched_result['title'] = source.get('file_name', 'Unknown')
            enriched_result['preview'] = (source.get('transcript_text', '')[:200] + '...')
            enriched_result['file_path'] = source.get('file_path')
            enriched_result['language'] = source.get('language')

        elif r['source_type'] == 'nova_analysis':
            source = nova_jobs.get(r['source_id'], {})
            enriched_result['title'] = f"Nova {source.get('analysis_type', 'Analysis')}"
            # Parse results JSON for preview
            try:
                results_data = json.loads(source.get('results', '{}'))
                if 'summary' in results_data:
                    enriched_result['preview'] = results_data['summary'][:200] + '...'
                else:
                    enriched_result['preview'] = str(results_data)[:200] + '...'
            except:
                enriched_result['preview'] = 'Analysis results'

        enriched.append(enriched_result)

    return enriched

def delete_embeddings_for_source(
    self,
    source_type: str,
    source_id: int
) -> int:
    """Delete all embeddings for a source. Returns count deleted."""
    with self.get_connection() as conn:
        if not self._load_vector_extension(conn):
            return 0

        cursor = conn.cursor()

        # Get rowids to delete
        cursor.execute('''
            SELECT rowid FROM nova_embedding_metadata
            WHERE source_type = ? AND source_id = ?
        ''', (source_type, source_id))
        rowids = [row['rowid'] for row in cursor.fetchall()]

        if not rowids:
            return 0

        # Delete from both tables
        placeholders = ','.join('?' * len(rowids))
        cursor.execute(f'DELETE FROM nova_embeddings WHERE rowid IN ({placeholders})', rowids)
        cursor.execute(f'DELETE FROM nova_embedding_metadata WHERE rowid IN ({placeholders})', rowids)

        return len(rowids)

def get_embedding_stats(self) -> Dict[str, Any]:
    """Get embedding statistics for monitoring."""
    with self.get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                source_type,
                model_name,
                COUNT(*) as count
            FROM nova_embedding_metadata
            GROUP BY source_type, model_name
        ''')

        by_source = {}
        for row in cursor.fetchall():
            key = f"{row['source_type']}:{row['model_name']}"
            by_source[key] = row['count']

        cursor.execute('SELECT COUNT(*) as total FROM nova_embedding_metadata')
        total = cursor.fetchone()['total']

        return {
            'total_embeddings': total,
            'by_source_and_model': by_source,
            'dimension': self._get_embedding_dimension()
        }
```

---

### Phase 2: Data Ingestion (EmbeddingManager)

#### 2.1. Create EmbeddingManager Service

**File:** `app/services/embedding_manager.py` (New)

```python
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

        results = job.get('results', {})
        if isinstance(results, str):
            import json
            try:
                results = json.loads(results)
            except:
                results = {}

        stats = {
            'nova_job_id': nova_job_id,
            'embedded': 0,
            'skipped': 0,
            'failed': 0
        }

        model_name = self.embeddings_service.MODEL_ID

        # Embed summary
        if 'summary' in results:
            self._embed_content(
                content=results['summary'],
                source_type='nova_analysis',
                source_id=nova_job_id,
                model_name=model_name,
                file_id=job.get('file_id'),
                force=force,
                stats=stats
            )

        # Embed chapters
        for i, chapter in enumerate(results.get('chapters', [])):
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
        for element in results.get('elements', []):
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
```

#### 2.2. Backfill Script

**File:** `scripts/backfill_embeddings.py` (New)

```python
#!/usr/bin/env python3
"""
Backfill embeddings for existing transcripts and Nova jobs.
Run with: python -m scripts.backfill_embeddings
"""
import argparse
import logging
import sys
from pathlib import Path

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
            SELECT id, analysis_type FROM nova_jobs
            WHERE status = 'COMPLETED' AND results IS NOT NULL
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
```

---

### Phase 3: Search API & UI

#### 3.1. Update Search API

**File:** `app/routes/search.py`

**Add to existing `/api/search` endpoint:**

```python
@search_bp.route('/api/search', methods=['POST'])
def api_search():
    """Search across all data sources."""
    data = request.get_json() or {}

    query = data.get('query', '').strip()
    semantic = data.get('semantic', False)

    # ... existing parameter handling ...

    if semantic and query:
        # Semantic search path
        return semantic_search(
            query=query,
            sources=data.get('sources', ['transcripts', 'nova']),
            limit=data.get('per_page', 50),
            page=data.get('page', 1)
        )
    else:
        # Existing keyword search
        return keyword_search(data)


def semantic_search(
    query: str,
    sources: List[str],
    limit: int = 50,
    page: int = 1
) -> Response:
    """Perform semantic vector search."""
    try:
        # Generate query embedding
        from app.services.embedding_manager import EmbeddingManager
        manager = EmbeddingManager(db)

        query_embedding = manager.embeddings_service.embed_query(query)

        # Map source names to source_types
        source_type_map = {
            'transcripts': 'transcript',
            'nova': 'nova_analysis'
        }
        source_types = [source_type_map.get(s) for s in sources if s in source_type_map]
        source_types = [s for s in source_types if s]  # Remove None

        # Vector search
        results = db.search_embeddings(
            query_vector=query_embedding,
            limit=limit * page,  # Fetch enough for pagination
            source_types=source_types if source_types else None
        )

        # Paginate
        start = (page - 1) * limit
        paginated = results[start:start + limit]

        # Enrich with content
        enriched = db.get_content_for_embedding_results(paginated)

        # Format response
        formatted = []
        for r in enriched:
            formatted.append({
                'source': 'transcripts' if r['source_type'] == 'transcript' else 'nova',
                'id': r['source_id'],
                'title': r.get('title', 'Unknown'),
                'preview': r.get('preview', ''),
                'similarity': round(r.get('similarity', 0), 3),
                'created_at': r.get('created_at')
            })

        return jsonify({
            'results': formatted,
            'total': len(results),
            'page': page,
            'per_page': limit,
            'semantic': True
        })

    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return jsonify({'error': str(e)}), 500
```

#### 3.2. Frontend Toggle

**File:** `app/templates/search.html`

Add toggle switch in the filter section:

```html
<!-- Add after existing filters -->
<div class="mb-3">
    <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" id="semanticToggle">
        <label class="form-check-label" for="semanticToggle">
            <i class="bi bi-stars"></i> AI Semantic Search
            <small class="text-muted">(searches by meaning, not keywords)</small>
        </label>
    </div>
</div>
```

**File:** `app/static/js/search.js`

Add toggle handling:

```javascript
// Add to existing state
let semanticEnabled = false;

// Toggle handler
document.getElementById('semanticToggle')?.addEventListener('change', (e) => {
    semanticEnabled = e.target.checked;
    if (document.getElementById('searchInput').value.trim()) {
        performSearch();
    }
});

// Modify performSearch to include semantic flag
async function performSearch() {
    const query = document.getElementById('searchInput').value.trim();
    // ... existing code ...

    const payload = {
        query: query,
        semantic: semanticEnabled,  // Add this
        // ... other params ...
    };

    // ... rest of function ...
}
```

---

## 5. Database Schema (Updated)

### 5.1. Migration Update

**File:** `migrations/006_add_nova_embeddings.sql`

```sql
-- Migration: Add Nova embeddings tables (sqlite-vec)
-- Created: 2025-12-19
-- Updated: 2025-12-21 (added chunk metadata)

-- Metadata table (always created)
CREATE TABLE IF NOT EXISTS nova_embedding_metadata (
    rowid INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,      -- 'transcript' or 'nova_analysis'
    source_id INTEGER NOT NULL,     -- FK to transcripts.id or nova_jobs.id
    file_id INTEGER,                -- FK to files.id (optional)
    model_name TEXT NOT NULL,       -- 'amazon.nova-2-multimodal-embeddings-v1:0'
    content_hash TEXT NOT NULL,     -- SHA-256 hash (first 32 chars)
    chunk_index INTEGER DEFAULT 0,  -- For multi-chunk sources
    chunk_start INTEGER,            -- Start char position
    chunk_end INTEGER,              -- End char position
    created_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_nova_embedding_source
ON nova_embedding_metadata(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_nova_embedding_file
ON nova_embedding_metadata(file_id);

CREATE INDEX IF NOT EXISTS idx_nova_embedding_model
ON nova_embedding_metadata(model_name);

CREATE UNIQUE INDEX IF NOT EXISTS ux_nova_embedding_unique
ON nova_embedding_metadata(source_type, source_id, model_name, content_hash);

-- Vector storage (requires sqlite-vec extension)
-- Dimension should match NOVA_EMBED_DIMENSION env var
-- Default: 1024 (recommended balance of accuracy vs storage)
CREATE VIRTUAL TABLE IF NOT EXISTS nova_embeddings USING vec0(
    embedding float[1024]
);
```

### 5.2. Environment Variables

Add to `.env`:

```bash
# Nova Embeddings Configuration
NOVA_EMBED_MODEL_ID=amazon.nova-2-multimodal-embeddings-v1:0
NOVA_EMBED_DIMENSION=1024
SQLITE_VEC_PATH=/path/to/vec0.dll  # Windows: vec0.dll, Linux: vec0.so
```

---

## 6. Cost Estimation

### 6.1. Nova Embeddings Pricing (us-east-1)

| Input Type | Price per 1K Input Tokens |
|------------|--------------------------|
| Text | ~$0.00002 |
| Image | ~$0.00006 |
| Video (per second) | ~$0.00005 |

### 6.2. Backfill Cost Estimate

For your current dataset:
- **3,154 transcripts** (avg ~5,000 chars each = ~1,250 tokens)
- **~100 Nova jobs** with summaries/chapters

| Item | Count | Tokens | Est. Cost |
|------|-------|--------|-----------|
| Transcripts | 3,154 | ~3.9M | ~$0.08 |
| Nova Summaries | 100 | ~50K | ~$0.001 |
| Nova Chapters | ~500 | ~125K | ~$0.003 |
| Nova Elements | ~200 | ~50K | ~$0.001 |
| **Total Backfill** | | ~4.1M | **~$0.09** |

### 6.3. Ongoing Costs

| Operation | Frequency | Monthly Cost |
|-----------|-----------|--------------|
| New transcripts (50/week) | 200/month | ~$0.01 |
| Search queries (100/day) | 3,000/month | ~$0.06 |
| **Monthly Total** | | **~$0.07** |

---

## 7. Verification & Testing

### 7.1. Unit Tests

**File:** `tests/test_nova_embeddings_service.py`

```python
import pytest
from unittest.mock import Mock, patch
from app.services.nova_embeddings_service import (
    NovaEmbeddingsService,
    NovaEmbeddingsError,
    EmbeddingPurpose
)


class TestNovaEmbeddingsService:

    def test_valid_dimensions(self):
        """Only 256, 384, 1024, 3072 are valid."""
        with pytest.raises(ValueError):
            NovaEmbeddingsService(dimension=512)

    def test_build_sync_request_format(self):
        """Request matches Nova schema."""
        service = NovaEmbeddingsService(dimension=1024)
        request = service._build_sync_request("test", EmbeddingPurpose.GENERIC_INDEX)

        assert request['schemaVersion'] == 'nova-multimodal-embed-v1'
        assert request['taskType'] == 'SINGLE_EMBEDDING'
        assert request['singleEmbeddingParams']['embeddingDimension'] == 1024
        assert request['singleEmbeddingParams']['text']['truncationMode'] == 'END'

    def test_text_too_long_raises_error(self):
        """Sync API rejects text >50K chars."""
        service = NovaEmbeddingsService()
        long_text = "x" * 60000

        with pytest.raises(NovaEmbeddingsError, match="too long"):
            service.embed_text(long_text)

    @patch('boto3.client')
    def test_embed_text_extracts_vector(self, mock_client):
        """Correctly extracts embedding from response."""
        mock_response = {
            'body': Mock(read=lambda: b'{"embeddings":[{"embeddingType":"TEXT","embedding":[0.1,0.2,0.3]}]}')
        }
        mock_client.return_value.invoke_model.return_value = mock_response

        service = NovaEmbeddingsService(dimension=1024)
        # Would fail dimension validation in real use, but tests extraction
        result = service._extract_embedding({
            'embeddings': [{'embeddingType': 'TEXT', 'embedding': [0.1, 0.2, 0.3]}]
        })

        assert result == [0.1, 0.2, 0.3]
```

**File:** `tests/test_embedding_manager.py`

```python
import pytest
from app.services.embedding_manager import EmbeddingManager, ChunkInfo


class TestChunking:

    def test_short_text_single_chunk(self):
        """Text under chunk_size returns single chunk."""
        manager = EmbeddingManager(db=Mock())
        chunks = manager._chunk_text("Short text", chunk_size=1000)

        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].total_chunks == 1

    def test_long_text_multiple_chunks(self):
        """Long text splits into multiple chunks."""
        manager = EmbeddingManager(db=Mock())
        text = "Word. " * 1000  # ~6000 chars
        chunks = manager._chunk_text(text, chunk_size=2000, overlap=100)

        assert len(chunks) > 1
        # Verify overlap exists
        for i in range(1, len(chunks)):
            prev_end = chunks[i-1].end_char
            curr_start = chunks[i].start_char
            assert prev_end > curr_start  # Overlap

    def test_sentence_boundary_respected(self):
        """Chunks break at sentence boundaries when possible."""
        manager = EmbeddingManager(db=Mock())
        text = "First sentence. Second sentence. Third sentence. " * 50
        chunks = manager._chunk_text(text, chunk_size=500)

        for chunk in chunks[:-1]:  # All but last
            assert chunk.text.endswith('.')


class TestHashing:

    def test_deterministic_hash(self):
        """Same content produces same hash."""
        hash1 = EmbeddingManager._compute_hash("test content")
        hash2 = EmbeddingManager._compute_hash("test content")
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Different content produces different hash."""
        hash1 = EmbeddingManager._compute_hash("content A")
        hash2 = EmbeddingManager._compute_hash("content B")
        assert hash1 != hash2
```

### 7.2. Integration Tests

**File:** `tests/test_vector_search.py`

```python
import pytest
import tempfile
from app.database import Database


@pytest.fixture
def db_with_vectors():
    """Create temp database with sqlite-vec."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db = Database(db_path=f.name)
        db.init_db()
        yield db


class TestVectorSearch:

    def test_insert_and_search(self, db_with_vectors):
        """Can insert vectors and retrieve by KNN."""
        db = db_with_vectors

        # Insert test vectors
        vec1 = [0.1] * 1024
        vec2 = [0.2] * 1024
        vec3 = [0.9] * 1024  # Very different

        db.create_nova_embedding(vec1, 'transcript', 1, 'test-model', 'hash1')
        db.create_nova_embedding(vec2, 'transcript', 2, 'test-model', 'hash2')
        db.create_nova_embedding(vec3, 'transcript', 3, 'test-model', 'hash3')

        # Search with query similar to vec1
        query = [0.11] * 1024
        results = db.search_embeddings(query, limit=2)

        assert len(results) == 2
        assert results[0]['source_id'] == 1  # Most similar

    def test_source_type_filter(self, db_with_vectors):
        """Source type filter works correctly."""
        db = db_with_vectors

        vec = [0.5] * 1024
        db.create_nova_embedding(vec, 'transcript', 1, 'model', 'h1')
        db.create_nova_embedding(vec, 'nova_analysis', 2, 'model', 'h2')

        results = db.search_embeddings(vec, source_types=['transcript'])
        assert all(r['source_type'] == 'transcript' for r in results)
```

---

## 8. Execution Order

### Prerequisites Checklist

- [ ] Download sqlite-vec extension for Windows (`vec0.dll`)
- [ ] Set `SQLITE_VEC_PATH` in `.env`
- [ ] Verify AWS credentials have Bedrock access
- [ ] Enable Nova Embeddings model in Bedrock console (us-east-1)

### Implementation Order

1. **Update NovaEmbeddingsService** (1.1)
   - Implement Nova-specific request schema
   - Add async API support
   - Add comprehensive error handling

2. **Add Database Methods** (1.2)
   - `search_embeddings()` with KNN query
   - `get_content_for_embedding_results()`
   - `delete_embeddings_for_source()`

3. **Create EmbeddingManager** (2.1)
   - Chunking logic
   - Hash-based idempotency
   - Process methods for transcripts and Nova jobs

4. **Create Backfill Script** (2.2)
   - Run with `--limit 10` first to test
   - Full backfill after validation

5. **Update Search API** (3.1)
   - Add `semantic` parameter
   - Implement semantic_search function

6. **Add UI Toggle** (3.2)
   - Toggle switch in search.html
   - JavaScript handler in search.js

7. **Real-time Integration**
   - Modify transcription completion handler
   - Modify Nova job completion handler

---

## 9. Acceptance Criteria

- [ ] `NovaEmbeddingsService.embed_text()` uses correct Nova schema
- [ ] Embeddings stored with correct dimension (1024)
- [ ] `search_embeddings()` returns ranked results by distance
- [ ] Backfill completes without re-embedding duplicates
- [ ] `/api/search?semantic=true` returns semantic results
- [ ] UI toggle enables/disables semantic search
- [ ] Default search behavior unchanged (semantic=false)
- [ ] Costs tracked and within estimates

---

## 10. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| sqlite-vec not loading | High | Provide clear error message, fallback to keyword-only |
| Nova API rate limits | Medium | Implement exponential backoff, batch processing |
| Embedding dimension mismatch | High | Validate dimensions on every operation |
| Long transcript timeouts | Medium | Use async API for >8K tokens |
| S3 costs for async output | Low | Clean up async output files after processing |

---

## 11. Future Enhancements

1. **Hybrid Search**: Combine keyword + semantic scores with weighted ranking
2. **Video Frame Embeddings**: Use Nova's image/video embedding for visual search
3. **Cross-Modal Search**: "Find videos showing a waterfall" using multimodal embeddings
4. **Clustering**: Automatic content categorization using embeddings
5. **Recommendations**: "Similar videos" feature based on embedding similarity
