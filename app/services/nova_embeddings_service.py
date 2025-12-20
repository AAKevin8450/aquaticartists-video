"""
AWS Nova Multimodal Embeddings service using Amazon Bedrock.
Generates embeddings for text inputs.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError


class NovaEmbeddingsError(Exception):
    """Nova embeddings errors."""
    pass


class NovaEmbeddingsService:
    """Service for generating Nova embeddings via Bedrock."""

    def __init__(
        self,
        region: str,
        model_id: str,
        aws_access_key: Optional[str] = None,
        aws_secret_key: Optional[str] = None,
        request_format: str = 'input'
    ):
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('bedrock-runtime', **session_kwargs)
        self.model_id = model_id
        self.request_format = request_format

    def _build_request(self, text: str) -> Dict[str, Any]:
        """Build the request payload for the embeddings model."""
        if self.request_format == 'inputText':
            return {'inputText': text}
        return {
            'input': [{'text': text}],
            'embeddingTypes': ['text']
        }

    def _extract_embedding(self, response_body: Dict[str, Any]) -> List[float]:
        """Extract embedding vector from response body."""
        if 'embedding' in response_body:
            return response_body['embedding']
        embeddings = response_body.get('embeddings')
        if isinstance(embeddings, list):
            if embeddings and isinstance(embeddings[0], dict) and 'embedding' in embeddings[0]:
                return embeddings[0]['embedding']
            if embeddings and isinstance(embeddings[0], list):
                return embeddings[0]
        raise NovaEmbeddingsError("Unable to parse embedding from response.")

    def embed_text(self, text: str) -> List[float]:
        """Generate an embedding for a single text input."""
        if not text or not text.strip():
            raise NovaEmbeddingsError("Text input is empty.")

        payload = self._build_request(text.strip())
        try:
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(payload).encode('utf-8'),
                accept='application/json',
                contentType='application/json'
            )
        except ClientError as e:
            raise NovaEmbeddingsError(f"Nova embeddings request failed: {e}")

        raw_body = response.get('body')
        if hasattr(raw_body, 'read'):
            body_str = raw_body.read().decode('utf-8')
        else:
            body_str = raw_body

        try:
            data = json.loads(body_str)
        except json.JSONDecodeError as e:
            raise NovaEmbeddingsError(f"Failed to parse embeddings response: {e}")

        return self._extract_embedding(data)
