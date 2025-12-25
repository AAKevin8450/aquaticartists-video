"""
Nova transcript summary service using Amazon Bedrock (Nova 2 Lite).
"""
import logging
from typing import Dict, Any

import boto3

logger = logging.getLogger(__name__)


class NovaTranscriptSummaryError(Exception):
    """Base exception for transcript summary errors."""
    pass


class NovaTranscriptSummaryService:
    """Service for summarizing transcript text with Nova 2 Lite."""

    MODEL_ID = 'us.amazon.nova-2-lite-v1:0'

    def __init__(self, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('bedrock-runtime', **session_kwargs)

    def summarize_transcript(self, transcript_text: str, max_chars: int = 1000) -> Dict[str, Any]:
        """Summarize transcript text into a short guide under max_chars characters."""
        if not transcript_text:
            raise NovaTranscriptSummaryError("Transcript text is empty.")

        prompt = (
            "Summarize the following transcript into a concise guide that will help a later video analysis.\n"
            f"Constraints:\n"
            f"- Keep the summary under {max_chars} characters.\n"
            "- Use plain text only (no markdown, no bullets).\n"
            "- Focus on the main subject, key events, and any notable entities or actions.\n\n"
            "Transcript:\n"
            f"{transcript_text}"
        )

        try:
            response = self.client.converse(
                modelId=self.MODEL_ID,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={
                    "maxTokens": 512,
                    "temperature": 0.2,
                    "topP": 0.9
                }
            )
        except Exception as exc:
            logger.error("Transcript summary generation failed: %s", exc)
            raise NovaTranscriptSummaryError(str(exc)) from exc

        summary_text = response['output']['message']['content'][0]['text'].strip()
        summary_text = " ".join(summary_text.split())
        if len(summary_text) > max_chars:
            summary_text = summary_text[:max_chars].rstrip()

        usage = response.get('usage', {})
        return {
            'summary': summary_text,
            'tokens_input': usage.get('inputTokens'),
            'tokens_output': usage.get('outputTokens'),
            'tokens_total': usage.get('totalTokens')
        }
