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
from botocore.config import Config
from typing import Dict, Any, Optional, List, Tuple, Callable, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from app.services.batch_splitter_service import BatchChunk
    from app.services.batch_s3_manager import BatchS3Manager

# Import from submodules - centralized functionality
from app.services.nova.models import (
    MODELS,
    NovaError,
    handle_bedrock_errors,
    get_model_config,
    estimate_cost,
    calculate_cost,
)
from app.services.nova.parsers import (
    NovaParseError,
    sanitize_json_string,
    parse_json_response,
    close_json_structure,
    parse_timecode_to_seconds,
    ensure_list,
    parse_time_range,
    parse_time_ranges,
    load_waterfall_assets,
    validate_waterfall_classification,
)
from app.services.nova.prompts import (
    normalize_file_context,
    build_contextual_prompt,
    get_waterfall_classification_prompt,
    get_summary_prompt,
    get_chapters_prompt,
    get_elements_prompt,
    get_combined_prompt,
)
from app.services.nova.enrichment import (
    enrich_chapter_data,
    enrich_equipment_data,
    enrich_topic_data,
    enrich_speaker_data,
    build_topics_summary,
    build_combined_results,
)

logger = logging.getLogger(__name__)


class NovaVideoService:
    """Service for AWS Nova video analysis via Amazon Bedrock."""
    COMBINED_ANALYSIS_TYPES = ['summary', 'chapters', 'elements', 'waterfall_classification']

    # Reference imported MODELS for backward compatibility
    MODEL_CONFIG = MODELS

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

    # Delegate to imported functions for backward compatibility
    @staticmethod
    def normalize_file_context(filename: Optional[str], file_path: Optional[str]) -> Dict[str, Any]:
        """Return normalized tokens and path segments for prompting/search."""
        return normalize_file_context(filename, file_path)

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
        """Wrap base prompt with contextual metadata section."""
        return build_contextual_prompt(
            base_prompt, filename, file_path, transcript_summary,
            filename_tokens, path_segments, project_like_tokens, duration_seconds
        )

    @staticmethod
    def _load_waterfall_assets() -> Tuple[str, Dict[str, Any]]:
        """Load waterfall classification decision tree and spec from docs."""
        return load_waterfall_assets()

    def _get_waterfall_classification_prompt(self) -> str:
        """Build prompt for waterfall classification using the decision tree and spec."""
        return get_waterfall_classification_prompt()

    def _resolve_analysis_types(self, analysis_types: Optional[List[str]]) -> Tuple[List[str], List[str], bool]:
        """Normalize analysis types, handling the combined option."""
        requested = analysis_types or ['summary']
        use_combined = 'combined' in requested
        if use_combined:
            return ['combined'], list(self.COMBINED_ANALYSIS_TYPES), True
        return requested, requested, False

    def _validate_waterfall_classification(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize waterfall classification output against the spec."""
        return validate_waterfall_classification(payload)

    def get_model_config(self, model: str) -> Dict[str, Any]:
        """Get configuration for a specific Nova model."""
        return get_model_config(model)

    def estimate_cost(self, model: str, video_duration_seconds: float,
                      estimated_output_tokens: int = 2048,
                      batch_mode: bool = False) -> Dict[str, Any]:
        """Estimate cost for video analysis."""
        return estimate_cost(model, video_duration_seconds, estimated_output_tokens, batch_mode)

    def _build_s3_uri(self, s3_key: str) -> str:
        """Build S3 URI from bucket and key.

        Note: URL encoding was removed because Bedrock Batch API cannot handle
        encoded filenames - it looks for the literal encoded key which doesn't exist.
        Instead, we now copy files to sanitized names in isolated batch folders.
        """
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
                             options: Dict[str, Any],
                             record_prefix: Optional[str] = None) -> List[Dict[str, Any]]:
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
            record_id = analysis_type
            if record_prefix:
                record_id = f"{record_prefix}{analysis_type}"
            records.append({
                'recordId': record_id,
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
        return calculate_cost(model, input_tokens, output_tokens, batch_mode)

    @handle_bedrock_errors
    def start_batch_analysis(self, s3_key: str, model: str,
                             analysis_types: List[str],
                             options: Dict[str, Any],
                             role_arn: str,
                             input_prefix: str,
                             output_prefix: str,
                             job_name: str) -> Dict[str, Any]:
        """Submit a Nova batch inference job."""
        records = self._build_batch_records(s3_key, analysis_types, options)
        return self.start_batch_analysis_records(
            records=records,
            model=model,
            role_arn=role_arn,
            input_prefix=input_prefix,
            output_prefix=output_prefix,
            job_name=job_name
        )

    @handle_bedrock_errors
    def start_batch_analysis_records(self, records: List[Dict[str, Any]], model: str,
                                     role_arn: str, input_prefix: str, output_prefix: str,
                                     job_name: str) -> Dict[str, Any]:
        """Submit a Nova batch inference job using pre-built records."""
        if not role_arn:
            raise NovaError("BEDROCK_BATCH_ROLE_ARN is required for batch processing.")
        if not records:
            raise NovaError("No batch records provided for submission.")

        config = self.get_model_config(model)
        runtime_model_id = config.get('inference_profile_id', config['id'])

        # Normalize output prefix only (input will be at bucket root)
        output_prefix = self._normalize_s3_prefix(output_prefix)

        # CRITICAL FIX: Upload JSONL to bucket root so InputDataConfig can point to root folder
        # Bedrock requires InputDataConfig to be a folder containing BOTH JSONL and all S3 resources
        # Since videos are in proxies/, source_files/, etc., the only common parent is bucket root
        input_key = f"batch_input_{job_name}.jsonl"  # Bucket root - flat file
        output_prefix_key = f"{output_prefix}/{job_name}/"

        jsonl_body = "\n".join(json.dumps(record) for record in records)
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=input_key,
            Body=jsonl_body.encode('utf-8'),
            ContentType='application/json'
        )

        max_retries = int(os.getenv('NOVA_BATCH_SUBMIT_MAX_RETRIES', '8'))
        base_backoff = float(os.getenv('NOVA_BATCH_SUBMIT_BACKOFF_SECONDS', '10'))
        max_backoff = float(os.getenv('NOVA_BATCH_SUBMIT_MAX_BACKOFF_SECONDS', '120'))
        attempt = 0
        while True:
            try:
                # InputDataConfig must point to a FOLDER (not file) containing all resources
                # Use bucket root with trailing slash to indicate folder
                job_arn = self._start_batch_job(
                    job_name=job_name,
                    model_id=runtime_model_id,
                    role_arn=role_arn,
                    input_s3_uri=f"s3://{self.bucket_name}/",  # FOLDER (bucket root with trailing slash)
                    output_s3_uri=self._build_s3_uri(output_prefix_key)
                )
                break
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code')
                if error_code not in ('ServiceQuotaExceededException', 'ThrottlingException'):
                    raise
                if attempt >= max_retries:
                    raise
                sleep_seconds = min(max_backoff, base_backoff * (2 ** attempt))
                logger.warning(
                    "Bedrock batch submit quota hit (code=%s). Retrying in %ss (attempt %s/%s).",
                    error_code,
                    sleep_seconds,
                    attempt + 1,
                    max_retries
                )
                time.sleep(sleep_seconds)
                attempt += 1

        return {
            'batch_job_arn': job_arn,
            'batch_input_s3_key': input_key,
            'batch_output_s3_prefix': output_prefix_key
        }

    def _get_model_id(self, model: str) -> str:
        """Get the runtime model ID for a given model name."""
        config = self.get_model_config(model)
        return config.get('inference_profile_id', config['id'])

    @property
    def batch_role_arn(self) -> str:
        """Get the Bedrock batch role ARN from environment."""
        role_arn = os.getenv('BEDROCK_BATCH_ROLE_ARN')
        if not role_arn:
            raise NovaError("BEDROCK_BATCH_ROLE_ARN environment variable is required for batch processing.")
        return role_arn

    @handle_bedrock_errors
    def submit_multi_chunk_batch(
        self,
        chunks: List['BatchChunk'],
        model: str,
        analysis_types: List[str],
        options: Dict[str, Any],
        batch_s3_manager: 'BatchS3Manager',
        file_id_to_proxy_key: Dict[int, str]
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
            file_id_to_proxy_key: Mapping of file_id -> original proxy S3 key

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

            # Bedrock job names must match: [a-zA-Z0-9]{1,63}(-*[a-zA-Z0-9\+\-\.]){0,63}
            # Replace slashes and underscores with hyphens
            job_name = f"nova-batch-{chunk.s3_folder.replace('/', '-').replace('_', '-')}"

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
                'key_mapping': key_mapping,
                'manifest_key': manifest_key,
                'output_s3_prefix': f"nova/batch/output/{chunk.s3_folder}/"
            })

            logger.info(f"Submitted chunk {chunk.chunk_index}: {batch_job_arn}")

        return results

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
                            options: Dict[str, Any],
                            record_prefix: Optional[str] = None) -> Dict[str, Any]:
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
            # Batch outputs end in .jsonl.out
            if not (key.endswith('.jsonl') or key.endswith('.jsonl.out')):
                continue
            obj_data = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            body = obj_data['Body'].read().decode('utf-8')
            lines.extend([line for line in body.splitlines() if line.strip()])

        record_outputs = {}
        if record_prefix is not None and not isinstance(record_prefix, str):
            record_prefix = str(record_prefix)
        for line in lines:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            record_id = payload.get('recordId') or payload.get('record_id')
            if not record_id:
                continue
            if record_prefix:
                if not isinstance(record_id, str):
                    record_id = str(record_id)
                if not record_id.startswith(record_prefix):
                    continue
                record_id = record_id[len(record_prefix):]
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

        # Handle search_metadata if present in combined results
        if 'search_metadata' in record_outputs:
            output = record_outputs['search_metadata']
            metadata_text = self._extract_text_from_batch_output(output) or '{}'
            try:
                parsed = self._parse_json_response(metadata_text)
            except NovaError as e:
                logger.error(f"Failed to parse search_metadata batch response: {e}")
                parsed = {}

            # Validate and normalize search_metadata structure
            search_metadata = {
                'project': parsed.get('project', {}),
                'location': parsed.get('location', {}),
                'content': parsed.get('content', {}),
                'keywords': parsed.get('keywords', []),
                'dates': parsed.get('dates', {})
            }
            results['search_metadata'] = search_metadata

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
        """Attempt to sanitize malformed JSON by fixing common issues."""
        return sanitize_json_string(text)

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parse JSON from Nova response, handling markdown code fences and common errors."""
        try:
            return parse_json_response(text)
        except NovaParseError as e:
            # Convert NovaParseError to NovaError for backward compatibility
            raise NovaError(str(e))

    def _close_json_structure(self, json_str: str) -> str:
        """Intelligently close an incomplete JSON structure by analyzing nesting levels."""
        return close_json_structure(json_str)

    def _parse_timecode_to_seconds(self, timecode: str) -> int:
        """Parse MM:SS or HH:MM:SS timecode into seconds."""
        return parse_timecode_to_seconds(timecode)

    def _ensure_list(self, value: Any) -> List[str]:
        """Normalize value into a list of strings."""
        return ensure_list(value)

    def _parse_time_range(self, time_range: str) -> Optional[Dict[str, Any]]:
        """Parse a time range string into structured fields."""
        return parse_time_range(time_range)

    def _parse_time_ranges(self, time_ranges: List[str]) -> List[Dict[str, Any]]:
        """Parse a list of time range strings into structured fields."""
        return parse_time_ranges(time_ranges)

    def _enrich_chapter_data(self, chapter: Dict[str, Any]) -> None:
        """Enrich chapter dictionary with computed fields (in-place modification)."""
        enrich_chapter_data(chapter)

    def _enrich_equipment_data(self, equip: Dict[str, Any]) -> None:
        """Enrich equipment dictionary with computed fields (in-place modification)."""
        enrich_equipment_data(equip)

    def _enrich_topic_data(self, topic: Dict[str, Any]) -> None:
        """Enrich topic dictionary with computed fields (in-place modification)."""
        enrich_topic_data(topic)

    def _enrich_speaker_data(self, speaker: Dict[str, Any]) -> None:
        """Enrich speaker dictionary with computed fields (in-place modification)."""
        enrich_speaker_data(speaker)

    def _build_topics_summary(self, topics_discussed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build topics summary from topics_discussed list."""
        return build_topics_summary(topics_discussed)

    def _get_summary_prompt(self, depth: str, language: str) -> str:
        """Build summary prompt based on depth and language."""
        return get_summary_prompt(depth, language)

    def _get_chapters_prompt(self) -> str:
        """Build chapter detection prompt."""
        return get_chapters_prompt()

    def _get_elements_prompt(self) -> str:
        """Build element identification prompt."""
        return get_elements_prompt()

    def _get_combined_prompt(self, depth: str, language: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Build combined analysis prompt for a single-pass output."""
        return get_combined_prompt(depth, language, context)

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
        return build_combined_results(
            payload=payload,
            model=model,
            options=options,
            usage=usage,
            cost_usd=cost_usd,
            processing_time_seconds=processing_time_seconds,
            generated_at=generated_at,
            get_model_config_func=get_model_config,
            validate_waterfall_func=validate_waterfall_classification,
            combined_analysis_types=self.COMBINED_ANALYSIS_TYPES
        )

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
