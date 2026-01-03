"""
Shared state and utilities for file management routes.
"""
import threading
import time
from typing import Dict, Any, List


# ============================================================================
# BATCH PROCESSING STATE
# ============================================================================

# Global batch jobs dictionary: {job_id: BatchJob}
_batch_jobs: Dict[str, 'BatchJob'] = {}
_batch_jobs_lock = threading.Lock()


class BatchJob:
    """Tracks batch processing job state."""

    def __init__(self, job_id: str, action_type: str, total_files: int, file_ids: List[int]):
        self.job_id = job_id
        self.action_type = action_type  # 'proxy', 'transcribe', 'transcript-summary', 'nova', 'embeddings'
        self.total_files = total_files
        self.file_ids = file_ids
        self.completed_files = 0
        self.failed_files = 0
        self.current_file = None
        self.status = 'RUNNING'  # RUNNING, COMPLETED, CANCELLED, FAILED
        self.errors = []
        self.start_time = time.time()
        self.end_time = None
        self.results = []  # List of result dicts for each file
        self.total_batch_size = 0  # Total size of all files in batch (bytes)
        self.processed_files_sizes = []  # Sizes of processed files (bytes)
        self.total_proxy_size = 0  # Total size of all generated proxy files (bytes) - for proxy action only
        self.total_tokens = 0  # Total tokens processed (Nova only)
        self.processed_files_tokens = []  # Tokens for each processed file (Nova only)
        self.total_cost_usd = 0.0  # Total cost in USD (Nova only)
        self.processed_files_costs = []  # Cost for each processed file (Nova only)
        self.options = {}  # Additional options (e.g., file_types dict for mixed batches)
        # Video/image specific tracking for unified proxy generation
        self.completed_videos = 0
        self.completed_images = 0
        self.failed_videos = 0
        self.failed_images = 0
        self.total_video_proxy_size = 0
        self.total_image_proxy_size = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON response."""
        elapsed = (self.end_time or time.time()) - self.start_time
        processed_count = self.completed_files + self.failed_files
        progress = processed_count / self.total_files * 100 if self.total_files > 0 else 0

        # Calculate average sizes
        avg_video_size_total = self.total_batch_size / self.total_files if self.total_files > 0 else None
        avg_video_size_processed = (
            sum(self.processed_files_sizes) / len(self.processed_files_sizes)
            if len(self.processed_files_sizes) > 0 else None
        )

        # Calculate total processed size
        total_processed_size = sum(self.processed_files_sizes) if len(self.processed_files_sizes) > 0 else 0

        # Calculate time remaining estimate
        time_remaining = None
        if processed_count > 0 and self.total_files > processed_count and elapsed > 0:
            avg_time_per_file = elapsed / processed_count
            remaining_files = self.total_files - processed_count
            time_remaining = avg_time_per_file * remaining_files

        # Calculate Nova token metrics
        avg_tokens_per_file = None
        if len(self.processed_files_tokens) > 0:
            avg_tokens_per_file = sum(self.processed_files_tokens) / len(self.processed_files_tokens)

        # Calculate Nova cost metrics
        avg_cost_per_file = None
        if len(self.processed_files_costs) > 0:
            avg_cost_per_file = sum(self.processed_files_costs) / len(self.processed_files_costs)

        return {
            'job_id': self.job_id,
            'action_type': self.action_type,
            'status': self.status,
            'total_files': self.total_files,
            'completed_files': self.completed_files,
            'failed_files': self.failed_files,
            'current_file': self.current_file,
            'progress_percent': round(progress, 1),
            'elapsed_seconds': round(elapsed, 1),
            'total_batch_size': self.total_batch_size,
            'total_processed_size': total_processed_size,
            'total_proxy_size': self.total_proxy_size,
            'time_remaining_seconds': round(time_remaining, 1) if time_remaining is not None else None,
            'avg_video_size_total': avg_video_size_total,
            'avg_video_size_processed': avg_video_size_processed,
            'total_tokens': self.total_tokens,
            'avg_tokens_per_file': round(avg_tokens_per_file, 1) if avg_tokens_per_file is not None else None,
            'total_cost_usd': round(self.total_cost_usd, 2) if self.total_cost_usd is not None else None,
            'avg_cost_per_file': round(avg_cost_per_file, 4) if avg_cost_per_file is not None else None,
            'errors': self.errors,
            'results': self.results,
            'completed_videos': self.completed_videos,
            'completed_images': self.completed_images,
            'failed_videos': self.failed_videos,
            'failed_images': self.failed_images,
            'total_video_proxy_size': self.total_video_proxy_size,
            'total_image_proxy_size': self.total_image_proxy_size
        }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def normalize_transcription_provider(provider: str) -> str:
    """Normalize transcription provider name."""
    if not provider:
        return 'whisper'
    provider = provider.lower()
    if provider in (
        'nova', 'sonic', 'nova_sonic',
        'sonic2', 'sonic_2', 'sonic_2_online',
        'nova2_sonic', 'nova_2_sonic'
    ):
        return 'nova_sonic'
    return provider


def select_latest_completed_transcript(transcripts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick the most recent completed transcript with text."""
    completed = [
        t for t in transcripts
        if t.get('status') == 'COMPLETED' and t.get('transcript_text')
    ]
    if not completed:
        return {}
    completed.sort(
        key=lambda t: t.get('completed_at') or t.get('created_at') or '',
        reverse=True
    )
    return completed[0]


def get_batch_job(job_id: str) -> 'BatchJob':
    """Get a batch job by ID."""
    with _batch_jobs_lock:
        return _batch_jobs.get(job_id)


def set_batch_job(job_id: str, job: 'BatchJob') -> None:
    """Store a batch job."""
    with _batch_jobs_lock:
        _batch_jobs[job_id] = job


def delete_batch_job(job_id: str) -> None:
    """Remove a batch job."""
    with _batch_jobs_lock:
        _batch_jobs.pop(job_id, None)
