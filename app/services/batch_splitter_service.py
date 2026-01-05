"""
Service for splitting batch jobs into smaller chunks.
Handles the 5GB Bedrock limitation and 150 file limit.
"""
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class BatchChunk:
    """Represents a single batch job chunk."""
    chunk_index: int              # 1-based index
    file_ids: List[int]           # File IDs in this chunk
    proxy_s3_keys: List[str]      # Original S3 keys for these files
    proxy_sizes: List[int]        # Size in bytes for each file
    total_size_bytes: int         # Total size of all files in chunk
    s3_folder: str                # Target folder: "nova_batch/job_{timestamp}_{index:03d}"


# Configuration Constants
MIN_FILES_PER_BATCH = 100  # Bedrock minimum requirement
MAX_FILES_PER_BATCH = 150
MAX_SIZE_BYTES = 5 * 1024 * 1024 * 1024  # 5GB
SAFETY_MARGIN = 0.9  # Use 90% of max to leave buffer
EFFECTIVE_MAX_SIZE = int(MAX_SIZE_BYTES * SAFETY_MARGIN)  # ~4.5GB


def split_batch_by_size(
    files: List[Dict],
    timestamp: str
) -> List[BatchChunk]:
    """
    Split a list of files into batch chunks.

    Each chunk respects BOTH limits:
    - Maximum 150 files per batch
    - Maximum ~4.5GB total size per batch (5GB with 10% safety margin)

    Files are processed in order. When adding a file would exceed either limit,
    a new chunk is started.

    Args:
        files: List of dicts, each containing:
            - file_id: int - Database file ID
            - proxy_s3_key: str - S3 key of the proxy file
            - proxy_size_bytes: int - Size of the proxy file in bytes
        timestamp: Timestamp string for folder naming (format: "YYYYMMDD_HHMMSS")

    Returns:
        List of BatchChunk objects, each representing one batch job to submit

    Example:
        files = [
            {'file_id': 1, 'proxy_s3_key': 'proxy_video/a.mov', 'proxy_size_bytes': 1000000},
            {'file_id': 2, 'proxy_s3_key': 'proxy_video/b.mov', 'proxy_size_bytes': 2000000},
        ]
        chunks = split_batch_by_size(files, "20260105_123456")
        # Returns: [BatchChunk(chunk_index=1, file_ids=[1, 2], ...)]
    """
    if not files:
        return []

    chunks = []
    current_file_ids = []
    current_s3_keys = []
    current_sizes = []
    current_total_size = 0
    chunk_index = 1

    for file_info in files:
        file_id = file_info['file_id']
        proxy_s3_key = file_info['proxy_s3_key']
        size_bytes = file_info.get('proxy_size_bytes') or 0

        # Check if adding this file would exceed either limit
        would_exceed_count = len(current_file_ids) >= MAX_FILES_PER_BATCH
        would_exceed_size = (current_total_size + size_bytes) > EFFECTIVE_MAX_SIZE

        # If current chunk is non-empty and would exceed limits, finalize it
        if current_file_ids and (would_exceed_count or would_exceed_size):
            chunks.append(BatchChunk(
                chunk_index=chunk_index,
                file_ids=current_file_ids,
                proxy_s3_keys=current_s3_keys,
                proxy_sizes=current_sizes,
                total_size_bytes=current_total_size,
                s3_folder=f"nova_batch/job_{timestamp}_{chunk_index:03d}"
            ))
            chunk_index += 1
            current_file_ids = []
            current_s3_keys = []
            current_sizes = []
            current_total_size = 0

        # Add file to current chunk
        current_file_ids.append(file_id)
        current_s3_keys.append(proxy_s3_key)
        current_sizes.append(size_bytes)
        current_total_size += size_bytes

    # Don't forget the last chunk
    if current_file_ids:
        chunks.append(BatchChunk(
            chunk_index=chunk_index,
            file_ids=current_file_ids,
            proxy_s3_keys=current_s3_keys,
            proxy_sizes=current_sizes,
            total_size_bytes=current_total_size,
            s3_folder=f"nova_batch/job_{timestamp}_{chunk_index:03d}"
        ))

    # Handle minimum batch size requirement
    if len(chunks) >= 2 and len(chunks[-1].file_ids) < MIN_FILES_PER_BATCH:
        # Merge undersized last chunk with previous chunk
        last_chunk = chunks.pop()
        prev_chunk = chunks.pop()

        merged = BatchChunk(
            chunk_index=prev_chunk.chunk_index,
            file_ids=prev_chunk.file_ids + last_chunk.file_ids,
            proxy_s3_keys=prev_chunk.proxy_s3_keys + last_chunk.proxy_s3_keys,
            proxy_sizes=prev_chunk.proxy_sizes + last_chunk.proxy_sizes,
            total_size_bytes=prev_chunk.total_size_bytes + last_chunk.total_size_bytes,
            s3_folder=prev_chunk.s3_folder
        )
        chunks.append(merged)
    elif len(chunks) == 1 and len(chunks[0].file_ids) < MIN_FILES_PER_BATCH:
        # Single chunk with < 100 files - batch mode not suitable
        raise ValueError(
            f"Batch mode requires at least {MIN_FILES_PER_BATCH} files. "
            f"Got {len(chunks[0].file_ids)} files. Use individual processing instead."
        )

    return chunks


def estimate_chunk_count(total_files: int, total_size_bytes: int) -> int:
    """
    Estimate how many batch chunks will be needed.
    Useful for progress reporting before actual splitting.

    Args:
        total_files: Total number of files
        total_size_bytes: Total size of all files in bytes

    Returns:
        Estimated number of chunks (minimum 1)
    """
    if total_files == 0:
        return 0

    chunks_by_count = (total_files + MAX_FILES_PER_BATCH - 1) // MAX_FILES_PER_BATCH
    chunks_by_size = (total_size_bytes + EFFECTIVE_MAX_SIZE - 1) // EFFECTIVE_MAX_SIZE

    return max(chunks_by_count, chunks_by_size, 1)
