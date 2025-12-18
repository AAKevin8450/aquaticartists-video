"""
Local video transcription service using faster-whisper.
Handles audio extraction, speech-to-text conversion, and batch processing.
"""
import os
import hashlib
import time
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Tuple
from dataclasses import dataclass, field
import threading
import queue

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

try:
    import ffmpeg
except ImportError:
    ffmpeg = None


class TranscriptionError(Exception):
    """Base exception for transcription errors."""
    pass


@dataclass
class TranscriptionProgress:
    """Progress tracking for batch transcription."""
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    current_file: Optional[str] = None
    status: str = 'PENDING'  # PENDING, RUNNING, COMPLETED, CANCELLED, FAILED
    errors: List[Dict[str, str]] = field(default_factory=list)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    total_batch_size: int = 0  # Total size of all files in batch (bytes)
    processed_files_sizes: List[int] = field(default_factory=list)  # Sizes of processed files (bytes)

    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_files == 0:
            return 0.0
        return (self.completed_files + self.failed_files) / self.total_files * 100

    @property
    def elapsed_time(self) -> Optional[float]:
        """Calculate elapsed time in seconds."""
        if self.start_time is None:
            return None
        end = self.end_time if self.end_time else time.time()
        return end - self.start_time

    @property
    def avg_video_size_total(self) -> Optional[float]:
        """Calculate average video size for entire batch."""
        if self.total_files == 0:
            return None
        return self.total_batch_size / self.total_files

    @property
    def avg_video_size_processed(self) -> Optional[float]:
        """Calculate average video size for processed files only."""
        if len(self.processed_files_sizes) == 0:
            return None
        return sum(self.processed_files_sizes) / len(self.processed_files_sizes)


class TranscriptionService:
    """Service for local video transcription using faster-whisper."""

    # Supported video extensions
    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg'}

    @staticmethod
    def calculate_text_metrics(text: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Calculate character count and word count from transcript text.
        Returns (None, None) for empty or whitespace-only text (no speech).

        Args:
            text: Transcript text

        Returns:
            Tuple of (character_count, word_count) or (None, None) if no speech
        """
        if not text or not text.strip():
            return (None, None)

        # Remove leading/trailing whitespace
        cleaned_text = text.strip()

        # Character count (excluding whitespace)
        char_count = len(cleaned_text.replace(' ', '').replace('\n', '').replace('\t', ''))

        # Word count (split by whitespace)
        word_count = len(cleaned_text.split())

        # If no actual content, return None
        if char_count == 0 or word_count == 0:
            return (None, None)

        return (char_count, word_count)

    def __init__(self, model_size: str = 'medium', device: str = 'auto', compute_type: str = 'default'):
        """
        Initialize transcription service.

        Args:
            model_size: Whisper model size (tiny, base, small, medium, large-v2, large-v3)
            device: Device to use ('cpu', 'cuda', 'auto')
            compute_type: Compute type ('int8', 'float16', 'float32', 'default')
        """
        if WhisperModel is None:
            raise TranscriptionError("faster-whisper not installed. Run: pip install faster-whisper")

        if ffmpeg is None:
            raise TranscriptionError("ffmpeg-python not installed. Run: pip install ffmpeg-python")

        self.model_size = model_size
        self.device = device if device != 'auto' else self._detect_device()
        self.compute_type = self._get_compute_type(compute_type)
        self._model: Optional[WhisperModel] = None
        self._model_lock = threading.Lock()

        # Batch processing state
        self._batch_jobs: Dict[str, TranscriptionProgress] = {}
        self._cancel_flags: Dict[str, bool] = {}

    def _detect_device(self) -> str:
        """Detect best available device (CUDA vs CPU)."""
        try:
            import torch
            if torch.cuda.is_available():
                return 'cuda'
        except ImportError:
            pass
        return 'cpu'

    def _get_compute_type(self, compute_type: str) -> str:
        """Get appropriate compute type based on device and user preference."""
        if compute_type != 'default':
            return compute_type

        if self.device == 'cuda':
            return 'float16'  # Faster on GPU
        else:
            return 'int8'  # Faster on CPU with minimal quality loss

    def _load_model(self, model_size: Optional[str] = None):
        """
        Load Whisper model (lazy loading with caching).

        Args:
            model_size: Model size to load (if different from current, reloads model)
        """
        # If model size is specified and different, reload model
        if model_size and model_size != self.model_size:
            with self._model_lock:
                self.model_size = model_size
                self._model = None  # Clear cached model

        if self._model is None:
            with self._model_lock:
                if self._model is None:  # Double-check pattern
                    self._model = WhisperModel(
                        self.model_size,
                        device=self.device,
                        compute_type=self.compute_type
                    )
        return self._model

    def set_model_size(self, model_size: str):
        """
        Change the model size (will reload model on next use).

        Args:
            model_size: New model size (tiny, base, small, medium, large-v2, large-v3)
        """
        with self._model_lock:
            if model_size != self.model_size:
                self.model_size = model_size
                self._model = None  # Clear cached model to force reload

    def get_file_metadata(self, file_path: str) -> tuple[int, float]:
        """
        Get file metadata (size and modified time) for identification.
        Much faster than hash calculation - instant filesystem metadata lookup.

        Args:
            file_path: Path to file

        Returns:
            Tuple of (file_size_bytes, file_modified_time)
        """
        stat = os.stat(file_path)
        return (stat.st_size, stat.st_mtime)

    def extract_audio(self, video_path: str, output_path: Optional[str] = None) -> str:
        """
        Extract audio from video file using FFmpeg.

        Args:
            video_path: Path to video file
            output_path: Optional output path for audio file (auto-generated if None)

        Returns:
            Path to extracted audio file (WAV format, 16kHz mono)
        """
        if not os.path.exists(video_path):
            raise TranscriptionError(f"Video file not found: {video_path}")

        # Generate output path if not provided
        if output_path is None:
            temp_dir = tempfile.gettempdir()
            file_hash = hashlib.md5(video_path.encode()).hexdigest()[:8]
            output_path = os.path.join(temp_dir, f"audio_{file_hash}.wav")

        try:
            # Extract audio: convert to 16kHz mono WAV (optimal for Whisper)
            stream = ffmpeg.input(video_path)
            stream = ffmpeg.output(
                stream,
                output_path,
                acodec='pcm_s16le',  # 16-bit PCM
                ac=1,  # Mono
                ar='16000',  # 16kHz sample rate
                loglevel='error'
            )
            ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)

            if not os.path.exists(output_path):
                raise TranscriptionError("Audio extraction failed - output file not created")

            return output_path

        except ffmpeg.Error as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            raise TranscriptionError(f"FFmpeg error during audio extraction: {error_msg}")
        except Exception as e:
            raise TranscriptionError(f"Failed to extract audio: {str(e)}")

    def transcribe_file(
        self,
        video_path: str,
        language: Optional[str] = None,
        beam_size: int = 5,
        vad_filter: bool = True,
        word_timestamps: bool = True
    ) -> Dict[str, Any]:
        """
        Transcribe a single video file.

        Args:
            video_path: Path to video file
            language: Language code (e.g., 'en', 'es', 'fr') or None for auto-detect
            beam_size: Beam size for decoding (higher = better quality but slower)
            vad_filter: Use voice activity detection to filter silence
            word_timestamps: Include word-level timestamps

        Returns:
            Dictionary with transcription results:
                - transcript_text: Full transcript as plain text
                - segments: List of segment dictionaries with timestamps
                - word_timestamps: List of word-level timestamps (if enabled)
                - language: Detected or specified language
                - duration_seconds: Audio duration
                - confidence_score: Average confidence across segments
        """
        if not os.path.exists(video_path):
            raise TranscriptionError(f"Video file not found: {video_path}")

        audio_path = None
        try:
            # Extract audio
            audio_path = self.extract_audio(video_path)

            # Load model
            model = self._load_model()

            # Transcribe
            start_time = time.time()
            segments, info = model.transcribe(
                audio_path,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
                word_timestamps=word_timestamps
            )

            # Process segments
            transcript_segments = []
            word_timestamps_list = []
            full_text_parts = []
            total_confidence = 0.0
            segment_count = 0

            for segment in segments:
                segment_dict = {
                    'id': segment.id,
                    'start': segment.start,
                    'end': segment.end,
                    'text': segment.text.strip(),
                    'avg_logprob': segment.avg_logprob,
                    'no_speech_prob': segment.no_speech_prob
                }

                # Add words if available
                if word_timestamps and hasattr(segment, 'words') and segment.words:
                    segment_dict['words'] = [
                        {
                            'word': word.word,
                            'start': word.start,
                            'end': word.end,
                            'probability': word.probability
                        }
                        for word in segment.words
                    ]
                    word_timestamps_list.extend(segment_dict['words'])

                transcript_segments.append(segment_dict)
                full_text_parts.append(segment.text.strip())

                # Calculate average confidence (convert log probability to linear)
                total_confidence += (1.0 - segment.no_speech_prob)
                segment_count += 1

            processing_time = time.time() - start_time

            # Calculate average confidence
            avg_confidence = total_confidence / segment_count if segment_count > 0 else 0.0

            # Get audio duration (from last segment)
            duration_seconds = transcript_segments[-1]['end'] if transcript_segments else 0.0

            # Calculate character and word counts
            full_text = ' '.join(full_text_parts)
            character_count, word_count = self.calculate_text_metrics(full_text)

            return {
                'transcript_text': full_text,
                'character_count': character_count,
                'word_count': word_count,
                'segments': transcript_segments,
                'word_timestamps': word_timestamps_list if word_timestamps else None,
                'language': info.language,
                'duration_seconds': duration_seconds,
                'confidence_score': avg_confidence,
                'processing_time_seconds': processing_time,
                'model_used': self.model_size
            }

        finally:
            # Clean up temporary audio file
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception:
                    pass  # Ignore cleanup errors

    def scan_directory(
        self,
        directory_path: str,
        extensions: Optional[List[str]] = None,
        recursive: bool = True
    ) -> List[str]:
        """
        Scan directory for video files.

        Args:
            directory_path: Path to directory to scan
            extensions: List of file extensions to include (default: all video extensions)
            recursive: Scan subdirectories recursively

        Returns:
            List of video file paths
        """
        if not os.path.isdir(directory_path):
            raise TranscriptionError(f"Directory not found: {directory_path}")

        if extensions is None:
            extensions = self.VIDEO_EXTENSIONS
        else:
            extensions = {ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in extensions}

        video_files = []
        path = Path(directory_path)

        if recursive:
            for ext in extensions:
                video_files.extend(path.rglob(f'*{ext}'))
        else:
            for ext in extensions:
                video_files.extend(path.glob(f'*{ext}'))

        return [str(f) for f in video_files]

    def batch_transcribe(
        self,
        file_paths: List[str],
        job_id: str,
        db_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        progress_callback: Optional[Callable[[TranscriptionProgress], None]] = None,
        force: bool = False,
        model_size: Optional[str] = None,
        **transcribe_kwargs
    ) -> TranscriptionProgress:
        """
        Transcribe multiple files in batch.

        Args:
            file_paths: List of video file paths to transcribe
            job_id: Unique job ID for tracking
            db_callback: Callback function(file_path, result) to save results to database
            progress_callback: Callback function(progress) for progress updates
            force: Reprocess files even if already transcribed
            model_size: Model size to use (if different from current, will reload model)
            **transcribe_kwargs: Additional arguments for transcribe_file()

        Returns:
            TranscriptionProgress object with final status
        """
        # Set model size if specified
        if model_size:
            self.set_model_size(model_size)

        # Calculate total batch size
        total_batch_size = 0
        for file_path in file_paths:
            try:
                total_batch_size += os.path.getsize(file_path)
            except OSError:
                pass  # Skip files that can't be accessed

        progress = TranscriptionProgress(
            total_files=len(file_paths),
            status='RUNNING',
            start_time=time.time(),
            total_batch_size=total_batch_size
        )
        self._batch_jobs[job_id] = progress
        self._cancel_flags[job_id] = False

        for file_path in file_paths:
            # Check for cancellation
            if self._cancel_flags.get(job_id, False):
                progress.status = 'CANCELLED'
                break

            progress.current_file = file_path

            # Notify progress
            if progress_callback:
                progress_callback(progress)

            try:
                # Get file size for tracking
                try:
                    file_size = os.path.getsize(file_path)
                except OSError:
                    file_size = 0

                # Transcribe file
                result = self.transcribe_file(file_path, **transcribe_kwargs)

                # Save to database if callback provided
                if db_callback:
                    db_callback(file_path, result)

                progress.completed_files += 1
                progress.processed_files_sizes.append(file_size)

            except Exception as e:
                # Track failed file size too
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

            # Notify progress
            if progress_callback:
                progress_callback(progress)

        # Finalize
        progress.end_time = time.time()
        if progress.status == 'RUNNING':
            progress.status = 'COMPLETED'

        progress.current_file = None

        # Notify final progress
        if progress_callback:
            progress_callback(progress)

        return progress

    def get_batch_progress(self, job_id: str) -> Optional[TranscriptionProgress]:
        """Get progress for a batch job."""
        return self._batch_jobs.get(job_id)

    def cancel_batch(self, job_id: str) -> bool:
        """
        Cancel a running batch job.

        Args:
            job_id: Job ID to cancel

        Returns:
            True if job was found and cancelled, False otherwise
        """
        if job_id in self._batch_jobs:
            self._cancel_flags[job_id] = True
            return True
        return False

    def cleanup_job(self, job_id: str):
        """Clean up job state after completion."""
        self._batch_jobs.pop(job_id, None)
        self._cancel_flags.pop(job_id, None)


def create_transcription_service(
    model_size: str = 'medium',
    device: str = 'auto',
    compute_type: str = 'default'
) -> TranscriptionService:
    """
    Factory function to create TranscriptionService instance.

    Args:
        model_size: Whisper model size (tiny, base, small, medium, large-v2, large-v3)
        device: Device to use ('cpu', 'cuda', 'auto')
        compute_type: Compute type ('int8', 'float16', 'float32', 'default')

    Returns:
        TranscriptionService instance
    """
    return TranscriptionService(model_size, device, compute_type)
