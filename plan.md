# Nova Batch Processing Fix - Implementation Plan

## Problem Statement

AWS Bedrock Batch API fails to process video files when S3 keys contain special characters (spaces, commas, parentheses). The batch API cannot handle these characters regardless of URL encoding. Additionally, there is a 5GB bucket size limitation that causes batch validation failures for large submissions.

### Root Cause Analysis

1. **Special Characters Issue**: S3 stores files with literal keys like `proxies/Video Nov 14 2025, 10 02 14 AM_22153_720p15.mov`. When Bedrock Batch API attempts to access these, it fails with "Provided S3 URI is invalid" (HTTP 400).

2. **5GB Limitation**: Bedrock Batch API validates the total size of the InputDataConfig S3 location. If the bucket/folder exceeds 5GB, batch submission fails.

3. **URL Encoding Does Not Work**: When we URL-encode the S3 key (e.g., `Video%20Nov%2014%202025`), Bedrock looks for an object with that literal key, but the actual S3 object has spaces in its key. This causes a 404 mismatch.

### Current Failures
- 35 files failed due to spaces and commas in filenames
- All files with special characters will continue to fail in batch mode
- Large batches exceeding 5GB fail validation

---

## Solution Architecture

### Overview

1. **Sanitize filenames** during batch preparation by creating temporary copies with safe names
2. **Create isolated S3 folders** for each batch job containing sanitized file copies
3. **Split large batches** into multiple jobs (max 150 files OR 4.5GB per job)
4. **Clean up S3 files** after successful processing (S3 is temporary storage)

### S3 Folder Structure

```
s3://video-analysis-app-676206912644/
├── proxy_video/                    # Permanent proxy storage (original names preserved)
│   └── Video Nov 14 2025.mov       # Original filename with spaces/commas
├── proxy_image/                    # Permanent image proxy storage
├── nova_batch/                     # Temporary batch processing folder (NEW)
│   └── job_20260105_123456_001/    # One folder per batch job
│       ├── manifest.jsonl          # Batch input manifest
│       └── files/                  # Sanitized copies of proxy files
│           └── Video_Nov_14_2025_22153.mov  # Sanitized filename
└── nova/batch/output/              # Batch output results (existing)
```

### Key Design Decisions

1. **Copy files, don't rename**: Original proxies in `proxy_video/` keep their names for on-demand API compatibility
2. **Isolated folders per job**: Each batch job gets its own folder to avoid 5GB bucket-level limit
3. **150 files OR 4.5GB limit**: Use whichever is reached first (4.5GB gives 10% safety margin under 5GB)
4. **Cleanup after success**: Delete temporary copies and manifests after results are fetched

---

## Implementation Steps

### Step 1: Create Filename Sanitization Utility

**File**: `app/utils/filename_sanitizer.py` (NEW FILE)

**Purpose**: Convert filenames with special characters to safe versions for S3 batch processing.

**Implementation**:

```python
"""
Filename sanitization utility for S3 batch processing.
Converts filenames with special characters to safe versions.
"""
import re
import unicodedata


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename for safe S3 batch processing.

    Transformations applied in order:
    1. Normalize unicode characters to ASCII equivalents
    2. Replace spaces with underscores
    3. Remove special characters: , ( ) [ ] { } ! @ # $ % ^ & * + = | \ : ; " ' < > ?
    4. Collapse multiple consecutive underscores to single underscore
    5. Remove leading/trailing underscores
    6. Preserve file extension

    Args:
        filename: Original filename
            Example: "Video Nov 14 2025, 10 02 14 AM_22153_720p15.mov"

    Returns:
        Sanitized filename
            Example: "Video_Nov_14_2025_10_02_14_AM_22153_720p15.mov"
    """
    # Separate extension from name
    if '.' in filename:
        name, ext = filename.rsplit('.', 1)
    else:
        name, ext = filename, ''

    # Step 1: Normalize unicode to ASCII
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')

    # Step 2: Replace spaces with underscores
    name = name.replace(' ', '_')

    # Step 3: Remove special characters (keep alphanumeric, underscore, hyphen)
    name = re.sub(r'[,\(\)\[\]\{\}!@#$%^&*+=|\\:;"\'<>?]', '', name)

    # Step 4: Collapse multiple underscores to single
    name = re.sub(r'_+', '_', name)

    # Step 5: Remove leading/trailing underscores
    name = name.strip('_')

    # Reconstruct with extension
    if ext:
        return f"{name}.{ext}"
    return name


def sanitize_s3_key(s3_key: str) -> str:
    """
    Sanitize an S3 key, preserving the directory structure.
    Only the filename portion is sanitized, not the path.

    Args:
        s3_key: Full S3 key
            Example: "proxy_video/Video Nov 14 2025, 10 02 14 AM_22153_720p15.mov"

    Returns:
        Sanitized S3 key
            Example: "proxy_video/Video_Nov_14_2025_10_02_14_AM_22153_720p15.mov"
    """
    if '/' in s3_key:
        directory, filename = s3_key.rsplit('/', 1)
        return f"{directory}/{sanitize_filename(filename)}"
    return sanitize_filename(s3_key)
```

**Unit Tests**: Create `tests/test_filename_sanitizer.py`

```python
"""Tests for filename sanitization."""
import pytest
from app.utils.filename_sanitizer import sanitize_filename, sanitize_s3_key


class TestSanitizeFilename:
    def test_spaces_replaced_with_underscores(self):
        assert sanitize_filename("Video Nov 14.mov") == "Video_Nov_14.mov"

    def test_commas_removed(self):
        assert sanitize_filename("Video, Part 1.mov") == "Video_Part_1.mov"

    def test_parentheses_removed(self):
        assert sanitize_filename("Video (1).mov") == "Video_1.mov"

    def test_multiple_special_chars(self):
        assert sanitize_filename("Video (1), Test [2].mov") == "Video_1_Test_2.mov"

    def test_preserves_file_id_pattern(self):
        # File ID suffix pattern should be preserved
        assert sanitize_filename("Video_22153_720p15.mov") == "Video_22153_720p15.mov"

    def test_collapses_multiple_underscores(self):
        assert sanitize_filename("Video___Test.mov") == "Video_Test.mov"

    def test_removes_leading_trailing_underscores(self):
        assert sanitize_filename("_Video_.mov") == "Video.mov"

    def test_preserves_extension(self):
        assert sanitize_filename("test file.MP4") == "test_file.MP4"

    def test_handles_no_extension(self):
        assert sanitize_filename("test file") == "test_file"

    def test_complex_real_filename(self):
        input_name = "Video Nov 14 2025, 10 02 14 AM_22153_720p15.mov"
        expected = "Video_Nov_14_2025_10_02_14_AM_22153_720p15.mov"
        assert sanitize_filename(input_name) == expected

    def test_already_clean_filename(self):
        assert sanitize_filename("C0134_33946_720p15.MP4") == "C0134_33946_720p15.MP4"


class TestSanitizeS3Key:
    def test_preserves_directory(self):
        assert sanitize_s3_key("proxy_video/Test File.mov") == "proxy_video/Test_File.mov"

    def test_nested_directory(self):
        assert sanitize_s3_key("a/b/c/Test File.mov") == "a/b/c/Test_File.mov"

    def test_no_directory(self):
        assert sanitize_s3_key("Test File.mov") == "Test_File.mov"
```

---

### Step 2: Create Batch Job Splitter Service

**File**: `app/services/batch_splitter_service.py` (NEW FILE)

**Purpose**: Split large batch requests into smaller chunks that respect Bedrock's limits.

**Implementation**:

```python
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
```

**Unit Tests**: Create `tests/test_batch_splitter.py`

```python
"""Tests for batch splitting logic."""
import pytest
from app.services.batch_splitter_service import (
    split_batch_by_size,
    estimate_chunk_count,
    MAX_FILES_PER_BATCH,
    EFFECTIVE_MAX_SIZE
)


class TestSplitBatchBySize:
    def test_empty_list_returns_empty(self):
        assert split_batch_by_size([], "20260105_123456") == []

    def test_single_file_returns_one_chunk(self):
        files = [{'file_id': 1, 'proxy_s3_key': 'a.mov', 'proxy_size_bytes': 1000}]
        chunks = split_batch_by_size(files, "20260105_123456")
        assert len(chunks) == 1
        assert chunks[0].file_ids == [1]
        assert chunks[0].chunk_index == 1

    def test_splits_at_150_files(self):
        files = [
            {'file_id': i, 'proxy_s3_key': f'{i}.mov', 'proxy_size_bytes': 1000}
            for i in range(200)
        ]
        chunks = split_batch_by_size(files, "20260105_123456")
        assert len(chunks) == 2
        assert len(chunks[0].file_ids) == 150
        assert len(chunks[1].file_ids) == 50

    def test_splits_at_size_limit(self):
        # Create files that exceed 4.5GB total
        large_size = EFFECTIVE_MAX_SIZE // 2 + 1  # Just over half the limit
        files = [
            {'file_id': 1, 'proxy_s3_key': 'a.mov', 'proxy_size_bytes': large_size},
            {'file_id': 2, 'proxy_s3_key': 'b.mov', 'proxy_size_bytes': large_size},
            {'file_id': 3, 'proxy_s3_key': 'c.mov', 'proxy_size_bytes': large_size},
        ]
        chunks = split_batch_by_size(files, "20260105_123456")
        assert len(chunks) == 2  # Files 1+2 exceed limit, so file 2 starts new chunk

    def test_folder_naming(self):
        files = [{'file_id': 1, 'proxy_s3_key': 'a.mov', 'proxy_size_bytes': 1000}]
        chunks = split_batch_by_size(files, "20260105_123456")
        assert chunks[0].s3_folder == "nova_batch/job_20260105_123456_001"

    def test_chunk_index_increments(self):
        files = [
            {'file_id': i, 'proxy_s3_key': f'{i}.mov', 'proxy_size_bytes': 1000}
            for i in range(450)  # Will create 3 chunks
        ]
        chunks = split_batch_by_size(files, "20260105_123456")
        assert len(chunks) == 3
        assert chunks[0].chunk_index == 1
        assert chunks[1].chunk_index == 2
        assert chunks[2].chunk_index == 3


class TestEstimateChunkCount:
    def test_zero_files(self):
        assert estimate_chunk_count(0, 0) == 0

    def test_small_batch(self):
        assert estimate_chunk_count(50, 1000000) == 1

    def test_count_limited(self):
        # 200 files, small size
        assert estimate_chunk_count(200, 1000) == 2

    def test_size_limited(self):
        # Few files but large size (10GB)
        assert estimate_chunk_count(10, 10 * 1024 * 1024 * 1024) >= 2
```

---

### Step 3: Create Batch S3 Manager Service

**File**: `app/services/batch_s3_manager.py` (NEW FILE)

**Purpose**: Handle S3 operations for batch processing - copying files with sanitized names, uploading manifests, and cleanup.

**Implementation**:

```python
"""
Service for managing S3 files during batch processing.
Handles copying files with sanitized names and cleanup after processing.
"""
import logging
from typing import List, Dict, Optional
from botocore.exceptions import ClientError

from app.utils.filename_sanitizer import sanitize_filename

logger = logging.getLogger(__name__)


class BatchS3Manager:
    """
    Manages S3 operations for Nova batch processing.

    Responsibilities:
    1. Copy proxy files to batch folder with sanitized filenames
    2. Upload JSONL manifest files
    3. Clean up batch folders after successful processing
    """

    def __init__(self, s3_client, bucket_name: str):
        """
        Initialize the manager.

        Args:
            s3_client: boto3 S3 client instance
            bucket_name: Name of the S3 bucket
        """
        self.s3 = s3_client
        self.bucket = bucket_name

    def prepare_batch_files(
        self,
        proxy_s3_keys: List[str],
        batch_folder: str
    ) -> Dict[str, str]:
        """
        Copy proxy files to batch folder with sanitized filenames.

        Creates sanitized copies in: {batch_folder}/files/{sanitized_filename}

        Args:
            proxy_s3_keys: List of original proxy S3 keys
                Example: ["proxy_video/Video Nov 14 2025_22153_720p15.mov"]
            batch_folder: Target batch folder
                Example: "nova_batch/job_20260105_123456_001"

        Returns:
            Dict mapping original_key -> sanitized_key
                Example: {
                    "proxy_video/Video Nov 14 2025_22153_720p15.mov":
                    "nova_batch/job_20260105_123456_001/files/Video_Nov_14_2025_22153_720p15.mov"
                }

        Raises:
            Exception: If any file copy fails
        """
        key_mapping = {}
        files_folder = f"{batch_folder}/files"

        for original_key in proxy_s3_keys:
            # Extract filename from path and sanitize
            original_filename = original_key.rsplit('/', 1)[-1]
            sanitized_filename = sanitize_filename(original_filename)
            sanitized_key = f"{files_folder}/{sanitized_filename}"

            # Copy object to new location with sanitized name
            try:
                self.s3.copy_object(
                    Bucket=self.bucket,
                    CopySource={'Bucket': self.bucket, 'Key': original_key},
                    Key=sanitized_key
                )
                key_mapping[original_key] = sanitized_key
                logger.debug(f"Copied {original_key} -> {sanitized_key}")
            except ClientError as e:
                logger.error(f"Failed to copy {original_key} to {sanitized_key}: {e}")
                raise Exception(f"Failed to prepare batch file: {original_key}") from e

        logger.info(f"Prepared {len(key_mapping)} files in {batch_folder}")
        return key_mapping

    def upload_manifest(
        self,
        manifest_content: str,
        batch_folder: str
    ) -> str:
        """
        Upload the JSONL manifest file to the batch folder.

        Args:
            manifest_content: JSONL content (newline-separated JSON records)
            batch_folder: Target batch folder

        Returns:
            S3 key of the uploaded manifest
                Example: "nova_batch/job_20260105_123456_001/manifest.jsonl"
        """
        manifest_key = f"{batch_folder}/manifest.jsonl"

        self.s3.put_object(
            Bucket=self.bucket,
            Key=manifest_key,
            Body=manifest_content.encode('utf-8'),
            ContentType='application/jsonl'
        )

        logger.info(f"Uploaded manifest to {manifest_key}")
        return manifest_key

    def cleanup_batch_folder(self, batch_folder: str) -> Dict[str, int]:
        """
        Delete all files in a batch folder and its output folder.

        Cleans up:
        - {batch_folder}/* (manifest and copied files)
        - nova/batch/output/{batch_folder}/* (output results)

        Args:
            batch_folder: Folder to clean up
                Example: "nova_batch/job_20260105_123456_001"

        Returns:
            Dict with cleanup stats:
                {'objects_deleted': int, 'bytes_freed': int}
        """
        stats = {'objects_deleted': 0, 'bytes_freed': 0}

        # Clean both input and output folders
        folders_to_clean = [
            batch_folder,
            f"nova/batch/output/{batch_folder}"
        ]

        for folder in folders_to_clean:
            folder_stats = self._delete_folder_contents(folder)
            stats['objects_deleted'] += folder_stats['objects_deleted']
            stats['bytes_freed'] += folder_stats['bytes_freed']

        logger.info(
            f"Cleaned up {batch_folder}: "
            f"{stats['objects_deleted']} objects, "
            f"{stats['bytes_freed'] / 1024 / 1024:.2f} MB freed"
        )
        return stats

    def _delete_folder_contents(self, prefix: str) -> Dict[str, int]:
        """Delete all objects with the given prefix."""
        stats = {'objects_deleted': 0, 'bytes_freed': 0}

        paginator = self.s3.get_paginator('list_objects_v2')

        try:
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)

            for page in pages:
                if 'Contents' not in page:
                    continue

                # Collect objects to delete (max 1000 per request)
                objects = []
                for obj in page['Contents']:
                    objects.append({'Key': obj['Key']})
                    stats['bytes_freed'] += obj['Size']

                if objects:
                    self.s3.delete_objects(
                        Bucket=self.bucket,
                        Delete={'Objects': objects}
                    )
                    stats['objects_deleted'] += len(objects)

        except ClientError as e:
            logger.warning(f"Error cleaning folder {prefix}: {e}")

        return stats

    def get_folder_size(self, folder: str) -> int:
        """
        Get total size of all objects in a folder.

        Args:
            folder: S3 prefix to measure

        Returns:
            Total size in bytes
        """
        total_size = 0
        paginator = self.s3.get_paginator('list_objects_v2')

        try:
            pages = paginator.paginate(Bucket=self.bucket, Prefix=folder)
            for page in pages:
                if 'Contents' in page:
                    total_size += sum(obj['Size'] for obj in page['Contents'])
        except ClientError as e:
            logger.warning(f"Error getting folder size for {folder}: {e}")

        return total_size

    def verify_files_exist(self, s3_keys: List[str]) -> Dict[str, bool]:
        """
        Check which files exist in S3.

        Args:
            s3_keys: List of S3 keys to check

        Returns:
            Dict mapping key -> exists (True/False)
        """
        results = {}
        for key in s3_keys:
            try:
                self.s3.head_object(Bucket=self.bucket, Key=key)
                results[key] = True
            except ClientError:
                results[key] = False
        return results
```

---

### Step 4: Modify Nova Service for Multi-Job Batches

**File**: `app/services/nova_service.py`

#### 4.1: Remove URL Encoding (Lines 164-170)

**Current code to REMOVE**:
```python
def _build_s3_uri(self, s3_key: str) -> str:
    """Build S3 URI from bucket and key with URL encoding for special characters."""
    from urllib.parse import quote
    # URL-encode the S3 key to handle spaces, commas, and other special characters
    # safe='/' preserves forward slashes in the path
    encoded_key = quote(s3_key, safe='/')
    return f"s3://{self.bucket_name}/{encoded_key}"
```

**Replace with**:
```python
def _build_s3_uri(self, s3_key: str) -> str:
    """Build S3 URI from bucket and key."""
    return f"s3://{self.bucket_name}/{s3_key}"
```

#### 4.2: Add New Imports at Top of File

Add these imports near the top of the file:
```python
from app.services.batch_splitter_service import BatchChunk
from app.services.batch_s3_manager import BatchS3Manager
```

#### 4.3: Add Multi-Job Batch Submission Method

Add this new method to the `NovaVideoService` class (after the existing batch methods, around line 520):

```python
def submit_multi_chunk_batch(
    self,
    chunks: List[BatchChunk],
    model: str,
    analysis_types: List[str],
    options: Dict[str, Any],
    batch_s3_manager: BatchS3Manager,
    file_id_to_analysis_job_id: Dict[int, int]
) -> List[Dict[str, Any]]:
    """
    Submit multiple batch jobs for a set of chunks.

    For each chunk:
    1. Copy proxy files to isolated S3 folder with sanitized names
    2. Build batch records using sanitized S3 keys
    3. Upload JSONL manifest to the chunk's folder
    4. Submit batch job to Bedrock with InputDataConfig pointing to chunk folder

    Args:
        chunks: List of BatchChunk objects from batch_splitter_service
        model: Nova model to use (e.g., "nova-lite")
        analysis_types: Analysis types to run (e.g., ["combined"])
        options: Analysis options dict
        batch_s3_manager: BatchS3Manager instance for S3 operations
        file_id_to_analysis_job_id: Mapping of file_id -> analysis_job_id for tracking

    Returns:
        List of dicts, one per chunk:
        {
            'chunk_index': int,
            'batch_job_arn': str,
            's3_folder': str,
            'file_ids': List[int],
            'file_count': int,
            'size_bytes': int,
            'key_mapping': Dict[str, str]  # original_key -> sanitized_key
        }

    Raises:
        Exception: If any chunk submission fails (partial submissions may exist)
    """
    import json

    results = []

    for chunk in chunks:
        logger.info(
            f"Processing chunk {chunk.chunk_index}: "
            f"{len(chunk.file_ids)} files, "
            f"{chunk.total_size_bytes / 1024 / 1024:.1f} MB"
        )

        # Step 1: Copy files to batch folder with sanitized names
        key_mapping = batch_s3_manager.prepare_batch_files(
            chunk.proxy_s3_keys,
            chunk.s3_folder
        )

        # Step 2: Build batch records using sanitized keys
        all_records = []
        for file_id, original_key in zip(chunk.file_ids, chunk.proxy_s3_keys):
            sanitized_key = key_mapping[original_key]

            # Build records for this file using sanitized key
            records = self._build_batch_records(
                s3_key=sanitized_key,
                analysis_types=analysis_types,
                options=options,
                record_prefix=f"file-{file_id}:"
            )
            all_records.extend(records)

        # Step 3: Create and upload manifest
        manifest_lines = [json.dumps(record) for record in all_records]
        manifest_content = '\n'.join(manifest_lines)
        manifest_key = batch_s3_manager.upload_manifest(manifest_content, chunk.s3_folder)

        # Step 4: Submit batch job to Bedrock
        # CRITICAL: InputDataConfig points to the chunk's folder (not bucket root)
        # This folder contains BOTH the manifest.jsonl AND the files/ subfolder
        input_s3_uri = f"s3://{self.bucket_name}/{chunk.s3_folder}/"
        output_s3_uri = f"s3://{self.bucket_name}/nova/batch/output/{chunk.s3_folder}/"

        job_name = f"nova-batch-{chunk.s3_folder.replace('/', '-')}"

        # Use existing _start_batch_job method
        runtime_model_id = self._get_model_id(model)
        role_arn = self.batch_role_arn

        batch_job_arn = self._start_batch_job(
            job_name=job_name,
            model_id=runtime_model_id,
            role_arn=role_arn,
            input_s3_uri=input_s3_uri,
            output_s3_uri=output_s3_uri
        )

        results.append({
            'chunk_index': chunk.chunk_index,
            'batch_job_arn': batch_job_arn,
            's3_folder': chunk.s3_folder,
            'file_ids': chunk.file_ids,
            'file_count': len(chunk.file_ids),
            'size_bytes': chunk.total_size_bytes,
            'key_mapping': key_mapping
        })

        logger.info(f"Submitted chunk {chunk.chunk_index}: {batch_job_arn}")

    return results
```

---

### Step 5: Add Database Fields for Multi-Job Tracking

**File**: `app/database/models.py` or create migration script

Add these columns to the `bedrock_batch_jobs` table:

```sql
-- Run as migration or add to schema
ALTER TABLE bedrock_batch_jobs ADD COLUMN parent_batch_id TEXT;
ALTER TABLE bedrock_batch_jobs ADD COLUMN chunk_index INTEGER;
ALTER TABLE bedrock_batch_jobs ADD COLUMN total_chunks INTEGER;
ALTER TABLE bedrock_batch_jobs ADD COLUMN s3_folder TEXT;
ALTER TABLE bedrock_batch_jobs ADD COLUMN cleanup_completed_at TIMESTAMP;

-- Index for efficient parent batch lookups
CREATE INDEX IF NOT EXISTS idx_bedrock_batch_jobs_parent
ON bedrock_batch_jobs(parent_batch_id);
```

**Update database helper functions** in `app/database/batch_jobs.py`:

Add parameters to `create_bedrock_batch_job()`:
```python
def create_bedrock_batch_job(
    batch_job_arn: str,
    job_name: str,
    model: str,
    nova_job_ids: List[int],
    input_s3_key: str,
    output_s3_prefix: str,
    parent_batch_id: str = None,      # NEW
    chunk_index: int = None,          # NEW
    total_chunks: int = None,         # NEW
    s3_folder: str = None             # NEW
) -> int:
    """Create a new bedrock batch job record."""
    # ... existing code ...
    # Add new columns to INSERT statement
```

Add new query function:
```python
def get_batch_jobs_by_parent(parent_batch_id: str) -> List[Dict]:
    """Get all batch jobs belonging to a parent batch group."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM bedrock_batch_jobs
            WHERE parent_batch_id = ?
            ORDER BY chunk_index
        ''', (parent_batch_id,))
        return [dict(row) for row in cursor.fetchall()]


def get_cleanable_batch_jobs() -> List[Dict]:
    """Get batch jobs that are completed and ready for S3 cleanup."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM bedrock_batch_jobs
            WHERE status = 'COMPLETED'
            AND cleanup_completed_at IS NULL
            AND s3_folder IS NOT NULL
        ''')
        return [dict(row) for row in cursor.fetchall()]


def mark_batch_job_cleaned(job_id: int):
    """Mark a batch job as cleaned up."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE bedrock_batch_jobs
            SET cleanup_completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (job_id,))
        conn.commit()
```

---

### Step 6: Modify Batch Route for Multi-Job Support

**File**: `app/routes/file_management/batch.py`

#### 6.1: Add Imports at Top of File

```python
from datetime import datetime
from app.services.batch_splitter_service import split_batch_by_size, estimate_chunk_count
from app.services.batch_s3_manager import BatchS3Manager
```

#### 6.2: Update Batch Nova Submission Handler

Find the batch Nova submission handler (the function that processes batch_nova action, around line 1400-1500).

**Replace the batch submission logic with**:

```python
# Inside the batch nova submission handler, after getting file_ids and validating:

# Step 1: Get file info with sizes for splitting
files_with_sizes = []
for file_id in file_ids:
    # Get proxy info for this file
    proxy = db.get_proxy_for_file(file_id)
    if proxy and proxy.get('s3_key'):
        files_with_sizes.append({
            'file_id': file_id,
            'proxy_s3_key': proxy['s3_key'],
            'proxy_size_bytes': proxy.get('file_size', 0) or 0
        })

if not files_with_sizes:
    return jsonify({'error': 'No valid proxy files found'}), 400

# Step 2: Split into chunks (150 files or 4.5GB max per chunk)
timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
chunks = split_batch_by_size(files_with_sizes, timestamp)

logger.info(
    f"Split {len(file_ids)} files into {len(chunks)} batch jobs "
    f"(total size: {sum(f['proxy_size_bytes'] for f in files_with_sizes) / 1024 / 1024:.1f} MB)"
)

# Step 3: Create database records for tracking
parent_batch_id = f"batch-group-{timestamp}"
file_id_to_analysis_job_id = {}
nova_job_ids_by_chunk = {}

for chunk in chunks:
    chunk_nova_job_ids = []
    for file_id in chunk.file_ids:
        # Create analysis_job record
        analysis_job_id = db.create_analysis_job(
            file_id=file_id,
            job_id=f"nova-batch-{parent_batch_id}-{file_id}",
            analysis_type='nova',
            model=model,
            status='PENDING'
        )
        file_id_to_analysis_job_id[file_id] = analysis_job_id

        # Create nova_job record
        nova_job_id = db.create_nova_job(
            analysis_job_id=analysis_job_id,
            model=model,
            analysis_types=analysis_types,
            status='PENDING'
        )
        db.update_nova_job(nova_job_id, {'batch_mode': True})
        chunk_nova_job_ids.append(nova_job_id)

    nova_job_ids_by_chunk[chunk.chunk_index] = chunk_nova_job_ids

# Step 4: Initialize S3 manager and Nova service
s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
batch_s3_manager = BatchS3Manager(s3_client, os.getenv('S3_BUCKET_NAME'))
nova_service = NovaVideoService()

# Step 5: Submit all chunks
batch_results = nova_service.submit_multi_chunk_batch(
    chunks=chunks,
    model=model,
    analysis_types=analysis_types,
    options=options,
    batch_s3_manager=batch_s3_manager,
    file_id_to_analysis_job_id=file_id_to_analysis_job_id
)

# Step 6: Record batch jobs in database
for result in batch_results:
    chunk_index = result['chunk_index']

    db.create_bedrock_batch_job(
        batch_job_arn=result['batch_job_arn'],
        job_name=f"{parent_batch_id}-chunk-{chunk_index:03d}",
        model=model,
        nova_job_ids=nova_job_ids_by_chunk[chunk_index],
        input_s3_key=f"{result['s3_folder']}/manifest.jsonl",
        output_s3_prefix=f"nova/batch/output/{result['s3_folder']}/",
        parent_batch_id=parent_batch_id,
        chunk_index=chunk_index,
        total_chunks=len(chunks),
        s3_folder=result['s3_folder']
    )

    # Update nova_jobs with batch info
    for nova_job_id in nova_job_ids_by_chunk[chunk_index]:
        db.update_nova_job(nova_job_id, {
            'batch_job_arn': result['batch_job_arn'],
            'batch_status': 'SUBMITTED',
            'status': 'SUBMITTED'
        })

# Step 7: Return response
return jsonify({
    'success': True,
    'parent_batch_id': parent_batch_id,
    'total_files': len(file_ids),
    'total_chunks': len(chunks),
    'chunks': [
        {
            'chunk_index': r['chunk_index'],
            'batch_job_arn': r['batch_job_arn'],
            'file_count': r['file_count'],
            'size_mb': r['size_bytes'] / 1024 / 1024
        }
        for r in batch_results
    ]
})
```

---

### Step 7: Add S3 Cleanup After Successful Processing

**File**: `app/services/batch_cleanup_service.py` (MODIFY EXISTING)

Add this method to handle cleanup of completed batch jobs:

```python
def cleanup_completed_batch_jobs(self, dry_run: bool = False) -> Dict[str, Any]:
    """
    Clean up S3 folders for all completed batch jobs.

    Only cleans up jobs that:
    1. Have status = 'COMPLETED'
    2. Have s3_folder set (new multi-job format)
    3. Haven't been cleaned up yet (cleanup_completed_at IS NULL)

    Args:
        dry_run: If True, only report what would be cleaned without deleting

    Returns:
        Dict with cleanup stats:
        {
            'jobs_processed': int,
            'jobs_cleaned': int,
            'objects_deleted': int,
            'bytes_freed': int,
            'errors': List[str]
        }
    """
    from app.database.batch_jobs import get_cleanable_batch_jobs, mark_batch_job_cleaned

    stats = {
        'jobs_processed': 0,
        'jobs_cleaned': 0,
        'objects_deleted': 0,
        'bytes_freed': 0,
        'errors': []
    }

    jobs = get_cleanable_batch_jobs()
    stats['jobs_processed'] = len(jobs)

    logger.info(f"Found {len(jobs)} completed batch jobs ready for cleanup")

    for job in jobs:
        job_id = job['id']
        s3_folder = job['s3_folder']

        if not s3_folder:
            continue

        try:
            if dry_run:
                # Just calculate what would be deleted
                size = self.batch_s3_manager.get_folder_size(s3_folder)
                output_size = self.batch_s3_manager.get_folder_size(
                    f"nova/batch/output/{s3_folder}"
                )
                stats['bytes_freed'] += size + output_size
                stats['jobs_cleaned'] += 1
                logger.info(f"[DRY RUN] Would clean {s3_folder}: {(size + output_size) / 1024 / 1024:.2f} MB")
            else:
                # Actually delete the files
                cleanup_result = self.batch_s3_manager.cleanup_batch_folder(s3_folder)
                stats['objects_deleted'] += cleanup_result['objects_deleted']
                stats['bytes_freed'] += cleanup_result['bytes_freed']

                # Mark as cleaned in database
                mark_batch_job_cleaned(job_id)
                stats['jobs_cleaned'] += 1

                logger.info(f"Cleaned batch job {job_id}, folder {s3_folder}")

        except Exception as e:
            error_msg = f"Failed to clean job {job_id} ({s3_folder}): {e}"
            logger.error(error_msg)
            stats['errors'].append(error_msg)

    return stats
```

---

### Step 8: Create Cleanup Management Script

**File**: `scripts/cleanup_batch_folders.py` (NEW FILE)

```python
"""
Script to clean up S3 folders from completed batch jobs.
Can be run manually or via scheduled task.

Usage:
    python -m scripts.cleanup_batch_folders [--dry-run]

Examples:
    # Preview what would be deleted
    python -m scripts.cleanup_batch_folders --dry-run

    # Actually delete files
    python -m scripts.cleanup_batch_folders
"""
import argparse
import logging
import boto3
import os
from dotenv import load_dotenv

from app.services.batch_cleanup_service import BatchCleanupService
from app.services.batch_s3_manager import BatchS3Manager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description='Clean up S3 folders from completed Nova batch jobs'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be deleted without actually deleting'
    )
    args = parser.parse_args()

    # Initialize services
    s3_client = boto3.client('s3', region_name=os.getenv('AWS_REGION', 'us-east-1'))
    bucket_name = os.getenv('S3_BUCKET_NAME')
    batch_s3_manager = BatchS3Manager(s3_client, bucket_name)
    cleanup_service = BatchCleanupService(batch_s3_manager)

    # Run cleanup
    if args.dry_run:
        print("=" * 60)
        print("DRY RUN - No files will be deleted")
        print("=" * 60)

    stats = cleanup_service.cleanup_completed_batch_jobs(dry_run=args.dry_run)

    # Report results
    print()
    print("=" * 60)
    print("CLEANUP SUMMARY")
    print("=" * 60)
    print(f"Jobs processed:   {stats['jobs_processed']}")
    print(f"Jobs cleaned:     {stats['jobs_cleaned']}")
    print(f"Objects deleted:  {stats['objects_deleted']}")
    print(f"Space freed:      {stats['bytes_freed'] / 1024 / 1024:.2f} MB")

    if stats['errors']:
        print()
        print("ERRORS:")
        for error in stats['errors']:
            print(f"  - {error}")

    print("=" * 60)


if __name__ == '__main__':
    main()
```

---

### Step 9: Update Result Fetching for Multi-Job Batches

**File**: `app/services/nova_service.py`

Modify the `fetch_batch_results()` method to handle the new folder structure:

Find the existing `fetch_batch_results()` method and update it to accept an optional `s3_folder` parameter:

```python
def fetch_batch_results(
    self,
    batch_job_arn: str,
    s3_folder: str = None
) -> Dict[str, Any]:
    """
    Fetch results from a completed batch job.

    Args:
        batch_job_arn: The batch job ARN
        s3_folder: Optional S3 folder for new multi-job structure.
                   If provided, looks for results in nova/batch/output/{s3_folder}/

    Returns:
        Dict with results and stats
    """
    # Determine output location
    if s3_folder:
        # New multi-job structure: output is in nova/batch/output/{s3_folder}/
        output_prefix = f"nova/batch/output/{s3_folder}/"
    else:
        # Legacy: get output location from job response
        job_response = self.bedrock.get_model_invocation_job(
            jobIdentifier=batch_job_arn
        )
        output_uri = job_response['outputDataConfig']['s3OutputDataConfig']['s3Uri']
        output_prefix = output_uri.replace(f"s3://{self.bucket_name}/", "")

    # Rest of existing fetch logic remains unchanged...
    # Continue with listing objects in output_prefix and parsing results
```

---

## Migration & Rollout Plan

### Phase 1: Deploy New Code (No Breaking Changes)

1. Create new utility files:
   - `app/utils/filename_sanitizer.py`
   - `app/services/batch_splitter_service.py`
   - `app/services/batch_s3_manager.py`

2. Add database columns (nullable, backward compatible):
   ```sql
   ALTER TABLE bedrock_batch_jobs ADD COLUMN parent_batch_id TEXT;
   ALTER TABLE bedrock_batch_jobs ADD COLUMN chunk_index INTEGER;
   ALTER TABLE bedrock_batch_jobs ADD COLUMN total_chunks INTEGER;
   ALTER TABLE bedrock_batch_jobs ADD COLUMN s3_folder TEXT;
   ALTER TABLE bedrock_batch_jobs ADD COLUMN cleanup_completed_at TIMESTAMP;
   ```

3. Add new methods to `nova_service.py` without modifying existing ones

4. Deploy and verify existing functionality still works

### Phase 2: Switch Batch Submission

1. Remove URL encoding from `_build_s3_uri()`
2. Update batch submission route to use new multi-chunk logic
3. Test with small batch (5-10 files with special characters)
4. Test with large batch (200+ files to verify splitting)

### Phase 3: Process Failed Files

1. Run script to process the 35 previously failed files
2. Verify results are correctly stored
3. Clean up temporary S3 files

### Phase 4: Enable Automatic Cleanup

1. Deploy cleanup script
2. Set up scheduled task (optional) or run manually after batch completions

---

## Testing Checklist

### Unit Tests
- [ ] Filename sanitizer handles all special character cases
- [ ] Batch splitter correctly splits by count limit (150)
- [ ] Batch splitter correctly splits by size limit (4.5GB)
- [ ] S3 manager copies files correctly
- [ ] S3 manager cleans up folders completely

### Integration Tests
- [ ] Submit small batch with clean filenames - succeeds
- [ ] Submit small batch with special character filenames - succeeds (with new code)
- [ ] Submit batch of 200 files - splits into 2 chunks
- [ ] Submit batch over 5GB - splits correctly
- [ ] Results are correctly fetched and distributed
- [ ] Cleanup removes all temporary files

### Manual Verification
- [ ] Process the 35 failed files successfully
- [ ] Verify S3 folder structure is correct
- [ ] Verify cleanup removes files after processing
- [ ] Verify original proxy files in `proxy_video/` are NOT deleted

---

## Summary of Changes

### New Files to Create
| File | Purpose |
|------|---------|
| `app/utils/filename_sanitizer.py` | Sanitize filenames for S3 |
| `app/services/batch_splitter_service.py` | Split batches by count/size |
| `app/services/batch_s3_manager.py` | Manage S3 copy/cleanup operations |
| `scripts/cleanup_batch_folders.py` | CLI for manual cleanup |
| `tests/test_filename_sanitizer.py` | Unit tests |
| `tests/test_batch_splitter.py` | Unit tests |

### Files to Modify
| File | Changes |
|------|---------|
| `app/services/nova_service.py` | Remove URL encoding, add multi-chunk method |
| `app/services/batch_cleanup_service.py` | Add folder cleanup for new structure |
| `app/routes/file_management/batch.py` | Multi-job submission logic |
| `app/database/batch_jobs.py` | New columns and query functions |

### Database Changes
| Change | Description |
|--------|-------------|
| `parent_batch_id` | Groups related batch jobs |
| `chunk_index` | Position in multi-chunk batch |
| `total_chunks` | Total chunks in parent batch |
| `s3_folder` | Isolated folder for this job |
| `cleanup_completed_at` | Timestamp when S3 was cleaned |
