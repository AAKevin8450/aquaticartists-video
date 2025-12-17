"""
Validation utilities for file uploads and inputs.
"""
import re
from pathlib import Path
from werkzeug.utils import secure_filename as werkzeug_secure_filename
from typing import Set, Optional


class ValidationError(Exception):
    """Validation error exception."""
    pass


def validate_file_type(filename: str, allowed_extensions: Set[str]) -> bool:
    """
    Validate file extension.

    Args:
        filename: Filename to validate
        allowed_extensions: Set of allowed extensions (without dot)

    Returns:
        True if valid

    Raises:
        ValidationError if invalid
    """
    if not filename or '.' not in filename:
        raise ValidationError("Filename must have an extension")

    ext = Path(filename).suffix.lstrip('.').lower()
    if ext not in allowed_extensions:
        raise ValidationError(
            f"Invalid file type '.{ext}'. Allowed types: {', '.join(sorted(allowed_extensions))}"
        )
    return True


def validate_file_size(size_bytes: int, max_size_mb: int) -> bool:
    """
    Validate file size.

    Args:
        size_bytes: File size in bytes
        max_size_mb: Maximum allowed size in MB

    Returns:
        True if valid

    Raises:
        ValidationError if too large
    """
    max_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise ValidationError(
            f"File size ({size_bytes / 1024 / 1024:.1f} MB) exceeds maximum "
            f"allowed size ({max_size_mb} MB)"
        )
    return True


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename for safe storage.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename
    """
    # Use werkzeug's secure_filename
    safe_name = werkzeug_secure_filename(filename)

    # Additional sanitization
    # Remove any remaining unsafe characters
    safe_name = re.sub(r'[^\w\s\-\.]', '', safe_name)

    # Collapse multiple spaces/dashes
    safe_name = re.sub(r'[\s\-]+', '_', safe_name)

    # Ensure not empty
    if not safe_name or safe_name == '.':
        raise ValidationError("Filename cannot be empty after sanitization")

    return safe_name


def validate_s3_key(s3_key: str) -> bool:
    """
    Validate S3 key format.

    Args:
        s3_key: S3 key to validate

    Returns:
        True if valid

    Raises:
        ValidationError if invalid
    """
    if not s3_key:
        raise ValidationError("S3 key cannot be empty")

    # S3 key length limits
    if len(s3_key) > 1024:
        raise ValidationError("S3 key exceeds maximum length (1024 characters)")

    # Check for invalid characters
    invalid_chars = ['\\', '{', '}', '^', '%', '`', '[', ']', '"', '>', '<', '~', '#', '|']
    for char in invalid_chars:
        if char in s3_key:
            raise ValidationError(f"S3 key contains invalid character: {char}")

    return True


def validate_confidence(confidence: float) -> bool:
    """
    Validate confidence threshold value.

    Args:
        confidence: Confidence value to validate

    Returns:
        True if valid

    Raises:
        ValidationError if invalid
    """
    if not (0 <= confidence <= 100):
        raise ValidationError("Confidence must be between 0 and 100")
    return True


def validate_collection_id(collection_id: str) -> bool:
    """
    Validate Rekognition collection ID format.

    Args:
        collection_id: Collection ID to validate

    Returns:
        True if valid

    Raises:
        ValidationError if invalid
    """
    if not collection_id:
        raise ValidationError("Collection ID cannot be empty")

    # Collection ID must be alphanumeric, hyphens, underscores, periods
    if not re.match(r'^[a-zA-Z0-9_.\-]+$', collection_id):
        raise ValidationError(
            "Collection ID can only contain alphanumeric characters, "
            "hyphens, underscores, and periods"
        )

    # Length limits (1-255 characters)
    if not (1 <= len(collection_id) <= 255):
        raise ValidationError("Collection ID must be between 1 and 255 characters")

    return True


def validate_job_id(job_id: str) -> bool:
    """
    Validate Rekognition job ID format.

    Args:
        job_id: Job ID to validate

    Returns:
        True if valid

    Raises:
        ValidationError if invalid
    """
    if not job_id:
        raise ValidationError("Job ID cannot be empty")

    # Job IDs are typically UUID-like strings
    if not re.match(r'^[a-zA-Z0-9\-]+$', job_id):
        raise ValidationError("Job ID contains invalid characters")

    return True


def validate_analysis_type(analysis_type: str, allowed_types: Set[str]) -> bool:
    """
    Validate analysis type.

    Args:
        analysis_type: Analysis type to validate
        allowed_types: Set of allowed analysis types

    Returns:
        True if valid

    Raises:
        ValidationError if invalid
    """
    if analysis_type not in allowed_types:
        raise ValidationError(
            f"Invalid analysis type '{analysis_type}'. "
            f"Allowed types: {', '.join(sorted(allowed_types))}"
        )
    return True


def get_file_type(filename: str, video_extensions: Set[str], image_extensions: Set[str]) -> str:
    """
    Determine if file is video or image based on extension.

    Args:
        filename: Filename to check
        video_extensions: Set of video extensions
        image_extensions: Set of image extensions

    Returns:
        'video' or 'image'

    Raises:
        ValidationError if extension not recognized
    """
    ext = Path(filename).suffix.lstrip('.').lower()

    if ext in video_extensions:
        return 'video'
    elif ext in image_extensions:
        return 'image'
    else:
        raise ValidationError(
            f"Unrecognized file extension '.{ext}'. "
            f"Supported: {', '.join(sorted(video_extensions | image_extensions))}"
        )
