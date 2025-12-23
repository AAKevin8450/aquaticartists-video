"""
Formatting utilities for display and conversion.
"""
from datetime import datetime, timedelta
from typing import Optional, Any

# Try to import zoneinfo, fall back to manual offset if not available
try:
    from zoneinfo import ZoneInfo
    ZONEINFO_AVAILABLE = True
except ImportError:
    ZONEINFO_AVAILABLE = False


def format_timestamp(timestamp: Optional[str], timezone: str = 'America/New_York') -> str:
    """
    Format ISO timestamp to human-readable string in specified timezone.

    Args:
        timestamp: ISO format timestamp string (UTC)
        timezone: Target timezone (default: Eastern Time)

    Returns:
        Formatted timestamp string in ET with timezone indicator
    """
    if not timestamp:
        return 'N/A'

    try:
        # Parse ISO format (assume UTC if no timezone specified)
        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = timestamp

        # Convert to Eastern Time
        if ZONEINFO_AVAILABLE:
            try:
                et_tz = ZoneInfo(timezone)
                dt_et = dt.astimezone(et_tz)
                return dt_et.strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                # Fallback if timezone not found
                pass

        # Fallback: Manual EST/EDT offset with DST handling
        # Determine if DST is in effect (EDT: UTC-4, EST: UTC-5)
        # DST typically runs from 2nd Sunday in March to 1st Sunday in November
        month = dt.month
        day = dt.day

        # Simple DST check: March-November is typically EDT (UTC-4)
        # More precise: 2nd Sunday March through 1st Sunday November
        if month > 3 and month < 11:
            # Definitely EDT
            offset_hours = 4
        elif month == 3:
            # Check if after 2nd Sunday in March
            # DST starts at 2 AM on 2nd Sunday
            second_sunday = (14 - (5 * 1 - day - 1) % 7)
            if day >= second_sunday:
                offset_hours = 4
            else:
                offset_hours = 5
        elif month == 11:
            # Check if before 1st Sunday in November
            # DST ends at 2 AM on 1st Sunday
            first_sunday = (7 - (5 * 1 - day - 1) % 7)
            if day < first_sunday:
                offset_hours = 4
            else:
                offset_hours = 5
        else:
            # December, January, February - EST
            offset_hours = 5

        dt_et = dt - timedelta(hours=offset_hours)
        return dt_et.strftime('%Y-%m-%d %H:%M:%S')

    except (ValueError, AttributeError) as e:
        # If parsing fails, return original
        return str(timestamp)


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in bytes to human-readable string.

    Args:
        size_bytes: File size in bytes

    Returns:
        Formatted size string (e.g., "1.5 MB")
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_confidence(confidence: float) -> str:
    """
    Format confidence value as percentage.

    Args:
        confidence: Confidence value (0-100)

    Returns:
        Formatted percentage string (e.g., "95.3%")
    """
    return f"{confidence:.1f}%"


def format_duration(duration_seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.

    Args:
        duration_seconds: Duration in seconds (can be float or int)

    Returns:
        Formatted duration string (e.g., "2h 15m", "1m 30s", "45s")
    """
    if duration_seconds < 0:
        return '0s'

    total_seconds = int(duration_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        if minutes > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{hours}h"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


def truncate_text(text: str, max_length: int = 100, suffix: str = '...') -> str:
    """
    Truncate text to maximum length.

    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated

    Returns:
        Truncated text
    """
    if not text:
        return ''

    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


def format_job_status(status: str) -> dict:
    """
    Format job status with display information.

    Args:
        status: Job status string

    Returns:
        Dictionary with status, label, and CSS class
    """
    status_map = {
        'SUBMITTED': {
            'label': 'Submitted',
            'class': 'badge bg-secondary',
            'icon': 'bi-clock'
        },
        'IN_PROGRESS': {
            'label': 'In Progress',
            'class': 'badge bg-primary',
            'icon': 'bi-arrow-repeat'
        },
        'COMPLETED': {
            'label': 'Completed',
            'class': 'badge bg-success',
            'icon': 'bi-check-circle'
        },
        'SUCCEEDED': {
            'label': 'Completed',
            'class': 'badge bg-success',
            'icon': 'bi-check-circle'
        },
        'FAILED': {
            'label': 'Failed',
            'class': 'badge bg-danger',
            'icon': 'bi-x-circle'
        }
    }

    return status_map.get(status, {
        'label': status,
        'class': 'badge bg-secondary',
        'icon': 'bi-question-circle'
    })


def format_analysis_type(analysis_type: str) -> str:
    """
    Format analysis type for display.

    Args:
        analysis_type: Analysis type code

    Returns:
        Formatted display name
    """
    type_map = {
        'nova': 'Nova Video Understanding',
        'video_labels': 'Video Label Detection',
        'video_faces': 'Video Face Detection',
        'video_face_search': 'Video Face Search',
        'video_persons': 'Video Person Tracking',
        'video_celebrities': 'Video Celebrity Recognition',
        'video_moderation': 'Video Content Moderation',
        'video_text': 'Video Text Detection',
        'video_segments': 'Video Segment Detection',
        'image_labels': 'Image Label Detection',
        'image_faces': 'Image Face Detection',
        'image_face_compare': 'Image Face Comparison',
        'image_celebrities': 'Image Celebrity Recognition',
        'image_moderation': 'Image Content Moderation',
        'image_text': 'Image Text Detection',
        'image_ppe': 'Image PPE Detection',
        'image_custom_labels': 'Image Custom Labels'
    }

    return type_map.get(analysis_type, analysis_type.replace('_', ' ').title())


def format_video_metadata(metadata: dict) -> dict:
    """
    Format video metadata for display.

    Args:
        metadata: Video metadata dictionary

    Returns:
        Formatted metadata dictionary
    """
    formatted = {}

    if metadata.get('duration_millis'):
        formatted['duration'] = format_duration(metadata['duration_millis'])

    if metadata.get('frame_rate'):
        formatted['frame_rate'] = f"{metadata['frame_rate']:.1f} fps"

    if metadata.get('frame_width') and metadata.get('frame_height'):
        formatted['resolution'] = f"{metadata['frame_width']}x{metadata['frame_height']}"

    if metadata.get('codec'):
        formatted['codec'] = metadata['codec']

    if metadata.get('format'):
        formatted['format'] = metadata['format']

    return formatted


def format_label_hierarchy(label_name: str, parents: list) -> str:
    """
    Format label with parent hierarchy.

    Args:
        label_name: Label name
        parents: List of parent label names

    Returns:
        Formatted hierarchy string (e.g., "Animal > Mammal > Dog")
    """
    if not parents:
        return label_name

    hierarchy = [p.get('Name', '') for p in parents if p.get('Name')]
    hierarchy.append(label_name)

    return ' > '.join(hierarchy)


def format_bounding_box(box: dict, image_width: int = 100, image_height: int = 100) -> dict:
    """
    Format bounding box coordinates for display.

    Args:
        box: Bounding box dict with Width, Height, Left, Top (0-1 scale)
        image_width: Image width in pixels
        image_height: Image height in pixels

    Returns:
        Dictionary with pixel coordinates
    """
    return {
        'left': int(box.get('Left', 0) * image_width),
        'top': int(box.get('Top', 0) * image_height),
        'width': int(box.get('Width', 0) * image_width),
        'height': int(box.get('Height', 0) * image_height)
    }


def format_emotions(emotions: list) -> str:
    """
    Format emotion list to string.

    Args:
        emotions: List of emotion dictionaries

    Returns:
        Comma-separated emotion string with confidence
    """
    if not emotions:
        return 'None detected'

    # Sort by confidence descending
    sorted_emotions = sorted(emotions, key=lambda e: e.get('Confidence', 0), reverse=True)

    # Take top 3
    top_emotions = sorted_emotions[:3]

    formatted = [
        f"{e.get('Type', 'Unknown')} ({e.get('Confidence', 0):.0f}%)"
        for e in top_emotions
    ]

    return ', '.join(formatted)


def pluralize(count: int, singular: str, plural: str = None) -> str:
    """
    Pluralize a word based on count.

    Args:
        count: Count value
        singular: Singular form
        plural: Plural form (defaults to singular + 's')

    Returns:
        Pluralized string with count
    """
    if plural is None:
        plural = singular + 's'

    word = singular if count == 1 else plural
    return f"{count} {word}"
