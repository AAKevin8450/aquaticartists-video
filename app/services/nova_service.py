"""
AWS Nova video analysis service using Amazon Bedrock.
Provides intelligent video comprehension including summaries, chapters, and element identification.
Supports automatic chunking for long videos exceeding model context windows.
"""
import os
import json
import boto3
import time
import logging
import re
from botocore.config import Config
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional, List, Tuple, Callable
from functools import wraps, lru_cache
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
    COMBINED_ANALYSIS_TYPES = ['summary', 'chapters', 'elements', 'waterfall_classification']

    # Model configurations with pricing and token limits
    MODEL_CONFIG = {
        'lite': {
            'id': 'amazon.nova-2-lite-v1:0',
            'inference_profile_id': 'us.amazon.nova-2-lite-v1:0',
            'name': 'Nova 2 Lite',
            'context_tokens': 300000,
            'max_video_minutes': 30,
            'price_input_per_1k': 0.00033,
            'price_output_per_1k': 0.00275,
            'best_for': 'General video understanding (recommended)',
            'supports_batch': True
        },
        'pro': {
            'id': 'us.amazon.nova-pro-v1:0',
            'name': 'Nova Pro',
            'context_tokens': 300000,
            'max_video_minutes': 30,
            'price_input_per_1k': 0.0008,
            'price_output_per_1k': 0.0032,
            'best_for': 'Complex reasoning, detailed analysis',
            'supports_batch': True
        },
        'premier': {
            'id': 'us.amazon.nova-premier-v1:0',
            'name': 'Nova Premier',
            'context_tokens': 1000000,
            'max_video_minutes': 90,
            'price_input_per_1k': 0.0025,
            'price_output_per_1k': 0.0125,
            'best_for': 'Enterprise critical analysis',
            'supports_batch': True
        }
    }

    def __init__(self, bucket_name: str, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        """Initialize Nova video service."""
        self.bucket_name = bucket_name
        self.region = region

        # Initialize Bedrock Runtime client with extended timeouts for large video processing
        # Nova can take 2-5+ minutes for large videos, default 60s timeout is insufficient
        bedrock_config = Config(
            read_timeout=600,      # 10 minutes for read operations
            connect_timeout=60,    # 60 seconds for initial connection
            retries={'max_attempts': 3, 'mode': 'standard'}
        )

        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('bedrock-runtime', config=bedrock_config, **session_kwargs)
        try:
            self.batch_client = boto3.client('bedrock', **session_kwargs)
        except Exception as e:
            logger.warning(f"Bedrock batch client unavailable: {e}")
            self.batch_client = None
        self.s3_client = boto3.client('s3', **session_kwargs)

        # Initialize chunker and aggregator for long video support
        from app.services.video_chunker import VideoChunker
        from app.services.nova_aggregator import NovaAggregator

        self.chunker = VideoChunker(
            bucket_name=bucket_name,
            region=region,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key
        )

        self.aggregator = NovaAggregator(
            region=region,
            aws_access_key=aws_access_key,
            aws_secret_key=aws_secret_key
        )

        logger.info(f"NovaVideoService initialized for bucket: {bucket_name}, region: {region}")

    @staticmethod
    def normalize_file_context(filename: Optional[str], file_path: Optional[str]) -> Dict[str, Any]:
        """
        Return normalized tokens and path segments for prompting/search.
        """
        if not filename and not file_path:
            return {}

        def tokenize(text: str) -> List[str]:
            if not text:
                return []
            # Split on common separators
            tokens = re.split(r'[_\-\.\s\\/]', text)
            # Split camelCase
            tokens = [re.sub(r'([a-z])([A-Z])', r'\1 \2', t).split() for t in tokens]
            # Flatten list
            tokens = [item for sublist in tokens for item in (sublist if isinstance(sublist, list) else [sublist])]
            # Clean and filter
            return [t.lower().strip() for t in tokens if t and t.strip()]

        filename_tokens = tokenize(filename)
        path_segments = tokenize(file_path)

        # Extract potential project/customer identifiers (heuristic)
        project_like_tokens = []
        for t in path_segments:
            # Look for job numbers or project names (often numeric or mixed)
            if re.search(r'\d', t) or len(t) > 4:
                project_like_tokens.append(t)

        # Filter out common noise words
        noise = {'video', 'videos', 'mp4', 'mov', 'final', 'v1', 'v2', 'copy', 'edited', 'training', 'products'}
        filename_tokens = [t for t in filename_tokens if t not in noise]
        path_segments = [t for t in path_segments if t not in noise]

        return {
            "filename_tokens": filename_tokens,
            "path_segments": path_segments,
            "project_like_tokens": project_like_tokens,
            "raw_filename": filename,
            "raw_path": file_path
        }

    @staticmethod
    def _build_contextual_prompt(
        base_prompt: str,
        filename: str = None,
        file_path: str = None,
        transcript_summary: str = None,
        filename_tokens: List[str] = None,
        path_segments: List[str] = None,
        project_like_tokens: List[str] = None,
        duration_seconds: float = None
    ) -> str:
        """
        Wrap base prompt with contextual metadata section.
        """
        context_parts = []
        if filename:
            context_parts.append(f"Filename: {filename}")
        if file_path:
            context_parts.append(f"File Path: {file_path}")
        if filename_tokens:
            context_parts.append(f"Filename Tokens: {', '.join(filename_tokens)}")
        if path_segments:
            context_parts.append(f"Path Segments: {', '.join(path_segments)}")
        if project_like_tokens:
            context_parts.append(f"Project/Customer Tokens: {', '.join(project_like_tokens)}")
        if duration_seconds:
            context_parts.append(f"Duration: {duration_seconds} seconds")

        context_section = ""
        if context_parts:
            context_section = "=== FILE CONTEXT ===\n" + "\n".join(context_parts) + "\n\n"

        transcript_section = ""
        if transcript_summary:
            transcript_section = f"=== TRANSCRIPT SUMMARY ===\n{transcript_summary}\n\n"

        instructions = ""
        if context_section or transcript_section:
            instructions = """=== ANALYSIS INSTRUCTIONS ===
Use the above context to guide your analysis:

CRITICAL EXTRACTION TARGETS:
1. RECORDING DATE: Look for dates in file path (YYYYMMDD, YYYY-MM-DD, MM-DD-YYYY patterns),
   filename, transcript ("today is...", "recorded on..."), or visual timestamps. Output as YYYY-MM-DD.
2. CUSTOMER/PROJECT NAME (synonymous): Check file path (first segment after drive is often customer),
   filename (e.g., "Smith_Pool.mp4"), and transcript (property owner names, client mentions).
3. LOCATION: Check path for city/state names, transcript for "here in [city]" or address mentions,
   and video for visible addresses, business signs, or license plates indicating state.

GENERAL GUIDANCE:
- The filename often contains important keywords about the content
- The file path may indicate project/category organization
- The transcript summary provides spoken content context
- Path segments can encode customer/project/location; treat as hints with source attribution
- Always include the source (path, filename, transcript, visual) for extracted entities
- Do not invent details; use null when evidence is missing

"""

        return f"{context_section}{transcript_section}{instructions}{base_prompt}"

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_waterfall_assets() -> Tuple[str, Dict[str, Any]]:
        """Load waterfall classification decision tree and spec from docs."""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        decision_path = os.path.join(base_dir, 'docs', 'Nova_Waterfall_Classification_Decision_Tree.md')
        spec_path = os.path.join(base_dir, 'docs', 'Nova_Waterfall_Classification_Spec.json')

        with open(decision_path, 'r', encoding='utf-8') as decision_file:
            decision_tree = decision_file.read()

        with open(spec_path, 'r', encoding='utf-8') as spec_file:
            spec = json.load(spec_file)

        return decision_tree, spec

    def _get_waterfall_classification_prompt(self) -> str:
        """Build prompt for waterfall classification using the decision tree and spec."""
        decision_tree, spec = self._load_waterfall_assets()
        spec_json = json.dumps(spec, indent=2, ensure_ascii=True)

        return f"""You are classifying waterfall content in a video segment.

This is a SEQUENTIAL 4-step classification process. You must:
1. First determine FAMILY (boulder vs no boulder, then kit vs custom)
2. Then determine FUNCTIONAL TYPE (slide and/or grotto detection)
3. Then determine TIER LEVEL (size/complexity assessment)
4. Finally determine SUB-TYPE (water path analysis)

Each step builds on the previous. Follow this order strictly as defined in the spec.

EVIDENCE PRIORITY (use this ranking):
1. Visual evidence (HIGHEST) - geometry, materials, physical features
2. Spoken narration / on-screen text - brand names, product terms
3. Context / environment cues - equipment, scale, jobsite complexity

Always prefer visual evidence over narration when they conflict.

CRITICAL: The family taxonomy uses a 4-type model:
- Custom Natural Stone (boulders + custom)
- Custom Formal (no boulders + custom)
- Genesis Natural (boulders + kit)
- Genesis Formal (no boulders + kit)

First split on BOULDER PRESENCE, then split on KIT vs CUSTOM.

CONFIDENCE & UNKNOWN POLICY:
- Minimum confidence threshold: 0.70 (0.75 for functional_type)
- If confidence is below threshold, set dimension to "Unknown" with reason
- DO NOT GUESS - use "Unknown" when evidence is insufficient
- Overall confidence = minimum of all four dimension confidences
- If there is no waterfall content, set all four dimensions to "Unknown" and explain why

Additionally, for search optimization, provide:

1. "search_tags": Array of 5-10 lowercase keywords for semantic search
   - Include product family, type, tier variations
   - Include content type (tutorial, review, demo, etc.)

2. "product_keywords": Array of exact product names/model numbers mentioned
   - Extract from filename and visual elements
   - Include brand names and SKUs if visible

3. "content_type": One of:
   - "product_overview" - General product introduction
   - "installation_tutorial" - How to install
   - "building_demonstration" - Waterfall construction
   - "troubleshooting" - Problem solving
   - "comparison" - Product comparison
   - "review" - Product review/opinion

4. "skill_level": One of:
   - "beginner", "intermediate", "advanced", "professional"

5. "building_techniques": Array of specific techniques shown:
   - E.g., ["bracket mounting", "silicone sealing", "pump sizing"]

OUTPUT REQUIREMENTS:
Return ONLY raw JSON - no markdown code fences, no explanatory text.
Output must be valid JSON parseable by json.loads().
All four dimensions are required: family, tier_level, functional_type, sub_type.
Include confidence object with per-dimension scores and overall score.
Include evidence array with specific cues observed.
Include unknown_reasons object for any "Unknown" classifications.
Include the search optimization fields defined above.

Decision Tree:
{decision_tree}

Spec:
{spec_json}
"""

    def _resolve_analysis_types(self, analysis_types: Optional[List[str]]) -> Tuple[List[str], List[str], bool]:
        """Normalize analysis types, handling the combined option."""
        requested = analysis_types or ['summary']
        use_combined = 'combined' in requested
        if use_combined:
            return ['combined'], list(self.COMBINED_ANALYSIS_TYPES), True
        return requested, requested, False

    def _validate_waterfall_classification(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize waterfall classification output against the spec."""
        _, spec = self._load_waterfall_assets()
        taxonomy = spec.get('taxonomy', {})
        required_fields = spec.get('output_format', {}).get('required_fields', [])

        data = payload if isinstance(payload, dict) else {}
        allowed = {
            'family': set(taxonomy.get('family', {}).get('allowed', [])),
            'tier_level': set(taxonomy.get('tier_level', {}).get('allowed', [])),
            'functional_type': set(taxonomy.get('functional_type', {}).get('allowed', [])),
            'sub_type': set(taxonomy.get('sub_type', {}).get('allowed', []))
        }

        unknown_reasons = data.get('unknown_reasons')
        if not isinstance(unknown_reasons, dict):
            unknown_reasons = {}

        for field, allowed_values in allowed.items():
            value = data.get(field)
            if value not in allowed_values:
                data[field] = 'Unknown'
                if not unknown_reasons.get(field):
                    unknown_reasons[field] = 'Invalid or missing value in model output.'

        normalized_unknown_reasons = {}
        for field in allowed.keys():
            if data.get(field) == 'Unknown':
                normalized_unknown_reasons[field] = unknown_reasons.get(
                    field, 'Insufficient evidence to determine classification.'
                )

        confidence = data.get('confidence')
        if not isinstance(confidence, dict):
            confidence = {}

        dim_confidences = {}
        for field in allowed.keys():
            raw_value = confidence.get(field)
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = 0.0 if data.get(field) == 'Unknown' else 0.5
            value = max(0.0, min(1.0, value))
            dim_confidences[field] = value

        overall = confidence.get('overall')
        try:
            overall_value = float(overall)
        except (TypeError, ValueError):
            overall_value = min(dim_confidences.values()) if dim_confidences else 0.0
        overall_value = max(0.0, min(1.0, overall_value))

        dim_confidences['overall'] = overall_value
        data['confidence'] = dim_confidences

        evidence = data.get('evidence')
        if not isinstance(evidence, list):
            evidence = [evidence] if evidence else []
        data['evidence'] = [str(item).strip() for item in evidence if str(item).strip()]

        data['unknown_reasons'] = normalized_unknown_reasons

        for field in required_fields:
            if field not in data:
                if field == 'confidence':
                    data['confidence'] = dim_confidences
                elif field == 'evidence':
                    data['evidence'] = []
                elif field == 'unknown_reasons':
                    data['unknown_reasons'] = normalized_unknown_reasons
                else:
                    data[field] = data.get(field, 'Unknown')

        return data

    def get_model_config(self, model: str) -> Dict[str, Any]:
        """Get configuration for a specific Nova model."""
        if model not in self.MODEL_CONFIG:
            raise NovaError(f"Invalid model: {model}. Choose from: {list(self.MODEL_CONFIG.keys())}")
        return self.MODEL_CONFIG[model]

    def estimate_cost(self, model: str, video_duration_seconds: float,
                      estimated_output_tokens: int = 2048,
                      batch_mode: bool = False) -> Dict[str, Any]:
        """
        Estimate cost for video analysis.

        Args:
            model: Nova model name ('lite', 'pro', 'premier')
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
        if batch_mode:
            input_cost *= 0.5
            output_cost *= 0.5
            total_cost *= 0.5

        return {
            'model': model,
            'video_duration_seconds': video_duration_seconds,
            'estimated_input_tokens': estimated_input_tokens,
            'estimated_output_tokens': estimated_output_tokens,
            'input_cost_usd': round(input_cost, 4),
            'output_cost_usd': round(output_cost, 4),
            'total_cost_usd': round(total_cost, 4),
            'price_per_1k_input': config['price_input_per_1k'],
            'price_per_1k_output': config['price_output_per_1k'],
            'batch_discount_applied': bool(batch_mode)
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

        runtime_model_id = config.get('inference_profile_id', config['id'])
        logger.info(f"Nova model ids - runtime: {runtime_model_id}, reporting: {config['id']}")

        # Prepare request body using Converse API
        request_body = {
            "modelId": runtime_model_id,
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
            logger.error(
                "Nova invocation failed (model=%s runtime_model_id=%s s3_key=%s): %s",
                model,
                runtime_model_id,
                s3_key,
                str(e)
            )
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
            'runtime_model_id': runtime_model_id,
            'stop_reason': response.get('stopReason', 'end_turn'),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'raw_response': json.dumps(response, default=str)  # Store full API response for debugging/auditing
        }

    def _build_batch_records(self, s3_key: str, analysis_types: List[str],
                             options: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build batch records for Nova batch inference."""
        requested_types, _, _ = self._resolve_analysis_types(analysis_types)
        s3_uri = self._build_s3_uri(s3_key)
        video_format = self._get_video_format(s3_key)

        depth = options.get('summary_depth', 'standard')
        language = options.get('language', 'auto')

        prompt_map = {
            'summary': self._get_summary_prompt(depth, language),
            'chapters': self._get_chapters_prompt(),
            'elements': self._get_elements_prompt(),
            'waterfall_classification': self._get_waterfall_classification_prompt(),
            'combined': self._get_combined_prompt(depth, language)
        }

        inference_map = {
            'summary': {'maxTokens': 2048, 'temperature': 0.3, 'topP': 0.9},
            'chapters': {'maxTokens': 4096, 'temperature': 0.2, 'topP': 0.9},
            'elements': {'maxTokens': 4096, 'temperature': 0.3, 'topP': 0.9},
            'waterfall_classification': {'maxTokens': 2048, 'temperature': 0.2, 'topP': 0.9},
            'combined': {'maxTokens': 4096, 'temperature': 0.2, 'topP': 0.9}
        }

        records = []
        for analysis_type in requested_types:
            prompt = prompt_map.get(analysis_type)
            if not prompt:
                continue
            records.append({
                'recordId': analysis_type,
                'modelInput': {
                    'messages': [
                        {
                            'role': 'user',
                            'content': [
                                {
                                    'video': {
                                        'format': video_format,
                                        'source': {
                                            's3Location': {'uri': s3_uri}
                                        }
                                    }
                                },
                                {'text': prompt}
                            ]
                        }
                    ],
                    'inferenceConfig': inference_map[analysis_type]
                }
            })

        if not records:
            raise NovaError("No valid analysis types provided for batch processing.")

        return records

    def _normalize_s3_prefix(self, prefix: str) -> str:
        """Normalize S3 prefix by trimming separators."""
        return prefix.strip().strip('/')

    def _start_batch_job(self, job_name: str, model_id: str, role_arn: str,
                         input_s3_uri: str, output_s3_uri: str) -> str:
        """Start a Bedrock batch job using the available API."""
        if not self.batch_client:
            raise NovaError("Bedrock batch client not available. Update boto3 to a version that supports batch inference.")
        if hasattr(self.batch_client, 'create_model_invocation_job'):
            response = self.batch_client.create_model_invocation_job(
                jobName=job_name,
                modelId=model_id,
                roleArn=role_arn,
                inputDataConfig={
                    's3InputDataConfig': {'s3Uri': input_s3_uri}
                },
                outputDataConfig={
                    's3OutputDataConfig': {'s3Uri': output_s3_uri}
                }
            )
        elif hasattr(self.batch_client, 'start_batch_inference_job'):
            response = self.batch_client.start_batch_inference_job(
                jobName=job_name,
                modelId=model_id,
                roleArn=role_arn,
                inputDataConfig={
                    's3InputDataConfig': {'s3Uri': input_s3_uri}
                },
                outputDataConfig={
                    's3OutputDataConfig': {'s3Uri': output_s3_uri}
                }
            )
        else:
            raise NovaError("Bedrock batch inference API not available in this boto3 version.")

        return (response.get('jobArn')
                or response.get('jobIdentifier')
                or response.get('batchJobArn')
                or response.get('jobId'))

    def _get_batch_job(self, job_identifier: str) -> Dict[str, Any]:
        """Fetch batch job status from Bedrock."""
        if not self.batch_client:
            raise NovaError("Bedrock batch client not available. Update boto3 to a version that supports batch inference.")
        if hasattr(self.batch_client, 'get_model_invocation_job'):
            try:
                return self.batch_client.get_model_invocation_job(jobIdentifier=job_identifier)
            except TypeError:
                return self.batch_client.get_model_invocation_job(jobId=job_identifier)
        if hasattr(self.batch_client, 'get_batch_inference_job'):
            try:
                return self.batch_client.get_batch_inference_job(batchJobArn=job_identifier)
            except TypeError:
                return self.batch_client.get_batch_inference_job(jobId=job_identifier)
        raise NovaError("Bedrock batch inference API not available in this boto3 version.")

    def _extract_text_from_batch_output(self, output: Dict[str, Any]) -> Optional[str]:
        """Extract text response from batch model output."""
        if not isinstance(output, dict):
            return None
        if 'output' in output and isinstance(output['output'], dict):
            message = output['output'].get('message')
            if message and message.get('content'):
                return message['content'][0].get('text')
        if 'message' in output and isinstance(output['message'], dict):
            content = output['message'].get('content', [])
            if content:
                return content[0].get('text')
        if 'text' in output:
            return output.get('text')
        return None

    def _extract_usage_from_batch_output(self, output: Dict[str, Any]) -> Dict[str, int]:
        """Extract token usage from batch output if present."""
        usage = output.get('usage', {}) if isinstance(output, dict) else {}
        input_tokens = usage.get('inputTokens') or usage.get('input_tokens') or 0
        output_tokens = usage.get('outputTokens') or usage.get('output_tokens') or 0
        total_tokens = usage.get('totalTokens') or usage.get('total_tokens') or (input_tokens + output_tokens)
        return {
            'input_tokens': int(input_tokens or 0),
            'output_tokens': int(output_tokens or 0),
            'total_tokens': int(total_tokens or 0)
        }

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int,
                        batch_mode: bool) -> float:
        """Calculate cost from token usage."""
        config = self.get_model_config(model)
        cost = (input_tokens / 1000) * config['price_input_per_1k'] + (
            output_tokens / 1000) * config['price_output_per_1k']
        if batch_mode:
            cost *= 0.5
        return round(cost, 4)

    @handle_bedrock_errors
    def start_batch_analysis(self, s3_key: str, model: str,
                             analysis_types: List[str],
                             options: Dict[str, Any],
                             role_arn: str,
                             input_prefix: str,
                             output_prefix: str,
                             job_name: str) -> Dict[str, Any]:
        """Submit a Nova batch inference job."""
        if not role_arn:
            raise NovaError("BEDROCK_BATCH_ROLE_ARN is required for batch processing.")

        config = self.get_model_config(model)
        runtime_model_id = config.get('inference_profile_id', config['id'])
        records = self._build_batch_records(s3_key, analysis_types, options)

        input_prefix = self._normalize_s3_prefix(input_prefix)
        output_prefix = self._normalize_s3_prefix(output_prefix)

        input_key = f"{input_prefix}/{job_name}.jsonl"
        output_prefix_key = f"{output_prefix}/{job_name}/"

        jsonl_body = "\n".join(json.dumps(record) for record in records)
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=input_key,
            Body=jsonl_body.encode('utf-8'),
            ContentType='application/json'
        )

        job_arn = self._start_batch_job(
            job_name=job_name,
            model_id=runtime_model_id,
            role_arn=role_arn,
            input_s3_uri=self._build_s3_uri(input_key),
            output_s3_uri=self._build_s3_uri(output_prefix_key)
        )

        return {
            'batch_job_arn': job_arn,
            'batch_input_s3_key': input_key,
            'batch_output_s3_prefix': output_prefix_key
        }

    @handle_bedrock_errors
    def get_batch_job_status(self, batch_job_arn: str) -> Dict[str, Any]:
        """Get current batch job status."""
        response = self._get_batch_job(batch_job_arn)
        status = response.get('status') or response.get('jobStatus') or response.get('batchStatus')
        failure_message = response.get('failureMessage') or response.get('message')
        return {
            'status': status,
            'failure_message': failure_message,
            'raw': response
        }

    def fetch_batch_results(self, s3_prefix: str, model: str,
                            analysis_types: List[str],
                            options: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch and parse batch results from S3."""
        requested_types, effective_types, use_combined = self._resolve_analysis_types(analysis_types)
        results = {
            'model': model,
            'analysis_types': requested_types,
            'options': options,
            'chunked': False,
            'processing_mode': 'batch'
        }

        total_tokens = 0
        total_cost = 0.0

        prefix = self._normalize_s3_prefix(s3_prefix)
        response = self.s3_client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)
        objects = response.get('Contents', [])

        lines = []
        for obj in objects:
            key = obj['Key']
            if not key.endswith('.jsonl'):
                continue
            obj_data = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            body = obj_data['Body'].read().decode('utf-8')
            lines.extend([line for line in body.splitlines() if line.strip()])

        record_outputs = {}
        for line in lines:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            record_id = payload.get('recordId') or payload.get('record_id')
            output = payload.get('modelOutput') or payload.get('output') or payload.get('response') or {}
            record_outputs[record_id] = output

        if use_combined and 'combined' in record_outputs:
            output = record_outputs['combined']
            combined_text = self._extract_text_from_batch_output(output) or '{}'
            usage = self._extract_usage_from_batch_output(output)
            try:
                parsed = self._parse_json_response(combined_text)
            except NovaError as e:
                logger.error(f"Failed to parse combined batch response: {e}")
                logger.error(f"S3 prefix: {s3_prefix}")
                parsed = {}

            combined_results = self._build_combined_results(
                payload=parsed,
                model=model,
                options=options,
                usage=usage,
                cost_usd=self._calculate_cost(model, usage['input_tokens'], usage['output_tokens'], True),
                processing_time_seconds=0.0,
                generated_at=datetime.utcnow().isoformat()
            )

            results.update(combined_results)
            total_tokens += usage['total_tokens']
            total_cost += combined_results['totals']['cost_total_usd']

            return results

        if 'summary' in requested_types and 'summary' in record_outputs:
            output = record_outputs['summary']
            summary_text = self._extract_text_from_batch_output(output) or ''
            usage = self._extract_usage_from_batch_output(output)
            summary_result = {
                'text': summary_text,
                'depth': options.get('summary_depth', 'standard'),
                'language': options.get('language', 'auto'),
                'word_count': len(summary_text.split()),
                'generated_at': datetime.utcnow().isoformat(),
                'model_used': model,
                'model_id': self.get_model_config(model)['id'],
                'tokens_used': usage['total_tokens'],
                'tokens_input': usage['input_tokens'],
                'tokens_output': usage['output_tokens'],
                'cost_usd': self._calculate_cost(model, usage['input_tokens'], usage['output_tokens'], True),
                'processing_time_seconds': 0.0
            }
            results['summary'] = summary_result
            total_tokens += usage['total_tokens']
            total_cost += summary_result['cost_usd']

        if 'chapters' in requested_types and 'chapters' in record_outputs:
            output = record_outputs['chapters']
            chapters_text = self._extract_text_from_batch_output(output) or '{}'
            try:
                parsed = self._parse_json_response(chapters_text)
            except NovaError as e:
                logger.error(f"Failed to parse chapters batch response: {e}")
                logger.error(f"S3 prefix: {s3_prefix}")
                parsed = {}
            chapters = parsed.get('chapters', [])

            # Enrich chapters using core function (ensures consistency with realtime)
            for chapter in chapters:
                self._enrich_chapter_data(chapter)

            usage = self._extract_usage_from_batch_output(output)
            chapters_result = {
                'chapters': chapters,
                'total_chapters': len(chapters),
                'detection_method': 'semantic_segmentation',
                'model_used': model,
                'model_id': self.get_model_config(model)['id'],
                'tokens_used': usage['total_tokens'],
                'cost_usd': self._calculate_cost(model, usage['input_tokens'], usage['output_tokens'], True),
                'processing_time_seconds': 0.0,
                'generated_at': datetime.utcnow().isoformat()
            }
            results['chapters'] = chapters_result
            total_tokens += usage['total_tokens']
            total_cost += chapters_result['cost_usd']

        if 'elements' in requested_types and 'elements' in record_outputs:
            output = record_outputs['elements']
            elements_text = self._extract_text_from_batch_output(output) or '{}'
            try:
                parsed = self._parse_json_response(elements_text)
            except NovaError as e:
                logger.error(f"Failed to parse elements batch response: {e}")
                logger.error(f"S3 prefix: {s3_prefix}")
                parsed = {}

            equipment = parsed.get('equipment', [])
            topics_discussed = parsed.get('topics_discussed', [])
            people = parsed.get('people', {'max_count': 0, 'multiple_speakers': False})
            speakers = parsed.get('speakers', [])

            # Enrich data using core functions (ensures consistency with realtime)
            for equip in equipment:
                self._enrich_equipment_data(equip)

            for topic in topics_discussed:
                self._enrich_topic_data(topic)

            for speaker in speakers:
                self._enrich_speaker_data(speaker)

            # Update people metadata
            if speakers and not people.get('multiple_speakers'):
                people['multiple_speakers'] = len(speakers) > 1

            # Build topics summary using core function
            topics_summary = self._build_topics_summary(topics_discussed)

            usage = self._extract_usage_from_batch_output(output)
            elements_result = {
                'equipment': equipment,
                'topics_discussed': topics_discussed,
                'topics_summary': topics_summary,
                'people': people,
                'speakers': speakers,
                'model_used': model,
                'model_id': self.get_model_config(model)['id'],
                'tokens_used': usage['total_tokens'],
                'cost_usd': self._calculate_cost(model, usage['input_tokens'], usage['output_tokens'], True),
                'processing_time_seconds': 0.0,
                'generated_at': datetime.utcnow().isoformat()
            }
            results['elements'] = elements_result
            total_tokens += usage['total_tokens']
            total_cost += elements_result['cost_usd']

        if 'waterfall_classification' in requested_types and 'waterfall_classification' in record_outputs:
            output = record_outputs['waterfall_classification']
            classification_text = self._extract_text_from_batch_output(output) or '{}'
            try:
                parsed = self._parse_json_response(classification_text)
            except NovaError as e:
                logger.error(f"Failed to parse waterfall_classification batch response: {e}")
                logger.error(f"S3 prefix: {s3_prefix}")
                logger.error(f"Raw batch output: {output}")
                parsed = {}

            classification = self._validate_waterfall_classification(parsed)
            usage = self._extract_usage_from_batch_output(output)

            classification_result = {
                **classification,
                'model_used': model,
                'model_id': self.get_model_config(model)['id'],
                'tokens_used': usage['total_tokens'],
                'cost_usd': self._calculate_cost(model, usage['input_tokens'], usage['output_tokens'], True),
                'processing_time_seconds': 0.0,
                'generated_at': datetime.utcnow().isoformat()
            }

            results['waterfall_classification'] = classification_result
            total_tokens += usage['total_tokens']
            total_cost += classification_result['cost_usd']

        results['totals'] = {
            'tokens_total': total_tokens,
            'cost_total_usd': round(total_cost, 4),
            'processing_time_seconds': 0.0,
            'analyses_completed': len([t for t in requested_types if t in results])
        }

        if results['totals']['cost_total_usd'] == 0 and options.get('estimated_duration_seconds'):
            estimate = self.estimate_cost(
                model=model,
                video_duration_seconds=options['estimated_duration_seconds'],
                batch_mode=True
            )
            results['totals']['cost_total_usd'] = round(
                estimate['total_cost_usd'] * len(requested_types), 4
            )

        return results

    def _sanitize_json_string(self, text: str) -> str:
        """
        Attempt to sanitize malformed JSON by fixing common issues.

        This is a fallback method for when Nova returns JSON with unescaped characters.

        Args:
            text: Potentially malformed JSON string

        Returns:
            Sanitized JSON string
        """
        import re

        # Remove any markdown code fences
        cleaned = text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)

        # Try to detect and fix common JSON issues:
        # 1. Unescaped quotes within string values
        # 2. Unescaped newlines within strings
        # 3. Unescaped backslashes

        # Note: This is a best-effort approach and may not work for all cases
        # The proper solution is for Nova to return valid JSON

        return cleaned

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """
        Parse JSON from Nova response, handling markdown code fences.

        This is a core parsing function used by both realtime and batch processing
        to ensure consistent JSON extraction across all analysis modes.

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
            error_msg = str(e)

            # Check if this is an unterminated string error (often caused by max_tokens truncation)
            if 'Unterminated string' in error_msg:
                logger.warning(f"Detected unterminated string in Nova response at position {e.pos}, attempting to fix...")

                # Try to fix by closing the string and completing the JSON
                fixed = cleaned

                # Find the position of the error and add a closing quote
                if e.pos and e.pos > 0 and e.pos <= len(fixed):
                    # Add closing quote at error position
                    fixed = fixed[:e.pos] + '"' + fixed[e.pos:]

                    # Count open braces/brackets to determine what needs closing
                    open_braces = fixed.count('{') - fixed.count('}')
                    open_brackets = fixed.count('[') - fixed.count(']')

                    # Add missing closing characters
                    fixed = fixed + (']' * open_brackets) + ('}' * open_braces)

                    try:
                        logger.info("Successfully fixed unterminated string in Nova response")
                        return json.loads(fixed)
                    except json.JSONDecodeError as e2:
                        logger.error(f"Still failed to parse after fixing unterminated string: {e2}")
                        # Fall through to other fixes below

            # Check if this is an invalid escape sequence error
            if 'Invalid \\escape' in error_msg or 'Invalid escape' in error_msg or 'bad escape' in error_msg:
                logger.warning(f"Detected invalid escape sequences in Nova response, attempting to fix...")

                # Fix invalid escape sequences by escaping backslashes that aren't part of valid JSON escapes
                # Valid JSON escape sequences: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
                # Replace any \ that's not followed by these valid characters with \\

                # First, temporarily replace valid escape sequences with placeholders
                replacements = {
                    '\\"': '\x00QUOTE\x00',
                    '\\\\': '\x00BACKSLASH\x00',
                    '\\/': '\x00SLASH\x00',
                    '\\b': '\x00BACKSPACE\x00',
                    '\\f': '\x00FORMFEED\x00',
                    '\\n': '\x00NEWLINE\x00',
                    '\\r': '\x00RETURN\x00',
                    '\\t': '\x00TAB\x00'
                }

                fixed = cleaned
                for old, new in replacements.items():
                    fixed = fixed.replace(old, new)

                # Also handle Unicode escapes \uXXXX
                # Use a safe placeholder that doesn't contain problematic escape sequences
                fixed = re.sub(r'\\u([0-9a-fA-F]{4})', '\x00UNICODE\\1\x00', fixed)

                # Now escape any remaining backslashes (these are the invalid ones)
                fixed = fixed.replace('\\', '\\\\')

                # Restore the valid escape sequences
                for old, new in replacements.items():
                    fixed = fixed.replace(new, old)

                # Restore Unicode escapes
                fixed = re.sub('\x00UNICODE([0-9a-fA-F]{4})\x00', r'\\u\1', fixed)

                try:
                    logger.info("Successfully fixed invalid escape sequences in Nova response")
                    return json.loads(fixed)
                except json.JSONDecodeError as e2:
                    logger.error(f"Still failed to parse after fixing escape sequences: {e2}")
                    # Fall through to original error handling below

            # Enhanced error logging for debugging
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Error at line {e.lineno}, column {e.colno}, position {e.pos}")
            logger.error(f"First 1000 chars of response: {text[:1000]}")

            # Log the problematic area around the error position
            if e.pos and e.pos > 0:
                start = max(0, e.pos - 100)
                end = min(len(cleaned), e.pos + 100)
                logger.error(f"Context around error (pos {e.pos}): ...{cleaned[start:end]}...")

            # Log last 500 chars to check if response was truncated
            logger.error(f"Last 500 chars of response: {text[-500:]}")

            raise NovaError(f"Failed to parse Nova response as JSON: {e}")

    def _parse_timecode_to_seconds(self, timecode: str) -> int:
        """Parse MM:SS or HH:MM:SS timecode into seconds."""
        if not timecode:
            return 0

        import re

        cleaned = re.sub(r'[^0-9:]', '', str(timecode).strip())
        if not cleaned:
            return 0

        parts = cleaned.split(':')
        try:
            if len(parts) == 3:
                hours, minutes, seconds = parts
            elif len(parts) == 2:
                hours = 0
                minutes, seconds = parts
            elif len(parts) == 1:
                hours = 0
                minutes = 0
                seconds = parts[0]
            else:
                return 0

            return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
        except ValueError:
            return 0

    def _ensure_list(self, value: Any) -> List[str]:
        """Normalize value into a list of strings."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if isinstance(value, str):
            return [value]
        return [str(value)]

    def _parse_time_range(self, time_range: str) -> Optional[Dict[str, Any]]:
        """Parse a time range string into structured fields."""
        if not time_range:
            return None

        import re

        parts = re.split(r'\s*-\s*', str(time_range).strip())
        if len(parts) == 2:
            start_time, end_time = parts
        else:
            start_time = parts[0]
            end_time = parts[0]

        start_seconds = self._parse_timecode_to_seconds(start_time)
        end_seconds = self._parse_timecode_to_seconds(end_time)
        if end_seconds < start_seconds:
            end_seconds = start_seconds

        return {
            'start_time': start_time.strip(),
            'end_time': end_time.strip(),
            'start_seconds': start_seconds,
            'end_seconds': end_seconds,
            'duration_seconds': end_seconds - start_seconds
        }

    def _parse_time_ranges(self, time_ranges: List[str]) -> List[Dict[str, Any]]:
        """Parse a list of time range strings into structured fields."""
        parsed = []
        for time_range in time_ranges:
            parsed_range = self._parse_time_range(time_range)
            if parsed_range:
                parsed.append(parsed_range)
        return parsed

    def _enrich_chapter_data(self, chapter: Dict[str, Any]) -> None:
        """
        Enrich chapter dictionary with computed fields (in-place modification).

        Core enrichment logic used by both realtime and batch processing
        to ensure consistent chapter data across all processing modes.

        Args:
            chapter: Chapter dictionary to enrich
        """
        start_time = chapter.get('start_time')
        end_time = chapter.get('end_time')

        start_seconds = self._parse_timecode_to_seconds(start_time)
        end_seconds = self._parse_timecode_to_seconds(end_time)
        if end_seconds < start_seconds:
            end_seconds = start_seconds

        chapter['start_seconds'] = start_seconds
        chapter['end_seconds'] = end_seconds
        duration_seconds = end_seconds - start_seconds
        chapter['duration_seconds'] = duration_seconds

        # Format duration as HH:MM:SS or MM:SS
        if duration_seconds >= 3600:
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            seconds = duration_seconds % 60
            chapter['duration'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            chapter['duration'] = f"{duration_seconds // 60:02d}:{duration_seconds % 60:02d}"

    def _enrich_equipment_data(self, equip: Dict[str, Any]) -> None:
        """
        Enrich equipment dictionary with computed fields (in-place modification).

        Core enrichment logic used by both realtime and batch processing
        to ensure consistent equipment data across all processing modes.

        Args:
            equip: Equipment dictionary to enrich
        """
        equip['time_ranges'] = self._ensure_list(equip.get('time_ranges'))
        equip['time_ranges_parsed'] = self._parse_time_ranges(equip['time_ranges'])
        equip['discussed'] = bool(equip.get('discussed', False))
        if 'confidence' not in equip:
            equip['confidence'] = 'medium'

    def _enrich_topic_data(self, topic: Dict[str, Any]) -> None:
        """
        Enrich topic dictionary with computed fields (in-place modification).

        Core enrichment logic used by both realtime and batch processing
        to ensure consistent topic data across all processing modes.

        Args:
            topic: Topic dictionary to enrich
        """
        topic['time_ranges'] = self._ensure_list(topic.get('time_ranges'))
        topic['time_ranges_parsed'] = self._parse_time_ranges(topic['time_ranges'])
        if 'importance' not in topic:
            topic['importance'] = 'medium'
        topic['keywords'] = self._ensure_list(topic.get('keywords'))

    def _enrich_speaker_data(self, speaker: Dict[str, Any]) -> None:
        """
        Enrich speaker dictionary with computed fields (in-place modification).

        Core enrichment logic used by both realtime and batch processing
        to ensure consistent speaker data across all processing modes.

        Args:
            speaker: Speaker dictionary to enrich
        """
        speaker['time_ranges'] = self._ensure_list(speaker.get('time_ranges'))
        speaker['time_ranges_parsed'] = self._parse_time_ranges(speaker['time_ranges'])
        if 'speaking_percentage' in speaker:
            try:
                speaker['speaking_percentage'] = float(speaker['speaking_percentage'])
            except (TypeError, ValueError):
                speaker['speaking_percentage'] = None

    def _build_topics_summary(self, topics_discussed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build topics summary from topics_discussed list.

        Core summarization logic used by both realtime and batch processing.

        Args:
            topics_discussed: List of topic dictionaries

        Returns:
            List of topic summary dictionaries
        """
        topics_summary = []
        for topic in topics_discussed:
            name = str(topic.get('topic', '')).strip()
            if not name:
                continue
            topics_summary.append({
                'topic': name,
                'importance': topic.get('importance', 'medium'),
                'time_range_count': len(topic.get('time_ranges', []))
            })
        return topics_summary

    def _get_summary_prompt(self, depth: str, language: str) -> str:
        """Build summary prompt based on depth and language."""
        prompts = {
            'brief': """Analyze this video and provide a concise 2-3 sentence summary of the main content and purpose.
Focus on what the video is about and its primary objective. Keep it under 50 words.""",

            'standard': """Analyze this video and provide a comprehensive summary including:

1. **Context & Purpose**: What this video is about, who it's for, and why it was created
2. **Main Topics**: The primary subjects and themes covered
3. **Key Information**: Important details, facts, techniques, or concepts presented
4. **Visual & Audio Elements**: Notable demonstrations, equipment shown, or speaker insights
5. **Conclusions & Takeaways**: What viewers should understand or be able to do after watching

Provide 2-4 well-structured paragraphs (approximately 250-350 words).
Be specific and informative, including:
- Concrete examples and specific details mentioned in the video
- Any technical specifications, product names, or model numbers discussed
- Key visual demonstrations or on-screen elements
- Relevant timestamps for important sections (e.g., "At 2:15, the presenter demonstrates...")""",

            'detailed': """Analyze this video thoroughly and provide an in-depth, comprehensive summary including:

1. **Opening & Context** (1 paragraph):
   - How the video begins and sets context
   - Purpose, intended audience, and production quality
   - Overall tone and presentation style

2. **Content Structure & Flow** (1-2 paragraphs):
   - How the video is organized and structured
   - Major sections and transitions
   - Teaching or presentation methodology used

3. **Detailed Topic Coverage** (2-3 paragraphs):
   - In-depth exploration of each major topic covered
   - Specific techniques, processes, or concepts explained
   - Technical details, specifications, measurements, or data presented
   - Equipment, tools, materials, or products featured (include brands/models)
   - Step-by-step procedures or demonstrations shown

4. **Visual & Audio Analysis** (1 paragraph):
   - Key visual elements: camera angles, graphics, on-screen text, product shots
   - Speaker delivery: expertise level, presentation quality, multiple speakers
   - Audio quality and background elements

5. **Critical Moments & Highlights** (1 paragraph):
   - Most important or impactful moments with timestamps
   - Before/after comparisons or results shown
   - Common mistakes addressed or troubleshooting tips
   - Expert tips, pro advice, or insider knowledge shared

6. **Conclusions & Practical Applications** (1 paragraph):
   - Final recommendations or summary by presenter
   - Practical takeaways viewers can implement
   - Resources mentioned or next steps suggested
   - Overall value and who would benefit most

Provide 6-10 comprehensive, detailed paragraphs (approximately 600-900 words).
Include specific examples, exact quotes when relevant, and precise timestamps for key moments.
Extract and mention any: product names, model numbers, measurements, prices, locations, dates, or technical specifications."""
        }

        prompt = prompts.get(depth, prompts['standard'])

        if language != 'auto':
            prompt += f"\n\nProvide the summary in {language} language."

        return prompt

    def _get_chapters_prompt(self) -> str:
        """Build chapter detection prompt."""
        return """Analyze this video and identify logical chapters based on content transitions and topic changes.

For each chapter, provide:
1. **Title** (3-8 words): A clear, descriptive title that indicates the chapter's content
2. **Start timestamp** (MM:SS or HH:MM:SS if duration exceeds 59:59)
3. **End timestamp** (MM:SS or HH:MM:SS if duration exceeds 59:59)
4. **Brief summary** (2-3 sentences): A concise overview of what happens in that chapter
5. **Detailed summary** (4-8 sentences, 100-200 words): An in-depth description including:
   - Specific actions, demonstrations, or explanations shown
   - Technical details, measurements, or specifications mentioned
   - Equipment, tools, or products featured
   - Key visual elements or camera shots
   - Important dialogue, quotes, or narrator insights
   - Techniques or processes demonstrated step-by-step
   - Any problems solved or challenges addressed
6. **Key points** (3-8 bullet points): Specific, actionable takeaways from this chapter

Return the results in this exact JSON format:
{
  "chapters": [
    {
      "index": 1,
      "title": "...",
      "start_time": "00:00",
      "end_time": "03:00",
      "summary": "Brief 2-3 sentence overview...",
      "detailed_summary": "Comprehensive 4-8 sentence description with specific details, timestamps, technical information, and exact procedures shown...",
      "key_points": ["Specific point 1", "Specific point 2", "Specific point 3"]
    }
  ]
}

IMPORTANT GUIDELINES:
- Create chapters that align with natural content divisions (topic changes, scene transitions, new demonstrations)
- Aim for chapters between 1-10 minutes in length where appropriate
- Use contiguous chapters that cover the full video without gaps when possible
- In detailed_summary, be VERY specific: mention exact products, measurements, techniques, and visual demonstrations
- Include relevant sub-timestamps within detailed_summary (e.g., "At 2:35 within this section, the installer...")
- Make key_points concrete and actionable, not vague generalizations
- Extract any product names, model numbers, measurements, or technical specifications mentioned

Do NOT include any text outside the JSON structure."""

    def _get_elements_prompt(self) -> str:
        """Build element identification prompt."""
        return """Analyze this video and identify:

1. EQUIPMENT/TOOLS: All visible equipment, tools, and devices
   For each item provide:
   - Name (be specific - include brand/model if visible)
   - Category (e.g., photography, computing, tools, kitchen, sports)
   - Time ranges when visible (format: "MM:SS-MM:SS" or single "MM:SS" if brief)
   - Whether it's discussed in audio (true/false)
   - Confidence (high/medium/low)

2. TOPICS DISCUSSED: Main topics covered in the video
   For each topic provide:
   - Topic name
   - Time ranges when discussed (format: "MM:SS-MM:SS")
   - Importance (high/medium/low)
   - Brief description (1 sentence)
   - Keywords (3-8 terms)

3. PEOPLE: Count of people visible
   - Maximum number of people visible at once
   - Whether there are multiple speakers (true/false)

4. SPEAKER DIARIZATION: If multiple speakers are present
   For each speaker provide:
   - Speaker ID (e.g., Speaker_1, Speaker_2)
   - Role (host, instructor, interviewer, guest, etc.)
   - Approximate time ranges when speaking
   - Speaking percentage (0-100)

Return as JSON:
{
  "equipment": [
    {
      "name": "...",
      "category": "...",
      "time_ranges": ["MM:SS-MM:SS"],
      "discussed": true,
      "confidence": "high"
    }
  ],
  "topics_discussed": [
    {
      "topic": "...",
      "time_ranges": ["MM:SS-MM:SS"],
      "importance": "high",
      "description": "...",
      "keywords": ["..."]
    }
  ],
  "people": {
    "max_count": 2,
    "multiple_speakers": true
  },
  "speakers": [
    {
      "speaker_id": "Speaker_1",
      "role": "...",
      "time_ranges": ["MM:SS-MM:SS"],
      "speaking_percentage": 65
    }
  ]
}

Do NOT include any text outside the JSON structure."""

    def _get_combined_prompt(self, depth: str, language: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Build combined analysis prompt for a single-pass output."""
        language_note = ""
        if language != 'auto':
            language_note = f"Provide the summary in {language} language."

        depth_guidance = {
            'brief': "2-3 sentences, under 50 words.",
            'standard': "2-4 paragraphs, 250-350 words, include context, main topics, key information, visual elements, and conclusions with specific details.",
            'detailed': ("6-10 paragraphs, 600-900 words, include opening context, content structure, detailed topic coverage, "
                         "visual/audio analysis, critical moments with timestamps, and practical applications.")
        }
        summary_guidance = depth_guidance.get(depth, depth_guidance['standard'])

        decision_tree, spec = self._load_waterfall_assets()
        spec_json = json.dumps(spec, indent=2, ensure_ascii=True)

        # Extract context fields if available
        context = context or {}
        filename = context.get('filename')
        file_path = context.get('file_path')
        transcript_summary = context.get('transcript_summary')
        filename_tokens = context.get('filename_tokens')
        path_segments = context.get('path_segments')
        project_like_tokens = context.get('project_like_tokens')
        duration_seconds = context.get('duration_seconds')

        base_prompt = f"""Analyze this video and return a SINGLE JSON object that includes all five analysis sections.

SUMMARY REQUIREMENTS:
- {summary_guidance}
- {language_note or "Use the video's original language."}
- Incorporate insights from the transcript summary if provided.
- Include specific examples, product names, technical details, and timestamps.

CHAPTERS REQUIREMENTS:
- Title (3-8 words): Clear, descriptive chapter title
- Start/end timecodes (MM:SS or HH:MM:SS)
- Summary (2-3 sentences): Brief overview of the chapter
- Detailed_summary (4-8 sentences, 100-200 words): In-depth description including:
  * Specific actions, demonstrations, or explanations shown
  * Technical details, measurements, specifications mentioned
  * Equipment, tools, or products featured with brands/models
  * Key visual elements and camera work
  * Important dialogue or narrator insights
  * Step-by-step techniques or processes
  * Problems solved or challenges addressed
- Key_points (3-8 bullets): Specific, actionable takeaways
- Chapters should be contiguous and cover the full video without gaps when possible.

ELEMENTS REQUIREMENTS:
- Equipment: name, category, time_ranges, discussed (true/false), confidence (high/medium/low).
- Topics: topic, time_ranges, importance (high/medium/low), description, keywords (3-8 terms).
- People: max_count, multiple_speakers.
- Speakers: speaker_id, role, time_ranges, speaking_percentage.

WATERFALL CLASSIFICATION REQUIREMENTS:
- Follow the sequential 4-step decision process and spec below.
- Apply Unknown rules and include confidence, evidence, unknown_reasons.
- Additionally provide "search_tags", "product_keywords", "content_type", "skill_level", "building_techniques".

SEARCH METADATA REQUIREMENTS (for discovery):

DATE EXTRACTION (CRITICAL - check all sources):
- File path patterns: YYYYMMDD, YYYY-MM-DD, YYYY_MM_DD, MM-DD-YYYY, MMDDYYYY
- Example paths: "2024-03-15_Johnson_Pool" → recording_date: "2024-03-15"
- Transcript mentions: "today is March 15th", "recorded on...", "this was filmed in June 2023"
- Visual cues: on-screen dates, timestamps, calendars visible
- If multiple dates found, prefer the one closest to the start of the path/filename
- Output as ISO format YYYY-MM-DD when possible; null if no date evidence

CUSTOMER/PROJECT NAME EXTRACTION (these are synonymous - check all sources):
- File path: First segment after drive/root is often the customer (e.g., "E:/videos/Johnson Family/..." → "Johnson Family")
- Filename: May contain customer name directly (e.g., "Smith_Pool_Installation.mp4" → "Smith")
- Transcript: "Mr. Johnson", "the Smith residence", "working for ABC Pools", "this is the Martinez project"
- Look for proper nouns, family names, business names in any source
- Cross-reference across sources for higher confidence (e.g., path says "Johnson" and transcript mentions "Mr. Johnson")

LOCATION EXTRACTION (multiple sources):
- File path: city names, state abbreviations, addresses in folder names
- Transcript: "here in Phoenix", "this property in Scottsdale", "Arizona weather", street addresses
- Visual: address signs, business names with locations, license plates (state), landmarks
- Normalize to: city, state_region, country when identifiable

STANDARD FIELDS:
- Project: customer_name, project_name, job_number/project_code, project_type.
- Location: site_name, city, state_region, country, address_fragment.
- Water feature: family, type_keywords, style_keywords.
- Content: content_type, skill_level.
- Entities: list of ALL extracted entities (dates, names, locations, etc.) with sources and evidence.
- Keywords: 8-20 lowercase search tags.

OUTPUT JSON SCHEMA (return ONLY JSON, no markdown):
{{
  "summary": {{
    "text": "...",
    "depth": "{depth}",
    "language": "{language}"
  }},
  "chapters": {{
    "chapters": [
      {{
        "index": 1,
        "title": "...",
        "start_time": "00:00",
        "end_time": "03:00",
        "summary": "Brief 2-3 sentence overview...",
        "detailed_summary": "Comprehensive 4-8 sentence description with specific details, technical information, exact procedures, and visual demonstrations shown...",
        "key_points": ["Specific point 1", "Specific point 2", "Specific point 3"]
      }}
    ]
  }},
  "elements": {{
    "equipment": [
      {{
        "name": "...",
        "category": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "discussed": true,
        "confidence": "high"
      }}
    ],
    "topics_discussed": [
      {{
        "topic": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "importance": "high",
        "description": "...",
        "keywords": ["..."]
      }}
    ],
    "people": {{
      "max_count": 2,
      "multiple_speakers": true
    }},
    "speakers": [
      {{
        "speaker_id": "Speaker_1",
        "role": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "speaking_percentage": 65
      }}
    ]
  }},
  "waterfall_classification": {{
    "family": "...",
    "tier_level": "...",
    "functional_type": "...",
    "sub_type": "...",
    "confidence": {{
      "family": 0.0,
      "tier_level": 0.0,
      "functional_type": 0.0,
      "sub_type": 0.0,
      "overall": 0.0
    }},
    "evidence": ["..."],
    "unknown_reasons": {{}},
    "search_tags": ["..."],
    "product_keywords": ["..."],
    "content_type": "...",
    "skill_level": "...",
    "building_techniques": ["..."]
  }},
  "search_metadata": {{
    "recording_date": {{
      "date": "YYYY-MM-DD or null if unknown",
      "date_source": "path|filename|transcript|visual|unknown",
      "confidence": 0.0,
      "raw_date_string": "original text/pattern found (e.g., '20240315', 'March 15th')"
    }},
    "project": {{
      "customer_name": "extracted customer/client/project name or null (synonymous with project_name)",
      "project_name": "same as customer_name - use identical value",
      "name_source": "path|filename|transcript|unknown",
      "name_confidence": 0.0,
      "project_code": "any project/job code found or null",
      "job_number": "any job number found or null",
      "project_type": "..."
    }},
    "location": {{
      "site_name": "...",
      "city": "extracted city name or null",
      "state_region": "extracted state/region or null",
      "country": "USA if US state detected, else extracted or null",
      "address_fragment": "any partial address found",
      "location_source": "path|transcript|visual|unknown",
      "location_confidence": 0.0
    }},
    "water_feature": {{
      "family": "...",
      "type_keywords": ["..."],
      "style_keywords": ["..."]
    }},
    "content": {{
      "content_type": "...",
      "skill_level": "..."
    }},
    "entities": [
      {{
        "type": "...",
        "value": "...",
        "normalized": "...",
        "sources": ["filename", "path", "transcript_summary"],
        "evidence": "...",
        "confidence": 0.0
      }}
    ],
    "keywords": ["..."]
  }}
}}

Decision Tree:
{decision_tree}

Spec:
{spec_json}
"""
        return self._build_contextual_prompt(
            base_prompt,
            filename=filename,
            file_path=file_path,
            transcript_summary=transcript_summary,
            filename_tokens=filename_tokens,
            path_segments=path_segments,
            project_like_tokens=project_like_tokens,
            duration_seconds=duration_seconds
        )

    def _build_combined_results(
        self,
        payload: Dict[str, Any],
        model: str,
        options: Dict[str, Any],
        usage: Dict[str, int],
        cost_usd: float,
        processing_time_seconds: float,
        generated_at: str
    ) -> Dict[str, Any]:
        """Build normalized results from a combined analysis payload."""
        summary_payload = payload.get('summary') or {}
        if isinstance(summary_payload, str):
            summary_text = summary_payload
        else:
            summary_text = summary_payload.get('text') or ''

        chapters_payload = payload.get('chapters') or {}
        if isinstance(chapters_payload, list):
            chapters = chapters_payload
        else:
            chapters = chapters_payload.get('chapters', []) if isinstance(chapters_payload, dict) else []

        for chapter in chapters:
            self._enrich_chapter_data(chapter)

        elements_payload = payload.get('elements') or {}
        if not isinstance(elements_payload, dict):
            elements_payload = {}

        equipment = elements_payload.get('equipment', [])
        topics_discussed = elements_payload.get('topics_discussed', [])
        people = elements_payload.get('people', {'max_count': 0, 'multiple_speakers': False})
        speakers = elements_payload.get('speakers', [])

        for equip in equipment:
            self._enrich_equipment_data(equip)

        for topic in topics_discussed:
            self._enrich_topic_data(topic)

        for speaker in speakers:
            self._enrich_speaker_data(speaker)

        if speakers and not people.get('multiple_speakers'):
            people['multiple_speakers'] = len(speakers) > 1

        topics_summary = self._build_topics_summary(topics_discussed)

        classification_payload = payload.get('waterfall_classification') or {}
        classification = self._validate_waterfall_classification(
            classification_payload if isinstance(classification_payload, dict) else {}
        )

        search_metadata_payload = payload.get('search_metadata') or {}
        if not isinstance(search_metadata_payload, dict):
            search_metadata_payload = {}

        summary_result = {
            'text': summary_text,
            'depth': options.get('summary_depth', summary_payload.get('depth') or 'standard'),
            'language': options.get('language', summary_payload.get('language') or 'auto'),
            'word_count': len(summary_text.split()) if summary_text else 0,
            'generated_at': generated_at,
            'model_used': model,
            'model_id': self.get_model_config(model)['id'],
            'tokens_used': usage['total_tokens'],
            'tokens_input': usage['input_tokens'],
            'tokens_output': usage['output_tokens'],
            'cost_usd': cost_usd,
            'processing_time_seconds': processing_time_seconds
        }

        chapters_result = {
            'chapters': chapters,
            'total_chapters': len(chapters),
            'detection_method': 'semantic_segmentation',
            'model_used': model,
            'model_id': self.get_model_config(model)['id'],
            'tokens_used': 0,
            'cost_usd': 0,
            'processing_time_seconds': processing_time_seconds,
            'generated_at': generated_at
        }

        elements_result = {
            'equipment': equipment,
            'topics_discussed': topics_discussed,
            'topics_summary': topics_summary,
            'people': people,
            'speakers': speakers,
            'model_used': model,
            'model_id': self.get_model_config(model)['id'],
            'tokens_used': 0,
            'cost_usd': 0,
            'processing_time_seconds': processing_time_seconds,
            'generated_at': generated_at
        }

        classification_result = {
            **classification,
            'model_used': model,
            'model_id': self.get_model_config(model)['id'],
            'tokens_used': 0,
            'cost_usd': 0,
            'processing_time_seconds': processing_time_seconds,
            'generated_at': generated_at
        }

        return {
            'summary': summary_result,
            'chapters': chapters_result,
            'elements': elements_result,
            'waterfall_classification': classification_result,
            'search_metadata': search_metadata_payload,
            'totals': {
                'tokens_total': usage['total_tokens'],
                'cost_total_usd': round(cost_usd, 4),
                'processing_time_seconds': round(processing_time_seconds, 2),
                'analyses_completed': len(self.COMBINED_ANALYSIS_TYPES)
            }
        }

    # ============================================================================
    # ANALYSIS METHODS
    # ============================================================================

    def generate_summary(self, s3_key: str, model: str = 'lite',
                        depth: str = 'standard', language: str = 'auto') -> Dict[str, Any]:
        """
        Generate video summary using Nova.

        Args:
            s3_key: S3 key of the video
            model: Nova model ('lite', 'pro', 'premier')
            depth: Summary depth ('brief', 'standard', 'detailed')
            language: Target language ('auto' or ISO code like 'en', 'es')

        Returns:
            Dict with summary text and metadata
        """
        prompt = self._get_summary_prompt(depth, language)

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
        prompt = self._get_chapters_prompt()

        # Invoke Nova
        response = self._invoke_nova(s3_key, model, prompt, max_tokens=4096, temperature=0.2)

        # Parse JSON response
        parsed = self._parse_json_response(response['text'])
        chapters = parsed.get('chapters', [])

        # Enrich chapters with computed fields using core function
        for chapter in chapters:
            self._enrich_chapter_data(chapter)

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
        prompt = self._get_elements_prompt()

        # Invoke Nova
        response = self._invoke_nova(s3_key, model, prompt, max_tokens=4096, temperature=0.3)

        # Parse JSON response
        parsed = self._parse_json_response(response['text'])

        equipment = parsed.get('equipment', [])
        topics_discussed = parsed.get('topics_discussed', [])
        people = parsed.get('people', {'max_count': 0, 'multiple_speakers': False})
        speakers = parsed.get('speakers', [])

        # Enrich data using core functions
        for equip in equipment:
            self._enrich_equipment_data(equip)

        for topic in topics_discussed:
            self._enrich_topic_data(topic)

        for speaker in speakers:
            self._enrich_speaker_data(speaker)

        # Update people metadata
        if speakers and not people.get('multiple_speakers'):
            people['multiple_speakers'] = len(speakers) > 1

        # Build topics summary using core function
        topics_summary = self._build_topics_summary(topics_discussed)

        # Build result
        elements_result = {
            'equipment': equipment,
            'topics_discussed': topics_discussed,
            'topics_summary': topics_summary,
            'people': people,
            'speakers': speakers,
            'model_used': model,
            'model_id': response['model_id'],
            'tokens_used': response['tokens_total'],
            'cost_usd': response['cost_total_usd'],
            'processing_time_seconds': response['processing_time_seconds'],
            'generated_at': response['timestamp']
        }

        return elements_result

    def classify_waterfall(self, s3_key: str, model: str = 'lite') -> Dict[str, Any]:
        """
        Classify waterfall features in a video using Nova.

        Args:
            s3_key: S3 key of the video
            model: Nova model ('lite', 'pro', 'premier')

        Returns:
            Dict with waterfall classification and metadata
        """
        prompt = self._get_waterfall_classification_prompt()
        response = self._invoke_nova(s3_key, model, prompt, max_tokens=2048, temperature=0.2)

        parsed = self._parse_json_response(response['text'])
        classification = self._validate_waterfall_classification(parsed)

        classification_result = {
            **classification,
            'model_used': model,
            'model_id': response['model_id'],
            'tokens_used': response['tokens_total'],
            'cost_usd': response['cost_total_usd'],
            'processing_time_seconds': response['processing_time_seconds'],
            'generated_at': response['timestamp']
        }

        return classification_result

    def analyze_combined(self, s3_key: str, model: str = 'lite',
                         options: Optional[Dict[str, Any]] = None,
                         context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Run a combined Nova analysis in a single call.

        Args:
            s3_key: S3 key of the video
            model: Nova model ('lite', 'pro', 'premier')
            options: Dict with options like {'summary_depth': 'standard', 'language': 'auto'}
            context: Optional dictionary with file context (filename, path, transcript, etc.)

        Returns:
            Dict containing summary, chapters, elements, and waterfall classification
        """
        options = options or {}
        depth = options.get('summary_depth', 'standard')
        language = options.get('language', 'auto')
        prompt = self._get_combined_prompt(depth, language, context=context)

        response = self._invoke_nova(s3_key, model, prompt, max_tokens=4096, temperature=0.2)
        parsed = self._parse_json_response(response['text'])

        usage = {
            'input_tokens': response['tokens_input'],
            'output_tokens': response['tokens_output'],
            'total_tokens': response['tokens_total']
        }

        results = self._build_combined_results(
            payload=parsed,
            model=model,
            options=options,
            usage=usage,
            cost_usd=response['cost_total_usd'],
            processing_time_seconds=response['processing_time_seconds'],
            generated_at=response['timestamp']
        )

        # Add raw response for debugging/auditing (combined analysis uses single API call)
        if 'raw_response' in response:
            results['raw_responses'] = {'combined': response['raw_response']}

        return results

    def analyze_video(self, s3_key: str, model: str = 'lite',
                     analysis_types: List[str] = None,
                     options: Dict[str, Any] = None,
                     context: Dict[str, Any] = None,
                     progress_callback: Optional[Callable[[int, int, str], None]] = None) -> Dict[str, Any]:
        """
        Comprehensive video analysis with multiple analysis types.
        Automatically handles chunking for long videos exceeding model context windows.

        Args:
            s3_key: S3 key of the video
            model: Nova model to use
            analysis_types: List of analysis types: ['summary', 'chapters', 'elements', 'waterfall_classification']
            options: Dict with options like {'summary_depth': 'standard', 'language': 'auto'}
            context: Optional dictionary with file context (filename, path, transcript, etc.)
            progress_callback: Optional callback function(current_chunk, total_chunks, status_message)

        Returns:
            Dict with all requested analyses and combined metadata
        """
        requested_types, effective_types, use_combined = self._resolve_analysis_types(analysis_types)

        if options is None:
            options = {}

        # Get video metadata to determine if chunking is needed
        try:
            metadata = self.chunker.get_video_metadata(s3_key)
            video_duration = metadata['duration_seconds']
        except Exception as e:
            logger.warning(f"Failed to get video metadata, assuming short video: {e}")
            video_duration = 300  # Default to 5 minutes

        # Check if chunking is needed
        if self.chunker.needs_chunking(video_duration, model):
            logger.info(f"Video duration {video_duration}s exceeds model {model} limit, using chunking")
            return self.analyze_video_chunked(
                s3_key=s3_key,
                model=model,
                analysis_types=requested_types,
                effective_analysis_types=effective_types,
                options=options,
                video_duration=video_duration,
                progress_callback=progress_callback
            )

        # Single-chunk analysis (original implementation)
        logger.info(f"Video duration {video_duration}s fits in single request for model {model}")

        results = {
            'model': model,
            'analysis_types': requested_types,
            'options': options,
            's3_key': s3_key,
            'chunked': False,
            'processing_mode': 'realtime'
        }

        total_tokens = 0
        total_cost = 0.0
        total_processing_time = 0.0

        if use_combined:
            combined_results = self.analyze_combined(s3_key, model, options, context=context)
            results.update(combined_results)
            results['analysis_types'] = requested_types
            results['processing_mode'] = 'realtime'
            return results

        # Run requested analyses
        if 'summary' in effective_types:
            depth = options.get('summary_depth', 'standard')
            language = options.get('language', 'auto')
            summary_result = self.generate_summary(s3_key, model, depth, language)
            results['summary'] = summary_result
            total_tokens += summary_result['tokens_used']
            total_cost += summary_result['cost_usd']
            total_processing_time += summary_result['processing_time_seconds']

        if 'chapters' in effective_types:
            chapters_result = self.detect_chapters(s3_key, model)
            results['chapters'] = chapters_result
            total_tokens += chapters_result['tokens_used']
            total_cost += chapters_result['cost_usd']
            total_processing_time += chapters_result['processing_time_seconds']

        if 'elements' in effective_types:
            elements_result = self.identify_elements(s3_key, model)
            results['elements'] = elements_result
            total_tokens += elements_result['tokens_used']
            total_cost += elements_result['cost_usd']
            total_processing_time += elements_result['processing_time_seconds']

        if 'waterfall_classification' in effective_types:
            classification_result = self.classify_waterfall(s3_key, model)
            results['waterfall_classification'] = classification_result
            total_tokens += classification_result['tokens_used']
            total_cost += classification_result['cost_usd']
            total_processing_time += classification_result['processing_time_seconds']

        # Collect raw responses from all analyses for debugging/auditing
        raw_responses = {}
        for analysis_type in ['summary', 'chapters', 'elements', 'waterfall_classification']:
            if analysis_type in results and 'raw_response' in results[analysis_type]:
                raw_responses[analysis_type] = results[analysis_type]['raw_response']

        if raw_responses:
            results['raw_responses'] = raw_responses

        # Add totals
        results['totals'] = {
            'tokens_total': total_tokens,
            'cost_total_usd': round(total_cost, 4),
            'processing_time_seconds': round(total_processing_time, 2),
            'analyses_completed': len([t for t in effective_types if t in results])
        }

        return results

    def analyze_video_chunked(
        self,
        s3_key: str,
        model: str,
        analysis_types: List[str],
        options: Dict[str, Any],
        video_duration: float,
        effective_analysis_types: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Analyze long video using chunking strategy.

        Args:
            s3_key: S3 key of the video
            model: Nova model to use
            analysis_types: List of analysis types
            options: Analysis options
            video_duration: Video duration in seconds
            progress_callback: Optional callback for progress updates

        Returns:
            Dict with aggregated results from all chunks
        """
        effective_types = effective_analysis_types or analysis_types
        logger.info(f"Starting chunked analysis for {s3_key} (duration: {video_duration}s)")

        # Generate chunk boundaries
        chunks = self.chunker.generate_chunk_boundaries(video_duration, model)
        total_chunks = len(chunks)

        logger.info(f"Split video into {total_chunks} chunks")

        if progress_callback:
            progress_callback(0, total_chunks, f"Splitting video into {total_chunks} chunks")

        # Process each chunk
        chunk_results = []
        chunk_s3_keys = []  # Track chunk files for cleanup

        try:
            for i, chunk in enumerate(chunks):
                chunk_index = chunk['index']
                logger.info(f"Processing chunk {chunk_index + 1}/{total_chunks}")

                if progress_callback:
                    progress_callback(
                        chunk_index,
                        total_chunks,
                        f"Processing chunk {chunk_index + 1}/{total_chunks}"
                    )

                # Extract video chunk
                chunk_s3_key = self.chunker.get_chunk_s3_key(s3_key, chunk_index)
                self.chunker.extract_video_segment(
                    s3_key=s3_key,
                    start_time=chunk['overlap_start'],
                    end_time=chunk['overlap_end'],
                    output_s3_key=chunk_s3_key
                )
                chunk_s3_keys.append(chunk_s3_key)

                # Analyze chunk
                chunk_result = self._analyze_chunk(
                    chunk_s3_key=chunk_s3_key,
                    chunk=chunk,
                    chunk_index=chunk_index,
                    total_chunks=total_chunks,
                    model=model,
                    analysis_types=analysis_types,
                    options=options,
                    previous_context=chunk_results[-1] if chunk_results else None
                )

                chunk_results.append(chunk_result)

            # Aggregate results
            if progress_callback:
                progress_callback(total_chunks, total_chunks, "Aggregating results")

            logger.info("Aggregating chunk results")
            aggregated_results = self._aggregate_chunk_results(
                chunk_results=chunk_results,
                model=model,
                analysis_types=effective_types,
                options=options
            )

            # Add metadata
            params = self.chunker.calculate_chunk_parameters(model, video_duration)
            aggregated_results['chunked'] = True
            aggregated_results['chunk_metadata'] = {
                'total_chunks': total_chunks,
                'chunk_duration': params['chunk_duration'],
                'overlap_seconds': params['overlap'],
                'video_duration': video_duration
            }
            aggregated_results['processing_mode'] = 'realtime'
            aggregated_results['analysis_types'] = analysis_types

            # Collect raw responses from all chunks for debugging/auditing
            all_raw_responses = []
            for chunk_idx, chunk_result in enumerate(chunk_results):
                if 'raw_responses' in chunk_result:
                    all_raw_responses.append({
                        'chunk_index': chunk_idx,
                        'chunk_time_range': f"{chunk_result['chunk']['start']:.1f}s - {chunk_result['chunk']['end']:.1f}s",
                        'responses': chunk_result['raw_responses']
                    })

            if all_raw_responses:
                aggregated_results['raw_responses'] = {
                    'chunked': True,
                    'total_chunks': len(all_raw_responses),
                    'chunks': all_raw_responses
                }

            return aggregated_results

        finally:
            # Clean up temporary chunk files
            logger.info(f"Cleaning up {len(chunk_s3_keys)} temporary chunk files")
            for chunk_key in chunk_s3_keys:
                try:
                    self.chunker.delete_chunk(chunk_key)
                except Exception as e:
                    logger.warning(f"Failed to delete chunk {chunk_key}: {e}")

    def _analyze_chunk(
        self,
        chunk_s3_key: str,
        chunk: Dict[str, Any],
        chunk_index: int,
        total_chunks: int,
        model: str,
        analysis_types: List[str],
        options: Dict[str, Any],
        previous_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze a single video chunk with context preservation.

        Args:
            chunk_s3_key: S3 key of the chunk file
            chunk: Chunk metadata dict
            chunk_index: Current chunk index
            total_chunks: Total number of chunks
            model: Nova model
            analysis_types: List of analysis types
            options: Analysis options
            previous_context: Results from previous chunk (for context)

        Returns:
            Dict with chunk analysis results
        """
        result = {
            'chunk': chunk,
            'chunk_index': chunk_index
        }

        # Build context from previous chunk if available
        context_summary = None
        if previous_context and 'summary' in previous_context:
            summary_data = previous_context['summary']
            if isinstance(summary_data, dict):
                context_summary = summary_data.get('text', '')
            else:
                context_summary = str(summary_data)

        # Run analyses on chunk
        if 'combined' in analysis_types:
            result.update(self.analyze_combined(chunk_s3_key, model, options))
            return result

        if 'summary' in analysis_types:
            depth = options.get('summary_depth', 'standard')
            language = options.get('language', 'auto')
            result['summary'] = self.generate_summary(chunk_s3_key, model, depth, language)

        if 'chapters' in analysis_types:
            result['chapters'] = self.detect_chapters(chunk_s3_key, model)

        if 'elements' in analysis_types:
            result['elements'] = self.identify_elements(chunk_s3_key, model)

        if 'waterfall_classification' in analysis_types:
            result['waterfall_classification'] = self.classify_waterfall(chunk_s3_key, model)

        # Collect raw responses from all analyses in this chunk for debugging/auditing
        raw_responses = {}
        for analysis_type in ['summary', 'chapters', 'elements', 'waterfall_classification']:
            if analysis_type in result and isinstance(result[analysis_type], dict):
                if 'raw_response' in result[analysis_type]:
                    raw_responses[analysis_type] = result[analysis_type]['raw_response']

        if raw_responses:
            result['raw_responses'] = raw_responses

        return result

    def _select_best_waterfall_classification(
        self,
        chunk_results: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Select the highest-confidence waterfall classification from chunk results."""
        best_result = None
        best_confidence = -1.0

        for chunk_result in chunk_results:
            classification = chunk_result.get('waterfall_classification')
            if not isinstance(classification, dict):
                continue
            confidence = classification.get('confidence', {})
            overall = confidence.get('overall')
            try:
                overall_value = float(overall)
            except (TypeError, ValueError):
                overall_value = 0.0
            if overall_value > best_confidence:
                best_confidence = overall_value
                best_result = classification

        return best_result

    def _aggregate_chunk_results(
        self,
        chunk_results: List[Dict[str, Any]],
        model: str,
        analysis_types: List[str],
        options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Aggregate results from multiple chunks.

        Args:
            chunk_results: List of chunk result dictionaries
            model: Nova model used
            analysis_types: List of analysis types
            options: Analysis options

        Returns:
            Dict with aggregated results
        """
        results = {
            'model': model,
            'analysis_types': analysis_types,
            'options': options
        }

        total_tokens = 0
        total_cost = 0.0
        total_processing_time = 0.0

        # Calculate totals from chunks
        for cr in chunk_results:
            for key in ['summary', 'chapters', 'elements', 'waterfall_classification']:
                if key in cr:
                    data = cr[key]
                    if isinstance(data, dict):
                        total_tokens += data.get('tokens_used', 0)
                        total_cost += data.get('cost_usd', 0)
                        total_processing_time += data.get('processing_time_seconds', 0)

        # Aggregate each analysis type
        if 'summary' in analysis_types:
            results['summary'] = self.aggregator.aggregate_summaries(chunk_results, model)
            total_tokens += results['summary'].get('tokens_used', 0)

        if 'chapters' in analysis_types:
            # Get overlap from first chunk
            overlap = chunk_results[0]['chunk']['overlap_end'] - chunk_results[0]['chunk']['core_end']
            results['chapters'] = self.aggregator.merge_chapters(chunk_results, overlap)

        if 'elements' in analysis_types:
            results['elements'] = self.aggregator.combine_elements(chunk_results)

        if 'waterfall_classification' in analysis_types:
            classification = self._select_best_waterfall_classification(chunk_results)
            if classification:
                results['waterfall_classification'] = classification

        # Add totals
        results['totals'] = {
            'tokens_total': total_tokens,
            'cost_total_usd': round(total_cost, 4),
            'processing_time_seconds': round(total_processing_time, 2),
            'analyses_completed': len([t for t in analysis_types if t in results])
        }

        return results
