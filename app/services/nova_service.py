"""
AWS Nova video analysis service using Amazon Bedrock.
Provides intelligent video comprehension including summaries, chapters, and element identification.
"""
import os
import json
import boto3
import time
import logging
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional, List, Tuple
from functools import wraps
from datetime import datetime

logger = logging.getLogger(__name__)


class NovaError(Exception):
    """Base exception for Nova errors."""
    pass


def handle_bedrock_errors(func):
    """Decorator to handle AWS Bedrock/Nova errors and convert to user-friendly messages."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            if error_code == 'AccessDeniedException':
                raise NovaError("AWS permission denied. Ensure IAM policy includes bedrock:InvokeModel for Nova models. See docs/NOVA_IAM_SETUP.md")
            elif error_code == 'ModelAccessDeniedException':
                raise NovaError("Nova model access denied. Request model access in Bedrock console. See docs/NOVA_IAM_SETUP.md")
            elif error_code == 'ValidationException':
                raise NovaError(f"Invalid request parameters: {error_msg}")
            elif error_code == 'ThrottlingException':
                raise NovaError("AWS rate limit exceeded. Please try again in a moment.")
            elif error_code == 'ServiceQuotaExceededException':
                raise NovaError("Service quota exceeded. Contact AWS Support to increase limits.")
            elif error_code == 'InvalidS3ObjectException':
                raise NovaError("Video file not found or inaccessible in S3")
            elif error_code == 'ResourceNotFoundException':
                raise NovaError(f"Resource not found: {error_msg}")
            else:
                raise NovaError(f"Bedrock error ({error_code}): {error_msg}")
    return wrapper


class NovaVideoService:
    """Service for AWS Nova video analysis via Amazon Bedrock."""

    # Model configurations with pricing and token limits
    MODEL_CONFIG = {
        'micro': {
            'id': 'us.amazon.nova-micro-v1:0',
            'name': 'Nova Micro',
            'context_tokens': 128000,
            'max_video_minutes': 12,
            'price_input_per_1k': 0.035,
            'price_output_per_1k': 0.14,
            'best_for': 'Quick summaries, batch processing'
        },
        'lite': {
            'id': 'us.amazon.nova-lite-v1:0',
            'name': 'Nova Lite',
            'context_tokens': 300000,
            'max_video_minutes': 30,
            'price_input_per_1k': 0.06,
            'price_output_per_1k': 0.24,
            'best_for': 'General video understanding (recommended)'
        },
        'pro': {
            'id': 'us.amazon.nova-pro-v1:0',
            'name': 'Nova Pro',
            'context_tokens': 300000,
            'max_video_minutes': 30,
            'price_input_per_1k': 0.80,
            'price_output_per_1k': 3.20,
            'best_for': 'Complex reasoning, detailed analysis'
        },
        'premier': {
            'id': 'us.amazon.nova-premier-v1:0',
            'name': 'Nova Premier',
            'context_tokens': 1000000,
            'max_video_minutes': 90,
            'price_input_per_1k': 2.00,  # Estimated
            'price_output_per_1k': 8.00,  # Estimated
            'best_for': 'Enterprise critical analysis'
        }
    }

    def __init__(self, bucket_name: str, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        """Initialize Nova video service."""
        self.bucket_name = bucket_name
        self.region = region

        # Initialize Bedrock Runtime client
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('bedrock-runtime', **session_kwargs)
        self.s3_client = boto3.client('s3', **session_kwargs)

        logger.info(f"NovaVideoService initialized for bucket: {bucket_name}, region: {region}")

    def get_model_config(self, model: str) -> Dict[str, Any]:
        """Get configuration for a specific Nova model."""
        if model not in self.MODEL_CONFIG:
            raise NovaError(f"Invalid model: {model}. Choose from: {list(self.MODEL_CONFIG.keys())}")
        return self.MODEL_CONFIG[model]

    def estimate_cost(self, model: str, video_duration_seconds: float, estimated_output_tokens: int = 2048) -> Dict[str, Any]:
        """
        Estimate cost for video analysis.

        Args:
            model: Nova model name ('micro', 'lite', 'pro', 'premier')
            video_duration_seconds: Video duration in seconds
            estimated_output_tokens: Expected output token count (default: 2048)

        Returns:
            Dict with cost breakdown
        """
        config = self.get_model_config(model)

        # Rough estimation: ~100 tokens per second of video (very approximate)
        # Actual token count depends on frame sampling and audio content
        estimated_input_tokens = int(video_duration_seconds * 100)

        input_cost = (estimated_input_tokens / 1000) * config['price_input_per_1k']
        output_cost = (estimated_output_tokens / 1000) * config['price_output_per_1k']
        total_cost = input_cost + output_cost

        return {
            'model': model,
            'video_duration_seconds': video_duration_seconds,
            'estimated_input_tokens': estimated_input_tokens,
            'estimated_output_tokens': estimated_output_tokens,
            'input_cost_usd': round(input_cost, 4),
            'output_cost_usd': round(output_cost, 4),
            'total_cost_usd': round(total_cost, 4),
            'price_per_1k_input': config['price_input_per_1k'],
            'price_per_1k_output': config['price_output_per_1k']
        }

    def _build_s3_uri(self, s3_key: str) -> str:
        """Build S3 URI from bucket and key."""
        return f"s3://{self.bucket_name}/{s3_key}"

    def _get_video_format(self, s3_key: str) -> str:
        """Extract video format from S3 key."""
        extension = s3_key.split('.')[-1].lower()
        # Map common extensions to formats
        format_map = {
            'mp4': 'mp4',
            'mov': 'mov',
            'avi': 'avi',
            'mkv': 'mkv',
            'webm': 'webm',
            'flv': 'flv',
            'wmv': 'wmv',
            '3gp': '3gp'
        }
        return format_map.get(extension, 'mp4')  # Default to mp4

    @handle_bedrock_errors
    def _invoke_nova(self, s3_key: str, model: str, prompt: str,
                     max_tokens: int = 4096, temperature: float = 0.3) -> Dict[str, Any]:
        """
        Core method to invoke Nova model for video analysis.

        Args:
            s3_key: S3 key of the video
            model: Nova model name
            prompt: Analysis prompt
            max_tokens: Maximum output tokens
            temperature: Model temperature (0.0-1.0)

        Returns:
            Dict containing response text, usage metrics, and metadata
        """
        config = self.get_model_config(model)
        s3_uri = self._build_s3_uri(s3_key)
        video_format = self._get_video_format(s3_key)

        logger.info(f"Invoking Nova {model} for video: {s3_key}")
        logger.info(f"S3 URI: {s3_uri}, Format: {video_format}")

        # Prepare request body using Converse API
        request_body = {
            "modelId": config['id'],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "video": {
                                "format": video_format,
                                "source": {
                                    "s3Location": {
                                        "uri": s3_uri
                                    }
                                }
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
                "topP": 0.9
            }
        }

        # Invoke model
        start_time = time.time()
        try:
            response = self.client.converse(**request_body)
        except Exception as e:
            logger.error(f"Nova invocation failed: {str(e)}")
            raise

        processing_time = time.time() - start_time

        # Parse response
        output_message = response['output']['message']
        result_text = output_message['content'][0]['text']

        # Extract usage metrics
        usage = response['usage']
        input_tokens = usage['inputTokens']
        output_tokens = usage['outputTokens']
        total_tokens = usage['totalTokens']

        # Calculate actual cost
        input_cost = (input_tokens / 1000) * config['price_input_per_1k']
        output_cost = (output_tokens / 1000) * config['price_output_per_1k']
        total_cost = input_cost + output_cost

        logger.info(f"Nova completed in {processing_time:.2f}s. Tokens: {total_tokens} (in: {input_tokens}, out: {output_tokens}), Cost: ${total_cost:.4f}")

        return {
            'text': result_text,
            'tokens_input': input_tokens,
            'tokens_output': output_tokens,
            'tokens_total': total_tokens,
            'cost_input_usd': round(input_cost, 4),
            'cost_output_usd': round(output_cost, 4),
            'cost_total_usd': round(total_cost, 4),
            'processing_time_seconds': round(processing_time, 2),
            'model': model,
            'model_id': config['id'],
            'stop_reason': response.get('stopReason', 'end_turn'),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """
        Parse JSON from Nova response, handling markdown code fences.

        Args:
            text: Response text that may contain JSON

        Returns:
            Parsed JSON object
        """
        import re

        # Remove markdown code fences if present
        cleaned = text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {text[:500]}")
            raise NovaError(f"Failed to parse Nova response as JSON: {e}")

    # ============================================================================
    # ANALYSIS METHODS
    # ============================================================================

    def generate_summary(self, s3_key: str, model: str = 'lite',
                        depth: str = 'standard', language: str = 'auto') -> Dict[str, Any]:
        """
        Generate video summary using Nova.

        Args:
            s3_key: S3 key of the video
            model: Nova model ('micro', 'lite', 'pro', 'premier')
            depth: Summary depth ('brief', 'standard', 'detailed')
            language: Target language ('auto' or ISO code like 'en', 'es')

        Returns:
            Dict with summary text and metadata
        """
        # Build prompt based on depth
        prompts = {
            'brief': """Analyze this video and provide a concise 2-3 sentence summary of the main content and purpose.
Focus on what the video is about and its primary objective. Keep it under 50 words.""",

            'standard': """Analyze this video and provide a comprehensive summary including:
1. Main topic and purpose of the video
2. Key points and important information discussed
3. Notable takeaways or conclusions

Provide the summary in 1-2 well-structured paragraphs (approximately 150 words).
Be specific and informative while remaining concise.""",

            'detailed': """Analyze this video thoroughly and provide a detailed summary including:

1. **Overview**: Context and purpose of the video, intended audience, and overall structure
2. **Main Topics**: Primary themes and subjects covered throughout
3. **Key Points**: Important details, facts, demonstrations, or arguments presented
4. **Notable Events**: Significant moments, transitions, or highlights
5. **Conclusions**: Takeaways, recommendations, or closing thoughts

Provide 3-5 comprehensive paragraphs with rich detail (approximately 400 words).
Include specific examples and timestamps where relevant."""
        }

        prompt = prompts.get(depth, prompts['standard'])

        if language != 'auto':
            prompt += f"\n\nProvide the summary in {language} language."

        # Invoke Nova
        response = self._invoke_nova(s3_key, model, prompt, max_tokens=2048, temperature=0.3)

        # Build result
        summary_result = {
            'text': response['text'],
            'depth': depth,
            'language': language,
            'word_count': len(response['text'].split()),
            'generated_at': response['timestamp'],
            'model_used': model,
            'model_id': response['model_id'],
            'tokens_used': response['tokens_total'],
            'tokens_input': response['tokens_input'],
            'tokens_output': response['tokens_output'],
            'cost_usd': response['cost_total_usd'],
            'processing_time_seconds': response['processing_time_seconds']
        }

        return summary_result

    def detect_chapters(self, s3_key: str, model: str = 'lite') -> Dict[str, Any]:
        """
        Detect logical chapters in video using Nova.

        Args:
            s3_key: S3 key of the video
            model: Nova model ('lite', 'pro', or 'premier' recommended)

        Returns:
            Dict with chapters array and metadata
        """
        prompt = """Analyze this video and identify logical chapters based on content transitions and topic changes.

For each chapter, provide:
1. A descriptive title (3-8 words) that clearly indicates the chapter's content
2. Start timestamp in MM:SS format
3. End timestamp in MM:SS format
4. A brief summary (2-3 sentences) of what happens in that chapter
5. Key points covered (bullet list, 2-5 points)

Return the results in this exact JSON format:
{
  "chapters": [
    {
      "index": 1,
      "title": "...",
      "start_time": "00:00",
      "end_time": "03:00",
      "summary": "...",
      "key_points": ["point1", "point2"]
    }
  ]
}

Create chapters that align with natural content divisions. Aim for chapters between 2-10 minutes in length where appropriate.
Do NOT include any text outside the JSON structure."""

        # Invoke Nova
        response = self._invoke_nova(s3_key, model, prompt, max_tokens=4096, temperature=0.2)

        # Parse JSON response
        parsed = self._parse_json_response(response['text'])
        chapters = parsed.get('chapters', [])

        # Enhance chapters with computed fields
        for chapter in chapters:
            # Convert MM:SS to seconds
            start_parts = chapter['start_time'].split(':')
            end_parts = chapter['end_time'].split(':')

            start_seconds = int(start_parts[0]) * 60 + int(start_parts[1])
            end_seconds = int(end_parts[0]) * 60 + int(end_parts[1])

            chapter['start_seconds'] = start_seconds
            chapter['end_seconds'] = end_seconds
            chapter['duration_seconds'] = end_seconds - start_seconds
            chapter['duration'] = f"{(end_seconds - start_seconds) // 60:02d}:{(end_seconds - start_seconds) % 60:02d}"

        # Build result
        chapters_result = {
            'chapters': chapters,
            'total_chapters': len(chapters),
            'detection_method': 'semantic_segmentation',
            'model_used': model,
            'model_id': response['model_id'],
            'tokens_used': response['tokens_total'],
            'cost_usd': response['cost_total_usd'],
            'processing_time_seconds': response['processing_time_seconds'],
            'generated_at': response['timestamp']
        }

        return chapters_result

    def identify_elements(self, s3_key: str, model: str = 'lite') -> Dict[str, Any]:
        """
        Identify equipment, objects, and topics in video using Nova.

        Args:
            s3_key: S3 key of the video
            model: Nova model ('lite', 'pro', or 'premier' recommended)

        Returns:
            Dict with equipment, topics, and people information
        """
        prompt = """Analyze this video and identify:

1. EQUIPMENT/TOOLS: All visible equipment, tools, and devices
   For each item provide:
   - Name (be specific - include brand/model if visible)
   - Category (e.g., photography, computing, tools, kitchen, sports)
   - Time ranges when visible (format: "MM:SS-MM:SS" or single "MM:SS" if brief)
   - Whether it's discussed in audio (true/false)

2. TOPICS DISCUSSED: Main topics covered in the video
   For each topic provide:
   - Topic name
   - Time ranges when discussed (format: "MM:SS-MM:SS")
   - Importance (high/medium/low)
   - Brief description (1 sentence)

3. PEOPLE: Count of people visible
   - Maximum number of people visible at once
   - Whether there are multiple speakers (true/false)

Return as JSON:
{
  "equipment": [
    {
      "name": "...",
      "category": "...",
      "time_ranges": ["MM:SS-MM:SS"],
      "discussed": true
    }
  ],
  "topics_discussed": [
    {
      "topic": "...",
      "time_ranges": ["MM:SS-MM:SS"],
      "importance": "high",
      "description": "..."
    }
  ],
  "people": {
    "max_count": 2,
    "multiple_speakers": true
  }
}

Do NOT include any text outside the JSON structure."""

        # Invoke Nova
        response = self._invoke_nova(s3_key, model, prompt, max_tokens=4096, temperature=0.3)

        # Parse JSON response
        parsed = self._parse_json_response(response['text'])

        # Build result
        elements_result = {
            'equipment': parsed.get('equipment', []),
            'topics_discussed': parsed.get('topics_discussed', []),
            'people': parsed.get('people', {'max_count': 0, 'multiple_speakers': False}),
            'model_used': model,
            'model_id': response['model_id'],
            'tokens_used': response['tokens_total'],
            'cost_usd': response['cost_total_usd'],
            'processing_time_seconds': response['processing_time_seconds'],
            'generated_at': response['timestamp']
        }

        return elements_result

    def analyze_video(self, s3_key: str, model: str = 'lite',
                     analysis_types: List[str] = None,
                     options: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Comprehensive video analysis with multiple analysis types.

        Args:
            s3_key: S3 key of the video
            model: Nova model to use
            analysis_types: List of analysis types: ['summary', 'chapters', 'elements']
            options: Dict with options like {'summary_depth': 'standard', 'language': 'auto'}

        Returns:
            Dict with all requested analyses and combined metadata
        """
        if analysis_types is None:
            analysis_types = ['summary']

        if options is None:
            options = {}

        results = {
            'model': model,
            'analysis_types': analysis_types,
            'options': options,
            's3_key': s3_key
        }

        total_tokens = 0
        total_cost = 0.0
        total_processing_time = 0.0

        # Run requested analyses
        if 'summary' in analysis_types:
            depth = options.get('summary_depth', 'standard')
            language = options.get('language', 'auto')
            summary_result = self.generate_summary(s3_key, model, depth, language)
            results['summary'] = summary_result
            total_tokens += summary_result['tokens_used']
            total_cost += summary_result['cost_usd']
            total_processing_time += summary_result['processing_time_seconds']

        if 'chapters' in analysis_types:
            chapters_result = self.detect_chapters(s3_key, model)
            results['chapters'] = chapters_result
            total_tokens += chapters_result['tokens_used']
            total_cost += chapters_result['cost_usd']
            total_processing_time += chapters_result['processing_time_seconds']

        if 'elements' in analysis_types:
            elements_result = self.identify_elements(s3_key, model)
            results['elements'] = elements_result
            total_tokens += elements_result['tokens_used']
            total_cost += elements_result['cost_usd']
            total_processing_time += elements_result['processing_time_seconds']

        # Add totals
        results['totals'] = {
            'tokens_total': total_tokens,
            'cost_total_usd': round(total_cost, 4),
            'processing_time_seconds': round(total_processing_time, 2),
            'analyses_completed': len([t for t in analysis_types if t in results])
        }

        return results
