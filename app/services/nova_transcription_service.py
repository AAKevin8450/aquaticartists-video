"""
AWS Nova 2 Sonic transcription service using Amazon Bedrock.
Handles audio extraction, Bedrock invocation, and batch processing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

try:
    import ffmpeg
except ImportError:
    ffmpeg = None

from app.services.transcription_service import TranscriptionError, TranscriptionProgress, TranscriptionService


logger = logging.getLogger(__name__)


class NovaTranscriptionError(TranscriptionError):
    """Nova transcription errors."""
    pass


@dataclass
class NovaTranscriptionConfig:
    """Configuration for Nova Sonic transcription."""
    model_id: str
    runtime_model_id: str
    max_tokens: int = 8192
    temperature: float = 0.0


class NovaSonicTranscriptionService:
    """Service for AWS Nova 2 Sonic transcription via Bedrock."""

    AUDIO_FORMAT = 'wav'

    def __init__(
        self,
        bucket_name: str,
        region: str,
        config: NovaTranscriptionConfig,
        aws_access_key: str | None = None,
        aws_secret_key: str | None = None
    ):
        if ffmpeg is None:
            raise NovaTranscriptionError("ffmpeg-python not installed. Run: pip install ffmpeg-python")

        if not bucket_name:
            raise NovaTranscriptionError("S3 bucket name is required for Nova Sonic transcription.")

        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.bucket_name = bucket_name
        self.region = region
        self.config = config
        self.debug_enabled = os.getenv('NOVA_SONIC_DEBUG', '').lower() in ('1', 'true', 'yes')
        self.client = boto3.client('bedrock-runtime', **session_kwargs)
        self.s3_client = boto3.client('s3', **session_kwargs)

        # Batch processing state
        self._batch_jobs: Dict[str, TranscriptionProgress] = {}
        self._cancel_flags: Dict[str, bool] = {}

    @property
    def model_name(self) -> str:
        return 'nova-2-sonic'

    def get_file_metadata(self, file_path: str) -> tuple[int, float]:
        """Get file metadata (size and modified time)."""
        stat = os.stat(file_path)
        return (stat.st_size, stat.st_mtime)

    def extract_audio(self, video_path: str, output_path: Optional[str] = None) -> str:
        """Extract audio from video file using FFmpeg."""
        if not os.path.exists(video_path):
            raise NovaTranscriptionError(f"Video file not found: {video_path}")

        if output_path is None:
            temp_dir = tempfile.gettempdir()
            file_hash = hashlib.md5(video_path.encode()).hexdigest()[:8]
            output_path = os.path.join(temp_dir, f"nova_audio_{file_hash}.wav")

        try:
            stream = ffmpeg.input(video_path)
            stream = ffmpeg.output(
                stream,
                output_path,
                acodec='pcm_s16le',
                ac=1,
                ar='16000',
                loglevel='error'
            )
            ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)

            if not os.path.exists(output_path):
                raise NovaTranscriptionError("Audio extraction failed - output file not created")

            return output_path
        except ffmpeg.Error as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            raise NovaTranscriptionError(f"FFmpeg error during audio extraction: {error_msg}")
        except Exception as e:
            raise NovaTranscriptionError(f"Failed to extract audio: {str(e)}")

    def _upload_audio_to_s3(self, audio_path: str) -> str:
        """Upload extracted audio to S3 and return the S3 key."""
        key = f"nova/transcription/{uuid.uuid4()}.{self.AUDIO_FORMAT}"
        try:
            self.s3_client.upload_file(audio_path, self.bucket_name, key)
        except ClientError as e:
            raise NovaTranscriptionError(f"Failed to upload audio to S3: {e}")
        return key

    def _delete_s3_object(self, s3_key: str):
        """Delete temporary audio from S3."""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
        except ClientError:
            pass

    def _parse_transcription_text(self, response: Dict[str, Any]) -> str:
        """Extract transcript text from Bedrock response."""
        def _extract_content_text(content: Any) -> str:
            if isinstance(content, list):
                parts = [item.get('text', '') for item in content if isinstance(item, dict)]
                text = ''.join(parts).strip()
                if text:
                    return text
            if isinstance(content, dict) and 'text' in content:
                return str(content.get('text', '')).strip()
            if isinstance(content, str):
                return content.strip()
            return ''

        output = response.get('output')
        if isinstance(output, dict):
            message = output.get('message')
            if isinstance(message, dict):
                text = _extract_content_text(message.get('content', []))
                if text:
                    return text
            if 'text' in output:
                return str(output.get('text', '')).strip()

        message = response.get('message')
        if isinstance(message, dict):
            text = _extract_content_text(message.get('content', []))
            if text:
                return text

        if 'transcript' in response:
            return str(response.get('transcript', '')).strip()
        if 'transcription' in response:
            return str(response.get('transcription', '')).strip()
        if 'text' in response:
            return str(response.get('text', '')).strip()
        return ''

    def _read_invoke_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Read JSON payload from a non-streaming Bedrock response."""
        raw_body = response.get('body')
        if hasattr(raw_body, 'read'):
            body_str = raw_body.read().decode('utf-8')
        else:
            body_str = raw_body
        if self.debug_enabled:
            self._log_response_body(body_str, stream=False)
        try:
            return json.loads(body_str) if body_str else {}
        except json.JSONDecodeError as e:
            raise NovaTranscriptionError(f"Failed to parse Nova Sonic response: {e}")

    def _read_stream_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Read JSON payload from a streaming Bedrock response."""
        stream = response.get('body')
        if stream is None:
            return {}

        chunks: List[str] = []
        for event in stream:
            if 'chunk' in event:
                chunk_bytes = event['chunk'].get('bytes')
                if chunk_bytes:
                    chunks.append(chunk_bytes.decode('utf-8'))
                continue
            if 'internalServerException' in event:
                message = event['internalServerException'].get('message', 'Stream error')
                raise NovaTranscriptionError(message)
            if 'modelStreamError' in event:
                message = event['modelStreamError'].get('message', 'Stream error')
                raise NovaTranscriptionError(message)

        body_str = ''.join(chunks).strip()
        if not body_str:
            return {}

        if self.debug_enabled:
            self._log_response_body(body_str, stream=True)

        try:
            return json.loads(body_str)
        except json.JSONDecodeError:
            for line in reversed(body_str.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
            raise NovaTranscriptionError("Failed to parse Nova Sonic streaming response.")

    def _invoke_bedrock(self, request_body: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke Nova Sonic using the most compatible Bedrock API."""
        payload = json.dumps(request_body).encode('utf-8')
        if hasattr(self.client, 'invoke_model_with_response_stream'):
            response = self.client.invoke_model_with_response_stream(
                modelId=self.config.runtime_model_id,
                body=payload,
                accept='application/json',
                contentType='application/json'
            )
            return self._read_stream_response(response)

        response = self.client.invoke_model(
            modelId=self.config.runtime_model_id,
            body=payload,
            accept='application/json',
            contentType='application/json'
        )
        return self._read_invoke_response(response)

    def _log_response_body(self, body_str: str, stream: bool) -> None:
        """Log Bedrock response payload for debugging."""
        if not body_str:
            logger.debug("Nova Sonic response body is empty (stream=%s).", stream)
            return
        trimmed = body_str.strip()
        if len(trimmed) > 4000:
            trimmed = trimmed[:4000] + '...[truncated]'
        logger.debug("Nova Sonic response body (stream=%s): %s", stream, trimmed)

    def _log_request_body(self, request_body: Dict[str, Any]) -> None:
        """Log Bedrock request payload for debugging with redacted S3 URI."""
        redacted = json.loads(json.dumps(request_body))
        try:
            content = redacted.get('messages', [{}])[0].get('content', [])
            for item in content:
                if isinstance(item, dict) and 'audio' in item:
                    source = item.get('audio', {}).get('source', {})
                    if 's3Location' in source and 'uri' in source['s3Location']:
                        source['s3Location']['uri'] = 's3://[redacted]'
        except Exception:
            pass
        logger.debug("Nova Sonic request body: %s", json.dumps(redacted, ensure_ascii=True))

    def transcribe_file(self, video_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Transcribe a single video file using Nova Sonic."""
        if not os.path.exists(video_path):
            raise NovaTranscriptionError(f"Video file not found: {video_path}")

        audio_path = None
        s3_key = None
        start_time = time.time()

        try:
            audio_path = self.extract_audio(video_path)
            s3_key = self._upload_audio_to_s3(audio_path)
            s3_uri = f"s3://{self.bucket_name}/{s3_key}"

            prompt = "Transcribe the provided audio. Return plain text only."
            if language:
                prompt = f"Transcribe the provided audio in {language}. Return plain text only."

            request_body = {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "audio": {
                                    "format": self.AUDIO_FORMAT,
                                    "source": {
                                        "s3Location": {
                                            "uri": s3_uri
                                        }
                                    }
                                }
                            },
                            {"text": prompt}
                        ]
                    }
                ],
                "inferenceConfig": {
                    "maxTokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "topP": 0.9
                }
            }

            if self.debug_enabled:
                logger.debug("Nova Sonic model runtime id: %s", self.config.runtime_model_id)
                self._log_request_body(request_body)

            payload = self._invoke_bedrock(request_body)
            transcript_text = self._parse_transcription_text(payload)
            character_count, word_count = TranscriptionService.calculate_text_metrics(transcript_text)

            processing_time = time.time() - start_time

            return {
                'transcript_text': transcript_text,
                'character_count': character_count,
                'word_count': word_count,
                'segments': None,
                'word_timestamps': None,
                'language': language or 'auto',
                'duration_seconds': None,
                'confidence_score': None,
                'processing_time_seconds': processing_time,
                'model_used': self.model_name,
                'model_id': self.config.model_id
            }
        except ClientError as e:
            raise NovaTranscriptionError(f"Nova Sonic transcription failed: {e}")
        finally:
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
            if s3_key:
                self._delete_s3_object(s3_key)

    def batch_transcribe(
        self,
        file_paths: List[str],
        job_id: str,
        db_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        progress_callback: Optional[Callable[[TranscriptionProgress], None]] = None,
        force: bool = False,
        language: Optional[str] = None
    ) -> TranscriptionProgress:
        """Transcribe multiple files in batch (sequential)."""
        total_batch_size = 0
        for file_path in file_paths:
            try:
                total_batch_size += os.path.getsize(file_path)
            except OSError:
                pass

        progress = TranscriptionProgress(
            total_files=len(file_paths),
            status='RUNNING',
            start_time=time.time(),
            total_batch_size=total_batch_size
        )
        self._batch_jobs[job_id] = progress
        self._cancel_flags[job_id] = False

        for file_path in file_paths:
            if self._cancel_flags.get(job_id, False):
                progress.status = 'CANCELLED'
                break

            progress.current_file = file_path
            if progress_callback:
                progress_callback(progress)

            try:
                try:
                    file_size = os.path.getsize(file_path)
                except OSError:
                    file_size = 0

                result = self.transcribe_file(file_path, language=language)
                if db_callback:
                    db_callback(file_path, result)

                progress.completed_files += 1
                progress.processed_files_sizes.append(file_size)
            except Exception as e:
                try:
                    file_size = os.path.getsize(file_path)
                    progress.processed_files_sizes.append(file_size)
                except OSError:
                    pass
                progress.failed_files += 1
                progress.errors.append({
                    'file_path': file_path,
                    'error': str(e)
                })

            if progress_callback:
                progress_callback(progress)

        progress.end_time = time.time()
        if progress.status == 'RUNNING':
            progress.status = 'COMPLETED'
        progress.current_file = None
        if progress_callback:
            progress_callback(progress)

        return progress

    def get_batch_progress(self, job_id: str) -> Optional[TranscriptionProgress]:
        """Get progress for a batch job."""
        return self._batch_jobs.get(job_id)

    def cancel_batch(self, job_id: str) -> bool:
        """Cancel a running batch job."""
        if job_id in self._batch_jobs:
            self._cancel_flags[job_id] = True
            return True
        return False

    def cleanup_job(self, job_id: str):
        """Clean up job state after completion."""
        self._batch_jobs.pop(job_id, None)
        self._cancel_flags.pop(job_id, None)


def create_nova_transcription_service(
    bucket_name: str,
    region: str,
    model_id: str,
    runtime_model_id: str,
    aws_access_key: str | None = None,
    aws_secret_key: str | None = None,
    max_tokens: int = 8192,
    temperature: float = 0.0
) -> NovaSonicTranscriptionService:
    """Factory function to create NovaSonicTranscriptionService instance."""
    config = NovaTranscriptionConfig(
        model_id=model_id,
        runtime_model_id=runtime_model_id,
        max_tokens=max_tokens,
        temperature=temperature
    )
    return NovaSonicTranscriptionService(
        bucket_name=bucket_name,
        region=region,
        config=config,
        aws_access_key=aws_access_key,
        aws_secret_key=aws_secret_key
    )
