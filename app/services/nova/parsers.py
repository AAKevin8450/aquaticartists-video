"""JSON parsing and validation for Nova responses."""
import json
import re
import os
import logging
from typing import Optional, Dict, Any, List, Tuple
from functools import lru_cache

logger = logging.getLogger(__name__)


class NovaParseError(Exception):
    """Exception raised when Nova response parsing fails."""
    pass


def sanitize_json_string(text: str) -> str:
    """
    Attempt to sanitize malformed JSON by fixing common issues.

    This is a fallback method for when Nova returns JSON with unescaped characters.

    Args:
        text: Potentially malformed JSON string

    Returns:
        Sanitized JSON string
    """
    # Remove any markdown code fences
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)

    # Try to detect and fix common JSON issues:
    # 1. Unescaped quotes within string values
    # 2. Unescaped newlines within strings
    # 3. Unescaped backslashes

    # Note: This is a best-effort approach and may not work for all cases
    # The proper solution is for Nova to return valid JSON

    return cleaned


def close_json_structure(json_str: str) -> str:
    """
    Intelligently close an incomplete JSON structure by analyzing nesting levels.

    Args:
        json_str: Potentially incomplete JSON string

    Returns:
        JSON string with proper closing braces/brackets
    """
    # Track depth while respecting string context
    in_string = False
    escape_next = False
    brace_depth = 0
    bracket_depth = 0

    for char in json_str:
        if escape_next:
            escape_next = False
            continue

        if char == '\\':
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if not in_string:
            if char == '{':
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
            elif char == '[':
                bracket_depth += 1
            elif char == ']':
                bracket_depth -= 1

    # Close any unclosed strings
    result = json_str
    if in_string:
        result += '"'

    # Remove any trailing commas before adding closing brackets
    result = result.rstrip()
    if result.endswith(','):
        result = result[:-1]

    # Add missing closing brackets and braces
    result += ']' * bracket_depth
    result += '}' * brace_depth

    return result


def parse_json_response(text: str) -> Dict[str, Any]:
    """
    Parse JSON from Nova response, handling markdown code fences and common errors.

    This is a core parsing function used by both realtime and batch processing
    to ensure consistent JSON extraction across all analysis modes.

    Args:
        text: Response text that may contain JSON

    Returns:
        Parsed JSON object

    Raises:
        NovaParseError: If JSON parsing fails after all fix attempts
    """
    # Remove markdown code fences if present
    cleaned = text.strip()
    cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned)
    cleaned = re.sub(r'\n?```\s*$', '', cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        error_msg = str(e)
        fixed = cleaned

        # Apply cascading fixes - keep trying until one works
        # Fix #1: Trailing commas before closing braces/brackets
        if ('Expecting property name' in error_msg or
            'Expecting value' in error_msg or
            'Illegal trailing comma' in error_msg):
            logger.warning(f"Detected trailing comma or syntax error at position {e.pos}, attempting to fix...")

            # Remove trailing commas before } or ]
            fixed = re.sub(r',\s*([}\]])', r'\1', fixed)

            try:
                logger.info("Successfully fixed trailing comma in Nova response")
                return json.loads(fixed)
            except json.JSONDecodeError as e2:
                logger.debug(f"Trailing comma fix didn't resolve issue: {e2}")
                # Update error for cascading to next fix
                e = e2
                error_msg = str(e2)

        # Fix #2: Unterminated strings (common with max_tokens truncation)
        if 'Unterminated string' in error_msg:
            logger.warning(f"Detected unterminated string in Nova response at position {e.pos}, attempting to fix...")

            # Strategy: Add a closing quote at the end and close the JSON structure
            fixed_attempts = []

            # Attempt 1: Just add quote at the end and close structure
            attempt1 = fixed.rstrip() + '"'
            attempt1 = close_json_structure(attempt1)
            fixed_attempts.append(attempt1)

            # Attempt 2: Remove any partial content after the last complete token and close
            if e.pos and e.pos > 10:
                # Try truncating a bit before the error position to remove partial content
                for lookback in [5, 10, 20, 50]:
                    if e.pos - lookback > 0:
                        truncate_pos = e.pos - lookback
                        # Find the last quote before this position
                        attempt = fixed[:truncate_pos].rstrip()
                        if attempt.endswith('"'):
                            attempt = close_json_structure(attempt)
                            fixed_attempts.append(attempt)

            # Try each fix attempt
            success = False
            for attempt in fixed_attempts:
                try:
                    result = json.loads(attempt)
                    logger.info("Successfully fixed unterminated string in Nova response")
                    return result
                except json.JSONDecodeError as e2:
                    # Keep trying, but save this for cascading to next fix
                    e = e2
                    error_msg = str(e2)
                    fixed = attempt  # Use this partially fixed version for next fix
                    continue

            if not success:
                logger.error(f"All unterminated string fixes failed, last error: {e}")

        # Fix #3: Invalid escape sequences
        if 'Invalid \\escape' in error_msg or 'Invalid escape' in error_msg or 'bad escape' in error_msg:
            logger.warning(f"Detected invalid escape sequences in Nova response, attempting to fix...")

            # Fix invalid escape sequences by escaping backslashes that aren't part of valid JSON escapes
            # Valid JSON escape sequences: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX

            # First, temporarily replace valid escape sequences with placeholders
            replacements = {
                '\\"': '\x00QUOTE\x00',
                '\\\\': '\x00BACKSLASH\x00',
                '\\/': '\x00SLASH\x00',
                '\\b': '\x00BACKSPACE\x00',
                '\\f': '\x00FORMFEED\x00',
                '\\n': '\x00NEWLINE\x00',
                '\\r': '\x00RETURN\x00',
                '\\t': '\x00TAB\x00'
            }

            temp_fixed = fixed
            for old, new in replacements.items():
                temp_fixed = temp_fixed.replace(old, new)

            # Also handle Unicode escapes \uXXXX
            temp_fixed = re.sub(r'\\u([0-9a-fA-F]{4})', '\x00UNICODE\\1\x00', temp_fixed)

            # Now escape any remaining backslashes (these are the invalid ones)
            temp_fixed = temp_fixed.replace('\\', '\\\\')

            # Restore the valid escape sequences
            for old, new in replacements.items():
                temp_fixed = temp_fixed.replace(new, old)

            # Restore Unicode escapes
            temp_fixed = re.sub('\x00UNICODE([0-9a-fA-F]{4})\x00', r'\\u\1', temp_fixed)

            try:
                logger.info("Successfully fixed invalid escape sequences in Nova response")
                return json.loads(temp_fixed)
            except json.JSONDecodeError as e2:
                logger.error(f"Still failed to parse after fixing escape sequences: {e2}")
                e = e2
                error_msg = str(e2)
                fixed = temp_fixed

        # Fix #4: Structural issues (Expecting comma, etc.)
        if 'Expecting' in error_msg and e.pos:
            logger.warning(f"Detected structural issue, attempting truncation and closure...")

            # Try truncating at different points before the error and closing the structure
            for lookback in [0, 1, 2, 5, 10, 20]:
                if e.pos - lookback > 0:
                    truncate_pos = e.pos - lookback
                    attempt = close_json_structure(fixed[:truncate_pos])

                    try:
                        return json.loads(attempt)
                    except json.JSONDecodeError:
                        continue

        # Fix #5: Generic truncation - try to intelligently close the JSON
        logger.warning("Attempting generic JSON structure completion...")
        fixed = close_json_structure(fixed)

        try:
            logger.info("Successfully completed truncated JSON structure")
            return json.loads(fixed)
        except json.JSONDecodeError as e2:
            logger.error(f"Generic structure completion failed: {e2}")

        # Enhanced error logging for debugging
        logger.error(f"All JSON fix attempts failed. Original error: {e}")
        logger.error(f"Error at line {e.lineno}, column {e.colno}, position {e.pos}")
        logger.error(f"First 1000 chars of response: {text[:1000]}")

        # Log the problematic area around the error position
        if e.pos and e.pos > 0:
            start = max(0, e.pos - 100)
            end = min(len(cleaned), e.pos + 100)
            logger.error(f"Context around error (pos {e.pos}): ...{cleaned[start:end]}...")

        # Log last 500 chars to check if response was truncated
        logger.error(f"Last 500 chars of response: {text[-500:]}")

        raise NovaParseError(f"Failed to parse Nova response as JSON: {e}")


def parse_timecode_to_seconds(timecode: str) -> int:
    """
    Parse MM:SS or HH:MM:SS timecode into seconds.

    Args:
        timecode: Time string in MM:SS or HH:MM:SS format

    Returns:
        Total seconds as integer
    """
    if not timecode:
        return 0

    cleaned = re.sub(r'[^0-9:]', '', str(timecode).strip())
    if not cleaned:
        return 0

    parts = cleaned.split(':')
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = parts
        elif len(parts) == 1:
            hours = 0
            minutes = 0
            seconds = parts[0]
        else:
            return 0

        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    except ValueError:
        return 0


def ensure_list(value: Any) -> List[str]:
    """
    Normalize value into a list of strings.

    Args:
        value: Any value to normalize

    Returns:
        List of strings
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value]
    return [str(value)]


def parse_time_range(time_range: str) -> Optional[Dict[str, Any]]:
    """
    Parse a time range string into structured fields.

    Args:
        time_range: Time range string like "00:00 - 01:30"

    Returns:
        Dictionary with start_time, end_time, start_seconds, end_seconds, duration_seconds
        or None if input is empty
    """
    if not time_range:
        return None

    parts = re.split(r'\s*-\s*', str(time_range).strip())
    if len(parts) == 2:
        start_time, end_time = parts
    else:
        start_time = parts[0]
        end_time = parts[0]

    start_seconds = parse_timecode_to_seconds(start_time)
    end_seconds = parse_timecode_to_seconds(end_time)
    if end_seconds < start_seconds:
        end_seconds = start_seconds

    return {
        'start_time': start_time.strip(),
        'end_time': end_time.strip(),
        'start_seconds': start_seconds,
        'end_seconds': end_seconds,
        'duration_seconds': end_seconds - start_seconds
    }


def parse_time_ranges(time_ranges: List[str]) -> List[Dict[str, Any]]:
    """
    Parse a list of time range strings into structured fields.

    Args:
        time_ranges: List of time range strings

    Returns:
        List of parsed time range dictionaries
    """
    parsed = []
    for time_range in time_ranges:
        parsed_range = parse_time_range(time_range)
        if parsed_range:
            parsed.append(parsed_range)
    return parsed


@lru_cache(maxsize=1)
def load_waterfall_assets() -> Tuple[str, Dict[str, Any]]:
    """
    Load waterfall classification decision tree and spec from docs.

    Returns:
        Tuple of (decision_tree_text, spec_dict)
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    decision_path = os.path.join(base_dir, 'docs', 'Nova_Waterfall_Classification_Decision_Tree.md')
    spec_path = os.path.join(base_dir, 'docs', 'Nova_Waterfall_Classification_Spec.json')

    with open(decision_path, 'r', encoding='utf-8') as decision_file:
        decision_tree = decision_file.read()

    with open(spec_path, 'r', encoding='utf-8') as spec_file:
        spec = json.load(spec_file)

    return decision_tree, spec


def validate_waterfall_classification(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and normalize waterfall classification output against the spec.

    Args:
        payload: Raw classification output from Nova

    Returns:
        Validated and normalized classification dictionary
    """
    _, spec = load_waterfall_assets()
    taxonomy = spec.get('taxonomy', {})
    required_fields = spec.get('output_format', {}).get('required_fields', [])

    data = payload if isinstance(payload, dict) else {}
    allowed = {
        'family': set(taxonomy.get('family', {}).get('allowed', [])),
        'tier_level': set(taxonomy.get('tier_level', {}).get('allowed', [])),
        'functional_type': set(taxonomy.get('functional_type', {}).get('allowed', [])),
        'sub_type': set(taxonomy.get('sub_type', {}).get('allowed', []))
    }

    unknown_reasons = data.get('unknown_reasons')
    if not isinstance(unknown_reasons, dict):
        unknown_reasons = {}

    for field, allowed_values in allowed.items():
        value = data.get(field)
        if value not in allowed_values:
            data[field] = 'Unknown'
            if not unknown_reasons.get(field):
                unknown_reasons[field] = 'Invalid or missing value in model output.'

    normalized_unknown_reasons = {}
    for field in allowed.keys():
        if data.get(field) == 'Unknown':
            normalized_unknown_reasons[field] = unknown_reasons.get(
                field, 'Insufficient evidence to determine classification.'
            )

    confidence = data.get('confidence')
    if not isinstance(confidence, dict):
        confidence = {}

    dim_confidences = {}
    for field in allowed.keys():
        raw_value = confidence.get(field)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = 0.0 if data.get(field) == 'Unknown' else 0.5
        value = max(0.0, min(1.0, value))
        dim_confidences[field] = value

    overall = confidence.get('overall')
    try:
        overall_value = float(overall)
    except (TypeError, ValueError):
        overall_value = min(dim_confidences.values()) if dim_confidences else 0.0
    overall_value = max(0.0, min(1.0, overall_value))

    dim_confidences['overall'] = overall_value
    data['confidence'] = dim_confidences

    evidence = data.get('evidence')
    if not isinstance(evidence, list):
        evidence = [evidence] if evidence else []
    data['evidence'] = [str(item).strip() for item in evidence if str(item).strip()]

    data['unknown_reasons'] = normalized_unknown_reasons

    for field in required_fields:
        if field not in data:
            if field == 'confidence':
                data['confidence'] = dim_confidences
            elif field == 'evidence':
                data['evidence'] = []
            elif field == 'unknown_reasons':
                data['unknown_reasons'] = normalized_unknown_reasons
            else:
                data[field] = data.get(field, 'Unknown')

    return data
