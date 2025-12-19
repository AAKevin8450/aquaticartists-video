"""
Media metadata extraction utility using FFprobe.
Extracts resolution, frame rate, codec, duration, bitrate from video/image files.
"""
import json
import subprocess
import shutil
from typing import Dict, Any, Optional
from pathlib import Path


class MediaMetadataError(Exception):
    """Exception raised for media metadata extraction errors."""
    pass


def extract_media_metadata(file_path: str) -> Dict[str, Any]:
    """
    Extract comprehensive media metadata from a video or image file using FFprobe.

    Args:
        file_path: Path to the media file

    Returns:
        Dictionary containing:
        - resolution_width: int (video width in pixels)
        - resolution_height: int (video height in pixels)
        - frame_rate: float (frames per second)
        - codec_video: str (video codec name)
        - codec_audio: str (audio codec name, None if no audio)
        - duration_seconds: float (duration in seconds)
        - bitrate: int (bitrate in bits per second)

    Raises:
        MediaMetadataError: If FFprobe is not available or extraction fails
    """
    if not shutil.which('ffprobe'):
        raise MediaMetadataError("ffprobe is not available on the system")

    file_path = str(Path(file_path).absolute())

    if not Path(file_path).exists():
        raise MediaMetadataError(f"File not found: {file_path}")

    # Build FFprobe command to extract all metadata as JSON
    command = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        file_path
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
    except subprocess.CalledProcessError as e:
        raise MediaMetadataError(f"FFprobe failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        raise MediaMetadataError("FFprobe timed out")
    except Exception as e:
        raise MediaMetadataError(f"FFprobe execution error: {str(e)}")

    try:
        probe_data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise MediaMetadataError(f"Failed to parse FFprobe output: {e}")

    # Extract metadata from probe data
    metadata = {
        'resolution_width': None,
        'resolution_height': None,
        'frame_rate': None,
        'codec_video': None,
        'codec_audio': None,
        'duration_seconds': None,
        'bitrate': None
    }

    # Extract format-level metadata
    format_info = probe_data.get('format', {})
    if 'duration' in format_info:
        try:
            metadata['duration_seconds'] = float(format_info['duration'])
        except (ValueError, TypeError):
            pass

    if 'bit_rate' in format_info:
        try:
            metadata['bitrate'] = int(format_info['bit_rate'])
        except (ValueError, TypeError):
            pass

    # Extract stream-level metadata
    streams = probe_data.get('streams', [])

    # Find video stream
    video_stream = None
    audio_stream = None

    for stream in streams:
        codec_type = stream.get('codec_type', '')

        if codec_type == 'video' and not video_stream:
            video_stream = stream
        elif codec_type == 'audio' and not audio_stream:
            audio_stream = stream

    # Extract video metadata
    if video_stream:
        # Resolution
        if 'width' in video_stream:
            try:
                metadata['resolution_width'] = int(video_stream['width'])
            except (ValueError, TypeError):
                pass

        if 'height' in video_stream:
            try:
                metadata['resolution_height'] = int(video_stream['height'])
            except (ValueError, TypeError):
                pass

        # Frame rate (parse "30/1" or "30000/1001" format)
        if 'r_frame_rate' in video_stream:
            try:
                frame_rate_str = video_stream['r_frame_rate']
                if '/' in frame_rate_str:
                    num, den = frame_rate_str.split('/')
                    if int(den) != 0:
                        metadata['frame_rate'] = float(num) / float(den)
                else:
                    metadata['frame_rate'] = float(frame_rate_str)
            except (ValueError, TypeError, ZeroDivisionError):
                # Fallback to avg_frame_rate
                if 'avg_frame_rate' in video_stream:
                    try:
                        avg_frame_rate_str = video_stream['avg_frame_rate']
                        if '/' in avg_frame_rate_str:
                            num, den = avg_frame_rate_str.split('/')
                            if int(den) != 0:
                                metadata['frame_rate'] = float(num) / float(den)
                        else:
                            metadata['frame_rate'] = float(avg_frame_rate_str)
                    except (ValueError, TypeError, ZeroDivisionError):
                        pass

        # Video codec
        if 'codec_name' in video_stream:
            metadata['codec_video'] = video_stream['codec_name']

    # Extract audio metadata
    if audio_stream:
        if 'codec_name' in audio_stream:
            metadata['codec_audio'] = audio_stream['codec_name']

    return metadata


def format_media_metadata(metadata: Dict[str, Any]) -> str:
    """
    Format media metadata as a human-readable string.

    Args:
        metadata: Dictionary from extract_media_metadata()

    Returns:
        Formatted string like "1920x1080 @ 30fps, h264/aac, 120.5s, 5000kbps"
    """
    parts = []

    # Resolution
    if metadata.get('resolution_width') and metadata.get('resolution_height'):
        parts.append(f"{metadata['resolution_width']}x{metadata['resolution_height']}")

    # Frame rate
    if metadata.get('frame_rate'):
        parts.append(f"@ {metadata['frame_rate']:.1f}fps")

    # Codecs
    codecs = []
    if metadata.get('codec_video'):
        codecs.append(metadata['codec_video'])
    if metadata.get('codec_audio'):
        codecs.append(metadata['codec_audio'])
    if codecs:
        parts.append('/'.join(codecs))

    # Duration
    if metadata.get('duration_seconds'):
        parts.append(f"{metadata['duration_seconds']:.1f}s")

    # Bitrate
    if metadata.get('bitrate'):
        bitrate_kbps = metadata['bitrate'] / 1000
        parts.append(f"{bitrate_kbps:.0f}kbps")

    return ', '.join(parts)


def get_video_resolution(file_path: str) -> tuple[Optional[int], Optional[int]]:
    """
    Quick utility to get just resolution (width, height) from a video file.

    Args:
        file_path: Path to the video file

    Returns:
        Tuple of (width, height) or (None, None) if extraction fails
    """
    try:
        metadata = extract_media_metadata(file_path)
        return (metadata.get('resolution_width'), metadata.get('resolution_height'))
    except MediaMetadataError:
        return (None, None)


def get_video_duration(file_path: str) -> Optional[float]:
    """
    Quick utility to get just duration from a video file.

    Args:
        file_path: Path to the video file

    Returns:
        Duration in seconds or None if extraction fails
    """
    try:
        metadata = extract_media_metadata(file_path)
        return metadata.get('duration_seconds')
    except MediaMetadataError:
        return None


def verify_proxy_spec(file_path: str, expected_height: int = 720, expected_fps: float = 15.0) -> bool:
    """
    Verify that a proxy video meets the expected specifications.

    Args:
        file_path: Path to the proxy video file
        expected_height: Expected video height (default: 720)
        expected_fps: Expected frame rate (default: 15.0)

    Returns:
        True if proxy meets specifications, False otherwise
    """
    try:
        metadata = extract_media_metadata(file_path)

        # Check height (width varies due to aspect ratio preservation)
        if metadata.get('resolution_height') != expected_height:
            return False

        # Check frame rate (allow 1 fps tolerance for floating point comparison)
        if metadata.get('frame_rate'):
            if abs(metadata['frame_rate'] - expected_fps) > 1.0:
                return False

        return True
    except MediaMetadataError:
        return False
