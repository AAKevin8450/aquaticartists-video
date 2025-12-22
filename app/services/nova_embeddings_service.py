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
