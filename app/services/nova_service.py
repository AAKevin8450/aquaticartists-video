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
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional, List, Tuple, Callable
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

        # Initialize Bedrock Runtime client
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('bedrock-runtime', **session_kwargs)
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
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

    def _build_batch_records(self, s3_key: str, analysis_types: List[str],
                             options: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build batch records for Nova batch inference."""
        s3_uri = self._build_s3_uri(s3_key)
        video_format = self._get_video_format(s3_key)

        depth = options.get('summary_depth', 'standard')
        language = options.get('language', 'auto')

        prompt_map = {
            'summary': self._get_summary_prompt(depth, language),
            'chapters': self._get_chapters_prompt(),
            'elements': self._get_elements_prompt()
        }

        inference_map = {
            'summary': {'maxTokens': 2048, 'temperature': 0.3, 'topP': 0.9},
            'chapters': {'maxTokens': 4096, 'temperature': 0.2, 'topP': 0.9},
            'elements': {'maxTokens': 4096, 'temperature': 0.3, 'topP': 0.9}
        }

        records = []
        for analysis_type in analysis_types:
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
        results = {
            'model': model,
            'analysis_types': analysis_types,
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

        if 'summary' in analysis_types and 'summary' in record_outputs:
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

        if 'chapters' in analysis_types and 'chapters' in record_outputs:
            output = record_outputs['chapters']
            chapters_text = self._extract_text_from_batch_output(output) or '{}'
            try:
                parsed = self._parse_json_response(chapters_text)
            except NovaError:
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

        if 'elements' in analysis_types and 'elements' in record_outputs:
            output = record_outputs['elements']
            elements_text = self._extract_text_from_batch_output(output) or '{}'
            try:
                parsed = self._parse_json_response(elements_text)
            except NovaError:
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

        results['totals'] = {
            'tokens_total': total_tokens,
            'cost_total_usd': round(total_cost, 4),
            'processing_time_seconds': 0.0,
            'analyses_completed': len([t for t in analysis_types if t in results])
        }

        if results['totals']['cost_total_usd'] == 0 and options.get('estimated_duration_seconds'):
            estimate = self.estimate_cost(
                model=model,
                video_duration_seconds=options['estimated_duration_seconds'],
                batch_mode=True
            )
            results['totals']['cost_total_usd'] = round(
                estimate['total_cost_usd'] * len(analysis_types), 4
            )

        return results

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
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response text: {text[:500]}")
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

        return prompt

    def _get_chapters_prompt(self) -> str:
        """Build chapter detection prompt."""
        return """Analyze this video and identify logical chapters based on content transitions and topic changes.

For each chapter, provide:
1. A descriptive title (3-8 words) that clearly indicates the chapter's content
2. Start timestamp (MM:SS or HH:MM:SS if duration exceeds 59:59)
3. End timestamp (MM:SS or HH:MM:SS if duration exceeds 59:59)
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
Use contiguous chapters that cover the full video without gaps when possible.
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

    def analyze_video(self, s3_key: str, model: str = 'lite',
                     analysis_types: List[str] = None,
                     options: Dict[str, Any] = None,
                     progress_callback: Optional[Callable[[int, int, str], None]] = None) -> Dict[str, Any]:
        """
        Comprehensive video analysis with multiple analysis types.
        Automatically handles chunking for long videos exceeding model context windows.

        Args:
            s3_key: S3 key of the video
            model: Nova model to use
            analysis_types: List of analysis types: ['summary', 'chapters', 'elements']
            options: Dict with options like {'summary_depth': 'standard', 'language': 'auto'}
            progress_callback: Optional callback function(current_chunk, total_chunks, status_message)

        Returns:
            Dict with all requested analyses and combined metadata
        """
        if analysis_types is None:
            analysis_types = ['summary']

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
                analysis_types=analysis_types,
                options=options,
                video_duration=video_duration,
                progress_callback=progress_callback
            )

        # Single-chunk analysis (original implementation)
        logger.info(f"Video duration {video_duration}s fits in single request for model {model}")

        results = {
            'model': model,
            'analysis_types': analysis_types,
            'options': options,
            's3_key': s3_key,
            'chunked': False,
            'processing_mode': 'realtime'
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

    def analyze_video_chunked(
        self,
        s3_key: str,
        model: str,
        analysis_types: List[str],
        options: Dict[str, Any],
        video_duration: float,
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
                analysis_types=analysis_types,
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
        if 'summary' in analysis_types:
            depth = options.get('summary_depth', 'standard')
            language = options.get('language', 'auto')
            result['summary'] = self.generate_summary(chunk_s3_key, model, depth, language)

        if 'chapters' in analysis_types:
            result['chapters'] = self.detect_chapters(chunk_s3_key, model)

        if 'elements' in analysis_types:
            result['elements'] = self.identify_elements(chunk_s3_key, model)

        return result

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
            for key in ['summary', 'chapters', 'elements']:
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

        # Add totals
        results['totals'] = {
            'tokens_total': total_tokens,
            'cost_total_usd': round(total_cost, 4),
            'processing_time_seconds': round(total_processing_time, 2),
            'analyses_completed': len([t for t in analysis_types if t in results])
        }

        return results
