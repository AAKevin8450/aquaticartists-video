"""
Image proxy service for Nova 2 Lite optimization.

Creates optimized image proxies at 896px shorter side for AWS Nova analysis,
reducing S3 storage costs, network transfer time, and API payload sizes.
"""
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)

# Nova 2 Lite specifications
NOVA_MIN_DIMENSION = 896  # Minimum rescale threshold for Nova 2 Lite
DEFAULT_JPEG_QUALITY = 85  # Optimal balance of size vs quality


class ImageProxyError(Exception):
    """Exception raised for image proxy creation errors."""
    pass


class ImageProxyService:
    """Service for creating optimized image proxies for Nova 2 Lite analysis."""

    def __init__(self, target_dimension: int = NOVA_MIN_DIMENSION, jpeg_quality: int = DEFAULT_JPEG_QUALITY):
        """
        Initialize the image proxy service.

        Args:
            target_dimension: Target dimension for shorter side (default 896px)
            jpeg_quality: JPEG compression quality (1-100, default 85)
        """
        self.target_dimension = target_dimension
        self.jpeg_quality = jpeg_quality

    def needs_proxy(self, width: int, height: int) -> bool:
        """
        Determine if an image needs a proxy based on its dimensions.

        Args:
            width: Image width in pixels
            height: Image height in pixels

        Returns:
            True if shorter side > target_dimension (default 896px)
        """
        shorter_side = min(width, height)
        return shorter_side > self.target_dimension

    def calculate_target_dimensions(self, width: int, height: int) -> Tuple[int, int]:
        """
        Calculate target dimensions maintaining aspect ratio.

        Rules:
        1. If shorter side > 896px: Scale down so shorter side = 896px
        2. If shorter side <= 896px: Keep original dimensions (no upscaling)

        Args:
            width: Original width in pixels
            height: Original height in pixels

        Returns:
            Tuple of (new_width, new_height)
        """
        shorter_side = min(width, height)

        if shorter_side <= self.target_dimension:
            # No resize needed - keep original
            return (width, height)

        # Calculate scale factor to make shorter side = target
        scale = self.target_dimension / shorter_side
        new_width = int(width * scale)
        new_height = int(height * scale)

        return (new_width, new_height)

    def get_optimal_format(self, source_path: str) -> str:
        """
        Determine optimal output format based on image content.

        - PNG for images with transparency (RGBA, LA, P modes)
        - JPEG for photographic content (RGB)

        Args:
            source_path: Path to source image

        Returns:
            'JPEG' or 'PNG'
        """
        try:
            with Image.open(source_path) as img:
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Check if P mode actually has transparency
                    if img.mode == 'P' and 'transparency' in img.info:
                        return 'PNG'
                    elif img.mode in ('RGBA', 'LA'):
                        return 'PNG'
                return 'JPEG'
        except Exception as e:
            logger.warning(f"Could not determine format for {source_path}: {e}")
            return 'JPEG'

    def get_image_dimensions(self, source_path: str) -> Tuple[int, int]:
        """
        Get image dimensions without loading full image data.

        Args:
            source_path: Path to image file

        Returns:
            Tuple of (width, height)

        Raises:
            ImageProxyError: If image cannot be read
        """
        try:
            with Image.open(source_path) as img:
                return img.size
        except Exception as e:
            raise ImageProxyError(f"Failed to read image dimensions: {e}")

    def create_proxy(
        self,
        source_path: str,
        output_path: Optional[str] = None,
        output_format: Optional[str] = None,
        quality: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create an optimized proxy image for Nova 2 Lite.

        Args:
            source_path: Path to source image
            output_path: Path for output proxy (auto-generated if not provided)
            output_format: Force output format ('JPEG' or 'PNG'), auto-detect if None
            quality: JPEG quality (1-100), uses instance default if None

        Returns:
            Dict with proxy details:
            {
                'proxy_path': str,
                'original_dimensions': (width, height),
                'proxy_dimensions': (width, height),
                'original_size_bytes': int,
                'proxy_size_bytes': int,
                'savings_percent': float,
                'format': str,
                'was_resized': bool
            }

        Raises:
            ImageProxyError: If proxy creation fails
        """
        source_path = str(source_path)

        if not os.path.isfile(source_path):
            raise ImageProxyError(f"Source file not found: {source_path}")

        original_size = os.path.getsize(source_path)
        quality = quality or self.jpeg_quality

        try:
            with Image.open(source_path) as img:
                original_dimensions = img.size
                width, height = original_dimensions

                # Determine output format
                if output_format is None:
                    output_format = self.get_optimal_format(source_path)

                # Calculate target dimensions
                new_width, new_height = self.calculate_target_dimensions(width, height)
                was_resized = (new_width, new_height) != original_dimensions

                # Generate output path if not provided
                if output_path is None:
                    ext = '.jpg' if output_format == 'JPEG' else '.png'
                    source_stem = Path(source_path).stem
                    output_path = str(Path(source_path).parent / f"{source_stem}_nova{ext}")

                # Ensure output directory exists
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)

                # Process image
                if was_resized:
                    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                else:
                    img_resized = img.copy()

                # Convert mode for JPEG output
                if output_format == 'JPEG':
                    if img_resized.mode in ('RGBA', 'LA', 'P'):
                        # Convert to RGB, handling transparency
                        if img_resized.mode == 'P':
                            img_resized = img_resized.convert('RGBA')
                        background = Image.new('RGB', img_resized.size, (255, 255, 255))
                        if img_resized.mode in ('RGBA', 'LA'):
                            # Handle both RGBA and LA modes
                            if img_resized.mode == 'LA':
                                img_resized = img_resized.convert('RGBA')
                            background.paste(img_resized, mask=img_resized.split()[-1])
                            img_resized = background
                        else:
                            img_resized = img_resized.convert('RGB')
                    elif img_resized.mode != 'RGB':
                        img_resized = img_resized.convert('RGB')

                # Save with optimization
                if output_format == 'JPEG':
                    img_resized.save(output_path, format='JPEG', quality=quality, optimize=True)
                else:
                    img_resized.save(output_path, format='PNG', optimize=True)

                img_resized.close()

                proxy_size = os.path.getsize(output_path)
                savings_percent = ((original_size - proxy_size) / original_size * 100) if original_size > 0 else 0

                logger.info(
                    f"Created image proxy: {Path(source_path).name} -> {Path(output_path).name} "
                    f"({original_dimensions[0]}x{original_dimensions[1]} -> {new_width}x{new_height}, "
                    f"{savings_percent:.1f}% size reduction)"
                )

                return {
                    'proxy_path': output_path,
                    'original_dimensions': original_dimensions,
                    'proxy_dimensions': (new_width, new_height),
                    'original_size_bytes': original_size,
                    'proxy_size_bytes': proxy_size,
                    'savings_percent': round(savings_percent, 1),
                    'format': output_format,
                    'was_resized': was_resized
                }

        except ImageProxyError:
            raise
        except Exception as e:
            logger.error(f"Failed to create image proxy for {source_path}: {e}")
            raise ImageProxyError(f"Failed to create image proxy: {e}")


def create_image_proxy_service(
    target_dimension: int = NOVA_MIN_DIMENSION,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY
) -> ImageProxyService:
    """
    Factory function to create an ImageProxyService instance.

    Args:
        target_dimension: Target dimension for shorter side (default 896px)
        jpeg_quality: JPEG compression quality (1-100, default 85)

    Returns:
        Configured ImageProxyService instance
    """
    return ImageProxyService(target_dimension, jpeg_quality)


def build_image_proxy_filename(source_filename: str, source_file_id: int) -> str:
    """
    Build proxy filename following project conventions.

    Pattern: {original_stem}_{source_file_id}_nova.{ext}

    Args:
        source_filename: Original filename
        source_file_id: Source file database ID

    Returns:
        Proxy filename string
    """
    name_parts = Path(source_filename)
    # Use original extension or default to .jpg
    ext = name_parts.suffix.lower()
    if ext not in ('.jpg', '.jpeg', '.png'):
        ext = '.jpg'
    return f"{name_parts.stem}_{source_file_id}_nova{ext}"
