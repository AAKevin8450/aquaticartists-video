"""
Video chunking service for long video handling in AWS Nova analysis.
Provides FFmpeg-based video segmentation with overlap support for context preservation.
"""
import os
import tempfile
import logging
import boto3
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path
from botocore.exceptions import ClientError

try:
    import ffmpeg
except ImportError:
    ffmpeg = None

logger = logging.getLogger(__name__)


class VideoChunkerError(Exception):
    """Base exception for video chunker errors."""
    pass


class VideoChunker:
    """Service for chunking long videos for Nova processing."""

    # Chunk configurations based on Nova model context windows
    # Using conservative chunk sizes to leave headroom below token limits
    CHUNK_CONFIGS = {
        'micro': {
            'max_duration': 720,     # 12 minutes (128K token limit)
            'chunk_duration': 600,   # 10 minutes per chunk
            'overlap_pct': 0.10      # 10% overlap between chunks
        },
        'lite': {
            'max_duration': 1800,    # 30 minutes (300K token limit)
            'chunk_duration': 1500,  # 25 minutes per chunk
            'overlap_pct': 0.10      # 10% overlap
        },
        'pro': {
            'max_duration': 1800,    # 30 minutes (300K token limit)
            'chunk_duration': 1500,  # 25 minutes per chunk
            'overlap_pct': 0.10      # 10% overlap
        },
        'pro_2_preview': {
            'max_duration': 1800,    # 30 minutes (preview model)
            'chunk_duration': 1500,  # 25 minutes per chunk
            'overlap_pct': 0.10      # 10% overlap
        },
        'omni_2_preview': {
            'max_duration': 1800,    # 30 minutes (preview model)
            'chunk_duration': 1500,  # 25 minutes per chunk
            'overlap_pct': 0.10      # 10% overlap
        },
        'premier': {
            'max_duration': 5400,    # 90 minutes (1M token limit)
            'chunk_duration': 4800,  # 80 minutes per chunk
            'overlap_pct': 0.10      # 10% overlap
        }
    }

    def __init__(self, bucket_name: str, region: str,
                 aws_access_key: str = None, aws_secret_key: str = None,
                 temp_dir: str = None):
        """
        Initialize video chunker.

        Args:
            bucket_name: S3 bucket for chunk storage
            region: AWS region
            aws_access_key: AWS access key (optional, uses default credentials if None)
            aws_secret_key: AWS secret key (optional)
            temp_dir: Directory for temporary files (uses system temp if None)
        """
        if ffmpeg is None:
            raise VideoChunkerError("ffmpeg-python not installed. Run: pip install ffmpeg-python")

        self.bucket_name = bucket_name
        self.region = region
        self.temp_dir = temp_dir or tempfile.gettempdir()

        # Initialize S3 client
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.s3_client = boto3.client('s3', **session_kwargs)

        logger.info(f"VideoChunker initialized for bucket: {bucket_name}, temp_dir: {self.temp_dir}")

    def get_video_metadata(self, s3_key: str) -> Dict[str, Any]:
        """
        Extract video metadata (duration, format, dimensions) from S3 video.

        Args:
            s3_key: S3 key of the video file

        Returns:
            Dict with video metadata (duration, format, width, height, fps, codec)
        """
        temp_file = None
        try:
            # Download video to temp file for ffprobe analysis
            temp_file = os.path.join(self.temp_dir, f"temp_video_{os.urandom(8).hex()}.mp4")

            logger.info(f"Downloading video from S3 for metadata extraction: {s3_key}")
            self.s3_client.download_file(self.bucket_name, s3_key, temp_file)

            # Use ffprobe to extract metadata
            probe = ffmpeg.probe(temp_file)

            # Find video stream
            video_stream = next(
                (stream for stream in probe['streams'] if stream['codec_type'] == 'video'),
                None
            )

            if not video_stream:
                raise VideoChunkerError("No video stream found in file")

            # Extract duration (prefer container duration, fallback to stream duration)
            duration = float(probe['format'].get('duration', 0))
            if duration == 0 and 'duration' in video_stream:
                duration = float(video_stream['duration'])

            # Extract frame rate
            fps_str = video_stream.get('r_frame_rate', '30/1')
            fps_parts = fps_str.split('/')
            fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else 30.0

            metadata = {
                'duration_seconds': round(duration, 2),
                'format': probe['format'].get('format_name', 'unknown'),
                'width': int(video_stream.get('width', 0)),
                'height': int(video_stream.get('height', 0)),
                'fps': round(fps, 2),
                'codec': video_stream.get('codec_name', 'unknown'),
                'bitrate': int(probe['format'].get('bit_rate', 0)),
                'size_bytes': int(probe['format'].get('size', 0))
            }

            logger.info(f"Video metadata: {metadata}")
            return metadata

        except ffmpeg.Error as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            raise VideoChunkerError(f"FFmpeg error during metadata extraction: {error_msg}")
        except ClientError as e:
            raise VideoChunkerError(f"S3 error downloading video: {str(e)}")
        except Exception as e:
            raise VideoChunkerError(f"Failed to extract video metadata: {str(e)}")
        finally:
            # Clean up temp file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as e:
                    logger.warning(f"Failed to remove temp file {temp_file}: {e}")

    def calculate_chunk_parameters(self, model: str, video_duration: float) -> Dict[str, Any]:
        """
        Calculate optimal chunk size and overlap for given model and video duration.

        Args:
            model: Nova model name ('micro', 'lite', 'pro', 'premier')
            video_duration: Video duration in seconds

        Returns:
            Dict with chunk_duration, overlap, max_duration, and estimated chunk count
        """
        if model not in self.CHUNK_CONFIGS:
            raise VideoChunkerError(f"Invalid model: {model}. Choose from: {list(self.CHUNK_CONFIGS.keys())}")

        config = self.CHUNK_CONFIGS[model]
        chunk_duration = config['chunk_duration']
        overlap = int(chunk_duration * config['overlap_pct'])
        max_duration = config['max_duration']

        # Calculate estimated number of chunks
        if video_duration <= max_duration:
            num_chunks = 1
        else:
            # Account for overlap in chunk count calculation
            effective_chunk_duration = chunk_duration - overlap
            num_chunks = max(1, int((video_duration - overlap) / effective_chunk_duration) + 1)

        return {
            'chunk_duration': chunk_duration,
            'overlap': overlap,
            'max_duration': max_duration,
            'estimated_chunks': num_chunks,
            'video_duration': video_duration
        }

    def generate_chunk_boundaries(self, video_duration: float, model: str) -> List[Dict[str, Any]]:
        """
        Generate chunk boundaries with overlap for long video processing.

        Args:
            video_duration: Total video duration in seconds
            model: Nova model name

        Returns:
            List of chunk dictionaries with timing information
        """
        params = self.calculate_chunk_parameters(model, video_duration)

        # If video fits in single chunk, return single chunk covering entire duration
        if video_duration <= params['max_duration']:
            return [{
                'index': 0,
                'core_start': 0,
                'core_end': video_duration,
                'overlap_start': 0,
                'overlap_end': video_duration,
                'duration': video_duration
            }]

        chunk_duration = params['chunk_duration']
        overlap = params['overlap']
        chunks = []
        start = 0
        chunk_index = 0

        while start < video_duration:
            # Calculate core chunk boundaries (non-overlapping portion)
            end = min(start + chunk_duration, video_duration)

            # Add overlap to both sides (except first/last)
            overlap_start = max(0, start - overlap) if chunk_index > 0 else 0
            overlap_end = min(video_duration, end + overlap) if end < video_duration else video_duration

            chunk = {
                'index': chunk_index,
                'core_start': start,
                'core_end': end,
                'overlap_start': overlap_start,
                'overlap_end': overlap_end,
                'duration': overlap_end - overlap_start
            }

            chunks.append(chunk)
            chunk_index += 1
            start = end  # Next chunk starts where this one's core ends

        logger.info(f"Generated {len(chunks)} chunks for {video_duration}s video with model {model}")
        return chunks

    def extract_video_segment(
        self,
        s3_key: str,
        start_time: float,
        end_time: float,
        output_s3_key: str
    ) -> str:
        """
        Extract a segment from video file and upload to S3.

        Args:
            s3_key: Source video S3 key
            start_time: Segment start time in seconds
            end_time: Segment end time in seconds
            output_s3_key: Destination S3 key for chunk

        Returns:
            S3 key of the uploaded chunk
        """
        temp_input = None
        temp_output = None

        try:
            # Download source video to temp file
            temp_input = os.path.join(self.temp_dir, f"input_{os.urandom(8).hex()}.mp4")
            logger.info(f"Downloading source video from S3: {s3_key}")
            self.s3_client.download_file(self.bucket_name, s3_key, temp_input)

            # Create temp output file
            temp_output = os.path.join(self.temp_dir, f"output_{os.urandom(8).hex()}.mp4")

            # Extract segment using FFmpeg
            duration = end_time - start_time
            logger.info(f"Extracting segment: {start_time}s to {end_time}s (duration: {duration}s)")

            stream = ffmpeg.input(temp_input, ss=start_time, t=duration)
            stream = ffmpeg.output(
                stream,
                temp_output,
                codec='copy',  # Copy streams without re-encoding (fast)
                avoid_negative_ts='make_zero',  # Handle timestamp issues
                loglevel='error'
            )
            ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)

            if not os.path.exists(temp_output):
                raise VideoChunkerError("Video segment extraction failed - output file not created")

            # Upload chunk to S3
            logger.info(f"Uploading chunk to S3: {output_s3_key}")
            self.s3_client.upload_file(
                temp_output,
                self.bucket_name,
                output_s3_key,
                ExtraArgs={'ContentType': 'video/mp4'}
            )

            # Verify upload
            chunk_size = os.path.getsize(temp_output)
            logger.info(f"Chunk uploaded successfully: {output_s3_key} ({chunk_size} bytes)")

            return output_s3_key

        except ffmpeg.Error as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            raise VideoChunkerError(f"FFmpeg error during segment extraction: {error_msg}")
        except ClientError as e:
            raise VideoChunkerError(f"S3 error during chunk processing: {str(e)}")
        except Exception as e:
            raise VideoChunkerError(f"Failed to extract video segment: {str(e)}")
        finally:
            # Clean up temp files
            for temp_file in [temp_input, temp_output]:
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        logger.debug(f"Cleaned up temp file: {temp_file}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temp file {temp_file}: {e}")

    def delete_chunk(self, s3_key: str) -> bool:
        """
        Delete chunk file from S3.

        Args:
            s3_key: S3 key of the chunk to delete

        Returns:
            True if successful
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=s3_key
            )
            logger.info(f"Deleted chunk from S3: {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete chunk {s3_key}: {e}")
            return False

    def needs_chunking(self, video_duration: float, model: str) -> bool:
        """
        Determine if video requires chunking for given model.

        Args:
            video_duration: Video duration in seconds
            model: Nova model name

        Returns:
            True if chunking is required, False otherwise
        """
        if model not in self.CHUNK_CONFIGS:
            raise VideoChunkerError(f"Invalid model: {model}")

        max_duration = self.CHUNK_CONFIGS[model]['max_duration']
        return video_duration > max_duration

    def get_chunk_s3_key(self, source_s3_key: str, chunk_index: int) -> str:
        """
        Generate S3 key for chunk file.

        Args:
            source_s3_key: Original video S3 key
            chunk_index: Chunk index number

        Returns:
            S3 key for chunk file
        """
        # Extract base name without extension
        base_name = Path(source_s3_key).stem

        # Generate chunk key in temp/chunks/ folder
        chunk_key = f"temp/chunks/{base_name}_chunk_{chunk_index:03d}.mp4"
        return chunk_key
