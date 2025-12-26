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
        if not transcript_text or not transcript_text.strip():
            raise NovaTranscriptSummaryError("Transcript text is empty.")

        # Warn if transcript is very long (may exceed context window)
        # Nova 2 Lite supports ~200k tokens, roughly 800k chars
        if len(transcript_text) > 500000:
            logger.warning(f"Transcript is very long ({len(transcript_text)} chars), truncating to 500k chars")
            transcript_text = transcript_text[:500000]

        prompt = (
            "Summarize the following transcript into a concise guide for video analysis.\n"
            f"Constraints:\n"
            f"- Keep the summary under {max_chars} characters.\n"
            "- Use plain text only (no markdown, no bullets, no formatting).\n"
            "- Prioritize: (1) Main subject/topic, (2) Key people/entities, (3) Important events/actions, (4) Locations if mentioned.\n"
            "- If the content is complex, focus on what would help someone understand the video's purpose and content.\n\n"
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

        # Indicate truncation if needed
        was_truncated = False
        if len(summary_text) > max_chars:
            # Truncate at word boundary near limit
            truncate_at = max_chars - 3  # Leave room for "..."
            last_space = summary_text.rfind(' ', 0, truncate_at)
            if last_space > max_chars * 0.9:  # If we can save >90% of content
                summary_text = summary_text[:last_space] + "..."
            else:
                summary_text = summary_text[:truncate_at] + "..."
            was_truncated = True

        usage = response.get('usage', {})
        return {
            'summary': summary_text,
            'tokens_input': usage.get('inputTokens'),
            'tokens_output': usage.get('outputTokens'),
            'tokens_total': usage.get('totalTokens'),
            'was_truncated': was_truncated
        }
