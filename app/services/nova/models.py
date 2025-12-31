"""Model configuration and cost estimation for Nova video analysis."""
from typing import Dict, Any, Optional
from functools import wraps

from botocore.exceptions import ClientError


class NovaError(Exception):
    """Base exception for Nova errors."""
    pass


def handle_bedrock_errors(func):
    """Decorator to handle AWS Bedrock/Nova errors and convert to user-friendly messages."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            if error_code == 'AccessDeniedException':
                raise NovaError("AWS permission denied. Ensure IAM policy includes bedrock:InvokeModel for Nova models. See docs/NOVA_IAM_SETUP.md")
            elif error_code == 'ModelAccessDeniedException':
                raise NovaError("Nova model access denied. Request model access in Bedrock console. See docs/NOVA_IAM_SETUP.md")
            elif error_code == 'ValidationException':
                raise NovaError(f"Invalid request parameters: {error_msg}")
            elif error_code == 'ThrottlingException':
                raise NovaError("AWS rate limit exceeded. Please try again in a moment.")
            elif error_code == 'ServiceQuotaExceededException':
                raise NovaError("Service quota exceeded. Contact AWS Support to increase limits.")
            elif error_code == 'InvalidS3ObjectException':
                raise NovaError("Video file not found or inaccessible in S3")
            elif error_code == 'ResourceNotFoundException':
                raise NovaError(f"Resource not found: {error_msg}")
            else:
                raise NovaError(f"Bedrock error ({error_code}): {error_msg}")
    return wrapper


# Model configurations with pricing and token limits
MODELS = {
    'lite': {
        'id': 'amazon.nova-2-lite-v1:0',
        'inference_profile_id': 'us.amazon.nova-2-lite-v1:0',
        'name': 'Nova 2 Lite',
        'context_tokens': 300000,
        'max_video_minutes': 30,
        'price_input_per_1k': 0.00033,
        'price_output_per_1k': 0.00275,
        'best_for': 'General video understanding (recommended)',
        'supports_batch': True
    },
    'pro': {
        'id': 'us.amazon.nova-pro-v1:0',
        'name': 'Nova Pro',
        'context_tokens': 300000,
        'max_video_minutes': 30,
        'price_input_per_1k': 0.0008,
        'price_output_per_1k': 0.0032,
        'best_for': 'Complex reasoning, detailed analysis',
        'supports_batch': True
    },
    'premier': {
        'id': 'us.amazon.nova-premier-v1:0',
        'name': 'Nova Premier',
        'context_tokens': 1000000,
        'max_video_minutes': 90,
        'price_input_per_1k': 0.0025,
        'price_output_per_1k': 0.0125,
        'best_for': 'Enterprise critical analysis',
        'supports_batch': True
    }
}


def get_model_config(model: str) -> Dict[str, Any]:
    """Get configuration for a specific Nova model.

    Args:
        model: Nova model name ('lite', 'pro', 'premier')

    Returns:
        Dict with model configuration including id, name, pricing, etc.

    Raises:
        NovaError: If model name is invalid
    """
    if model not in MODELS:
        raise NovaError(f"Invalid model: {model}. Choose from: {list(MODELS.keys())}")
    return MODELS[model]


def estimate_cost(model: str, video_duration_seconds: float,
                  estimated_output_tokens: int = 2048,
                  batch_mode: bool = False) -> Dict[str, Any]:
    """
    Estimate cost for video analysis.

    Args:
        model: Nova model name ('lite', 'pro', 'premier')
        video_duration_seconds: Video duration in seconds
        estimated_output_tokens: Expected output token count (default: 2048)
        batch_mode: Whether batch processing discount applies (50% off)

    Returns:
        Dict with cost breakdown including:
        - model: Model name
        - video_duration_seconds: Input duration
        - estimated_input_tokens: Calculated input tokens
        - estimated_output_tokens: Expected output tokens
        - input_cost_usd: Input token cost
        - output_cost_usd: Output token cost
        - total_cost_usd: Total estimated cost
        - price_per_1k_input: Model's input price
        - price_per_1k_output: Model's output price
        - batch_discount_applied: Whether 50% batch discount was applied
    """
    config = get_model_config(model)

    # Rough estimation: ~100 tokens per second of video (very approximate)
    # Actual token count depends on frame sampling and audio content
    estimated_input_tokens = int(video_duration_seconds * 100)

    input_cost = (estimated_input_tokens / 1000) * config['price_input_per_1k']
    output_cost = (estimated_output_tokens / 1000) * config['price_output_per_1k']
    total_cost = input_cost + output_cost
    if batch_mode:
        input_cost *= 0.5
        output_cost *= 0.5
        total_cost *= 0.5

    return {
        'model': model,
        'video_duration_seconds': video_duration_seconds,
        'estimated_input_tokens': estimated_input_tokens,
        'estimated_output_tokens': estimated_output_tokens,
        'input_cost_usd': round(input_cost, 4),
        'output_cost_usd': round(output_cost, 4),
        'total_cost_usd': round(total_cost, 4),
        'price_per_1k_input': config['price_input_per_1k'],
        'price_per_1k_output': config['price_output_per_1k'],
        'batch_discount_applied': bool(batch_mode)
    }


def calculate_cost(model: str, input_tokens: int, output_tokens: int,
                   batch_mode: bool = False) -> float:
    """Calculate actual cost from token usage.

    Args:
        model: Nova model name ('lite', 'pro', 'premier')
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens generated
        batch_mode: Whether batch processing discount applies (50% off)

    Returns:
        Total cost in USD, rounded to 4 decimal places
    """
    config = get_model_config(model)
    cost = (input_tokens / 1000) * config['price_input_per_1k'] + (
        output_tokens / 1000) * config['price_output_per_1k']
    if batch_mode:
        cost *= 0.5
    return round(cost, 4)
