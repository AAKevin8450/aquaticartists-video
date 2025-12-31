"""Nova video analysis service modules."""
from .models import (
    MODELS,
    NovaError,
    handle_bedrock_errors,
    get_model_config,
    estimate_cost,
    calculate_cost,
)
from .parsers import (
    NovaParseError,
    sanitize_json_string,
    parse_json_response,
    close_json_structure,
    parse_timecode_to_seconds,
    ensure_list,
    parse_time_range,
    parse_time_ranges,
    load_waterfall_assets,
    validate_waterfall_classification,
)
from .prompts import (
    normalize_file_context,
    build_contextual_prompt,
    get_waterfall_classification_prompt,
    get_summary_prompt,
    get_chapters_prompt,
    get_elements_prompt,
    get_combined_prompt,
)

__all__ = [
    # Models
    'MODELS',
    'NovaError',
    'handle_bedrock_errors',
    'get_model_config',
    'estimate_cost',
    'calculate_cost',
    # Parsers
    'NovaParseError',
    'sanitize_json_string',
    'parse_json_response',
    'close_json_structure',
    'parse_timecode_to_seconds',
    'ensure_list',
    'parse_time_range',
    'parse_time_ranges',
    'load_waterfall_assets',
    'validate_waterfall_classification',
    # Prompts
    'normalize_file_context',
    'build_contextual_prompt',
    'get_waterfall_classification_prompt',
    'get_summary_prompt',
    'get_chapters_prompt',
    'get_elements_prompt',
    'get_combined_prompt',
]
