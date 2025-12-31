"""
AWS Nova image analysis service using Amazon Bedrock.
Provides intelligent image comprehension including descriptions, visual elements, and metadata extraction.
"""
import os
import json
import boto3
import base64
import logging
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from botocore.config import Config
from typing import Dict, Any, Optional, List
from datetime import datetime

# Import from shared Nova modules
from app.services.nova.models import (
    MODELS,
    NovaError,
    handle_bedrock_errors,
    get_model_config,
    calculate_cost,
)
from app.services.nova.parsers import (
    NovaParseError,
    parse_json_response,
)
from app.services.nova.image_prompts import (
    get_image_description_prompt,
    get_image_elements_prompt,
    get_image_waterfall_prompt,
    get_image_metadata_prompt,
    get_image_combined_prompt,
)

logger = logging.getLogger(__name__)


class NovaImageService:
    """Service for AWS Nova image analysis via Amazon Bedrock."""

    def __init__(self, bucket_name: str, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        """Initialize Nova image service."""
        self.bucket_name = bucket_name
        self.region = region

        # Initialize Bedrock Runtime client with reasonable timeouts for images
        # Image analysis is much faster than video (5-15s typical)
        bedrock_config = Config(
            read_timeout=120,      # 2 minutes for read operations
            connect_timeout=30,    # 30 seconds for initial connection
            retries={'max_attempts': 3, 'mode': 'standard'}
        )

        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.client = boto3.client('bedrock-runtime', config=bedrock_config, **session_kwargs)
        self.s3_client = boto3.client('s3', **session_kwargs)

        logger.info(f"NovaImageService initialized for bucket: {bucket_name}, region: {region}")

    def extract_exif_metadata(self, image_path: str) -> Dict[str, Any]:
        """
        Extract EXIF metadata from image file.

        Args:
            image_path: Path to local image file

        Returns:
            Dict with EXIF data:
                - capture_date: ISO date string or None
                - gps_coordinates: Dict with latitude/longitude or None
                - camera_make: Camera manufacturer or None
                - camera_model: Camera model or None
                - original_description: Embedded description or None
        """
        exif_data = {
            'capture_date': None,
            'gps_coordinates': None,
            'camera_make': None,
            'camera_model': None,
            'original_description': None
        }

        try:
            with Image.open(image_path) as img:
                exif = img.getexif()
                if not exif:
                    return exif_data

                for tag_id, value in exif.items():
                    tag = TAGS.get(tag_id, tag_id)

                    if tag == 'DateTimeOriginal' or tag == 'DateTime':
                        # Format: "2024:03:15 14:30:00" → "2024-03-15"
                        exif_data['capture_date'] = self._parse_exif_date(value)
                    elif tag == 'GPSInfo':
                        exif_data['gps_coordinates'] = self._parse_gps_info(value)
                    elif tag == 'Make':
                        exif_data['camera_make'] = str(value).strip()
                    elif tag == 'Model':
                        exif_data['camera_model'] = str(value).strip()
                    elif tag == 'ImageDescription':
                        exif_data['original_description'] = str(value).strip()

        except Exception as e:
            logger.warning(f"Failed to extract EXIF from {image_path}: {e}")

        return exif_data

    def _parse_exif_date(self, date_str: str) -> Optional[str]:
        """
        Convert EXIF date format to ISO format.

        Args:
            date_str: EXIF date string (e.g., "2024:03:15 14:30:00")

        Returns:
            ISO date string (e.g., "2024-03-15") or None
        """
        try:
            date_part = str(date_str).split(' ')[0]
            return date_part.replace(':', '-')
        except Exception:
            return None

    def _parse_gps_info(self, gps_info: Dict) -> Optional[Dict[str, float]]:
        """
        Parse GPS EXIF data to decimal coordinates.

        Args:
            gps_info: GPS EXIF dict

        Returns:
            Dict with latitude/longitude or None
        """
        try:
            def dms_to_decimal(dms, ref):
                """Convert degrees, minutes, seconds to decimal."""
                degrees = float(dms[0])
                minutes = float(dms[1]) / 60
                seconds = float(dms[2]) / 3600
                decimal = degrees + minutes + seconds
                if ref in ['S', 'W']:
                    decimal = -decimal
                return round(decimal, 6)

            # GPS EXIF tags
            gps_latitude = gps_info.get(2)
            gps_latitude_ref = gps_info.get(1)
            gps_longitude = gps_info.get(4)
            gps_longitude_ref = gps_info.get(3)

            if gps_latitude and gps_latitude_ref and gps_longitude and gps_longitude_ref:
                lat = dms_to_decimal(gps_latitude, gps_latitude_ref)
                lon = dms_to_decimal(gps_longitude, gps_longitude_ref)
                return {'latitude': lat, 'longitude': lon}

        except Exception as e:
            logger.warning(f"Failed to parse GPS info: {e}")

        return None

    def build_file_context(self, file_record: Dict[str, Any], image_path: str) -> Dict[str, Any]:
        """
        Build context dict for Nova prompt, including EXIF data.

        Args:
            file_record: Database record with filename, s3_key, etc.
            image_path: Local path to image file

        Returns:
            Context dict with file metadata and EXIF data
        """
        exif = self.extract_exif_metadata(image_path)

        path_segments = []
        if file_record.get('s3_key'):
            path_segments = file_record['s3_key'].split('/')

        camera_str = ''
        if exif['camera_make'] and exif['camera_model']:
            camera_str = f"{exif['camera_make']} {exif['camera_model']}"
        elif exif['camera_make']:
            camera_str = exif['camera_make']
        elif exif['camera_model']:
            camera_str = exif['camera_model']

        return {
            'filename': file_record.get('filename', 'unknown'),
            'path_segments': path_segments,
            'file_date': file_record.get('created_at'),
            # EXIF enrichment
            'exif_capture_date': exif['capture_date'],
            'exif_gps': exif['gps_coordinates'],
            'exif_camera': camera_str,
            'exif_description': exif['original_description']
        }

    @handle_bedrock_errors
    def analyze_image(
        self,
        image_path: str,
        analysis_types: List[str],
        model: str = 'lite',
        file_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Main entry point - single combined API call for all analysis types.

        Args:
            image_path: Path to proxy image file (local filesystem)
            analysis_types: List of ['description', 'elements', 'waterfall', 'metadata']
            model: 'lite', 'pro', or 'premier'
            file_context: Dict with filename, path_segments, exif data

        Returns:
            Combined results dict with:
                - results: Dict with all requested analysis types
                - tokens_input: Input token count
                - tokens_output: Output token count
                - tokens_total: Total token count
                - cost_usd: Estimated cost
                - raw_response: Full API response for debugging
                - processing_time_seconds: Time taken
        """
        if not analysis_types:
            raise NovaError("At least one analysis type must be specified")

        start_time = datetime.now()

        # Build combined prompt
        prompt = get_image_combined_prompt(analysis_types, file_context)

        # Single API call
        response_data = self._invoke_nova_image(image_path, prompt, model)

        # Parse combined response
        results = self._parse_combined_response(response_data['text'], analysis_types)

        processing_time = (datetime.now() - start_time).total_seconds()

        return {
            'results': results,
            'tokens_input': response_data['tokens_input'],
            'tokens_output': response_data['tokens_output'],
            'tokens_total': response_data['tokens_total'],
            'cost_usd': response_data['cost'],
            'raw_response': response_data['raw_response'],
            'processing_time_seconds': processing_time
        }

    def _prepare_image_content(self, image_path: str) -> Dict[str, Any]:
        """
        Prepare image for Bedrock Converse API.

        Args:
            image_path: Path to local image file

        Returns:
            Image content dict for Bedrock API
        """
        with open(image_path, 'rb') as f:
            image_bytes = f.read()

        # Determine media type from extension
        ext = Path(image_path).suffix.lower()
        format_map = {
            '.jpg': 'jpeg',
            '.jpeg': 'jpeg',
            '.png': 'png',
            '.gif': 'gif',
            '.webp': 'webp'
        }
        image_format = format_map.get(ext, 'jpeg')

        return {
            "image": {
                "format": image_format,
                "source": {
                    "bytes": image_bytes
                }
            }
        }

    @handle_bedrock_errors
    def _invoke_nova_image(self, image_path: str, prompt: str, model: str) -> Dict[str, Any]:
        """
        Invoke Nova model with image content via Bedrock Converse API.

        Args:
            image_path: Path to local image file
            prompt: Analysis prompt text
            model: Model identifier ('lite', 'pro', 'premier')

        Returns:
            Dict with:
                - text: Response text
                - tokens_input: Input tokens
                - tokens_output: Output tokens
                - tokens_total: Total tokens
                - cost: Estimated cost in USD
                - raw_response: Full API response
        """
        model_config = get_model_config(model)
        model_id = model_config['id']

        image_content = self._prepare_image_content(image_path)

        logger.info(f"Invoking Nova {model} for image analysis")

        response = self.client.converse(
            modelId=model_id,
            messages=[{
                "role": "user",
                "content": [
                    image_content,
                    {"text": prompt}
                ]
            }],
            inferenceConfig={
                "maxTokens": 4096,
                "temperature": 0.3
            }
        )

        # Extract response text and token usage
        output_text = response['output']['message']['content'][0]['text']
        usage = response['usage']

        tokens_input = usage['inputTokens']
        tokens_output = usage['outputTokens']
        tokens_total = tokens_input + tokens_output

        # Calculate cost
        cost = calculate_cost(
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output
        )

        logger.info(f"Nova image analysis complete: {tokens_total} tokens, ${cost:.6f}")

        return {
            'text': output_text,
            'tokens_input': tokens_input,
            'tokens_output': tokens_output,
            'tokens_total': tokens_total,
            'cost': cost,
            'raw_response': response
        }

    def _parse_combined_response(self, response_text: str, analysis_types: List[str]) -> Dict[str, Any]:
        """
        Parse combined JSON response into typed results.

        Args:
            response_text: Raw text response from Nova
            analysis_types: List of requested analysis types

        Returns:
            Dict with parsed results for each analysis type

        Raises:
            NovaParseError: If JSON parsing fails
        """
        # Use shared parser from parsers.py
        parsed = parse_json_response(response_text, context="image_analysis")

        results = {}

        # Extract each requested analysis type
        if 'description' in analysis_types and 'description' in parsed:
            results['description'] = parsed['description']

        if 'elements' in analysis_types and 'elements' in parsed:
            results['elements'] = parsed['elements']

        if 'waterfall' in analysis_types and 'waterfall_classification' in parsed:
            results['waterfall_classification'] = parsed['waterfall_classification']

        if 'metadata' in analysis_types and 'metadata' in parsed:
            results['metadata'] = parsed['metadata']

        return results

    def estimate_image_cost(self, model: str, analysis_types: List[str]) -> Dict[str, Any]:
        """
        Estimate cost for image analysis.

        Args:
            model: Model identifier ('lite', 'pro', 'premier')
            analysis_types: List of analysis types to perform

        Returns:
            Dict with cost estimates:
                - estimated_input_tokens: Approximate input tokens
                - estimated_output_tokens: Approximate output tokens
                - estimated_cost_usd: Estimated total cost
                - model: Model name
        """
        model_config = get_model_config(model)

        # Image analysis token estimates (approximate)
        # Input: ~1500 tokens for 896px image + prompt overhead
        # Output: ~500-1500 tokens depending on analysis types
        estimated_input_tokens = 1500 + (len(analysis_types) * 200)

        output_tokens_by_type = {
            'description': 400,
            'elements': 600,
            'waterfall': 400,
            'metadata': 400
        }

        estimated_output_tokens = sum(
            output_tokens_by_type.get(at, 500) for at in analysis_types
        )

        # Calculate cost
        cost = calculate_cost(
            model=model,
            tokens_input=estimated_input_tokens,
            tokens_output=estimated_output_tokens
        )

        return {
            'estimated_input_tokens': estimated_input_tokens,
            'estimated_output_tokens': estimated_output_tokens,
            'estimated_cost_usd': cost,
            'model': model_config['name']
        }

    def get_models(self) -> Dict[str, Any]:
        """
        Get available models and their configurations.

        Returns:
            Dict of model configurations
        """
        return MODELS
