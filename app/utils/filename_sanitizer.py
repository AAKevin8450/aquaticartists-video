"""
Filename sanitization utility for S3 batch processing.
Converts filenames with special characters to safe versions.
"""
import re
import unicodedata


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename for safe S3 batch processing.

    Transformations applied in order:
    1. Normalize unicode characters to ASCII equivalents
    2. Replace spaces with underscores
    3. Remove special characters: , ( ) [ ] { } ! @ # $ % ^ & * + = | \ : ; " ' < > ?
    4. Collapse multiple consecutive underscores to single underscore
    5. Remove leading/trailing underscores
    6. Preserve file extension

    Args:
        filename: Original filename
            Example: "Video Nov 14 2025, 10 02 14 AM_22153_720p15.mov"

    Returns:
        Sanitized filename
            Example: "Video_Nov_14_2025_10_02_14_AM_22153_720p15.mov"
    """
    # Separate extension from name
    if '.' in filename:
        name, ext = filename.rsplit('.', 1)
    else:
        name, ext = filename, ''

    # Step 1: Normalize unicode to ASCII
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')

    # Step 2: Replace spaces with underscores
    name = name.replace(' ', '_')

    # Step 3: Remove special characters (keep alphanumeric, underscore, hyphen)
    name = re.sub(r'[,\(\)\[\]\{\}!@#$%^&*+=|\\:;"\'<>?]', '', name)

    # Step 4: Collapse multiple underscores to single
    name = re.sub(r'_+', '_', name)

    # Step 5: Remove leading/trailing underscores
    name = name.strip('_')

    # Reconstruct with extension
    if ext:
        return f"{name}.{ext}"
    return name


def sanitize_s3_key(s3_key: str) -> str:
    """
    Sanitize an S3 key, preserving the directory structure.
    Only the filename portion is sanitized, not the path.

    Args:
        s3_key: Full S3 key
            Example: "proxy_video/Video Nov 14 2025, 10 02 14 AM_22153_720p15.mov"

    Returns:
        Sanitized S3 key
            Example: "proxy_video/Video_Nov_14_2025_10_02_14_AM_22153_720p15.mov"
    """
    if '/' in s3_key:
        directory, filename = s3_key.rsplit('/', 1)
        return f"{directory}/{sanitize_filename(filename)}"
    return sanitize_filename(s3_key)


def needs_sanitization(filename: str) -> bool:
    """
    Check if a filename contains characters that need sanitization.

    Args:
        filename: Filename to check

    Returns:
        True if the filename contains special characters that need sanitization
    """
    # Check for spaces or special characters
    special_chars = r'[ ,\(\)\[\]\{\}!@#$%^&*+=|\\:;"\'<>?]'
    return bool(re.search(special_chars, filename))
