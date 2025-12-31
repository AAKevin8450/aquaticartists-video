"""Data enrichment functions for Nova analysis results.

This module contains standalone functions for enriching Nova analysis data.
These functions modify dictionaries in-place (they return None).
"""
import re
from typing import Dict, Any, List, Optional


def parse_timecode_to_seconds(timecode: str) -> int:
    """Parse MM:SS or HH:MM:SS timecode into seconds."""
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
    """Normalize value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str):
        return [value]
    return [str(value)]


def parse_time_range(time_range: str) -> Optional[Dict[str, Any]]:
    """Parse a time range string into structured fields."""
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
    """Parse a list of time range strings into structured fields."""
    parsed = []
    for time_range in time_ranges:
        parsed_range = parse_time_range(time_range)
        if parsed_range:
            parsed.append(parsed_range)
    return parsed


def enrich_chapter_data(chapter: Dict[str, Any]) -> None:
    """
    Enrich chapter dictionary with computed fields (in-place modification).

    Core enrichment logic used by both realtime and batch processing
    to ensure consistent chapter data across all processing modes.

    Args:
        chapter: Chapter dictionary to enrich
    """
    start_time = chapter.get('start_time')
    end_time = chapter.get('end_time')

    start_seconds = parse_timecode_to_seconds(start_time)
    end_seconds = parse_timecode_to_seconds(end_time)
    if end_seconds < start_seconds:
        end_seconds = start_seconds

    chapter['start_seconds'] = start_seconds
    chapter['end_seconds'] = end_seconds
    duration_seconds = end_seconds - start_seconds
    chapter['duration_seconds'] = duration_seconds

    # Format duration as HH:MM:SS or MM:SS
    if duration_seconds >= 3600:
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        seconds = duration_seconds % 60
        chapter['duration'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        chapter['duration'] = f"{duration_seconds // 60:02d}:{duration_seconds % 60:02d}"


def enrich_equipment_data(equip: Dict[str, Any]) -> None:
    """
    Enrich equipment dictionary with computed fields (in-place modification).

    Core enrichment logic used by both realtime and batch processing
    to ensure consistent equipment data across all processing modes.

    Args:
        equip: Equipment dictionary to enrich
    """
    equip['time_ranges'] = ensure_list(equip.get('time_ranges'))
    equip['time_ranges_parsed'] = parse_time_ranges(equip['time_ranges'])
    equip['discussed'] = bool(equip.get('discussed', False))
    if 'confidence' not in equip:
        equip['confidence'] = 'medium'


def enrich_topic_data(topic: Dict[str, Any]) -> None:
    """
    Enrich topic dictionary with computed fields (in-place modification).

    Core enrichment logic used by both realtime and batch processing
    to ensure consistent topic data across all processing modes.

    Args:
        topic: Topic dictionary to enrich
    """
    topic['time_ranges'] = ensure_list(topic.get('time_ranges'))
    topic['time_ranges_parsed'] = parse_time_ranges(topic['time_ranges'])
    if 'importance' not in topic:
        topic['importance'] = 'medium'
    topic['keywords'] = ensure_list(topic.get('keywords'))


def enrich_speaker_data(speaker: Dict[str, Any]) -> None:
    """
    Enrich speaker dictionary with computed fields (in-place modification).

    Core enrichment logic used by both realtime and batch processing
    to ensure consistent speaker data across all processing modes.

    Args:
        speaker: Speaker dictionary to enrich
    """
    speaker['time_ranges'] = ensure_list(speaker.get('time_ranges'))
    speaker['time_ranges_parsed'] = parse_time_ranges(speaker['time_ranges'])
    if 'speaking_percentage' in speaker:
        try:
            speaker['speaking_percentage'] = float(speaker['speaking_percentage'])
        except (TypeError, ValueError):
            speaker['speaking_percentage'] = None


def build_topics_summary(topics_discussed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build topics summary from topics_discussed list.

    Core summarization logic used by both realtime and batch processing.

    Args:
        topics_discussed: List of topic dictionaries

    Returns:
        List of topic summary dictionaries
    """
    topics_summary = []
    for topic in topics_discussed:
        name = str(topic.get('topic', '')).strip()
        if not name:
            continue
        topics_summary.append({
            'topic': name,
            'importance': topic.get('importance', 'medium'),
            'time_range_count': len(topic.get('time_ranges', []))
        })
    return topics_summary


def build_combined_results(
    payload: Dict[str, Any],
    model: str,
    options: Dict[str, Any],
    usage: Dict[str, int],
    cost_usd: float,
    processing_time_seconds: float,
    generated_at: str,
    get_model_config_func,
    validate_waterfall_func,
    combined_analysis_types: List[str]
) -> Dict[str, Any]:
    """Build normalized results from a combined analysis payload.

    Args:
        payload: Raw analysis payload from Nova
        model: Model name ('lite', 'pro', 'premier')
        options: Analysis options dictionary
        usage: Token usage dictionary with 'total_tokens', 'input_tokens', 'output_tokens'
        cost_usd: Total cost in USD
        processing_time_seconds: Processing time
        generated_at: ISO timestamp
        get_model_config_func: Function to get model config (callable that takes model name)
        validate_waterfall_func: Function to validate waterfall classification
        combined_analysis_types: List of analysis types for count

    Returns:
        Normalized results dictionary
    """
    summary_payload = payload.get('summary') or {}
    if isinstance(summary_payload, str):
        summary_text = summary_payload
    else:
        summary_text = summary_payload.get('text') or ''

    chapters_payload = payload.get('chapters') or {}
    if isinstance(chapters_payload, list):
        chapters = chapters_payload
    else:
        chapters = chapters_payload.get('chapters', []) if isinstance(chapters_payload, dict) else []

    for chapter in chapters:
        enrich_chapter_data(chapter)

    elements_payload = payload.get('elements') or {}
    if not isinstance(elements_payload, dict):
        elements_payload = {}

    equipment = elements_payload.get('equipment', [])
    topics_discussed = elements_payload.get('topics_discussed', [])
    people = elements_payload.get('people', {'max_count': 0, 'multiple_speakers': False})
    speakers = elements_payload.get('speakers', [])

    for equip in equipment:
        enrich_equipment_data(equip)

    for topic in topics_discussed:
        enrich_topic_data(topic)

    for speaker in speakers:
        enrich_speaker_data(speaker)

    if speakers and not people.get('multiple_speakers'):
        people['multiple_speakers'] = len(speakers) > 1

    topics_summary = build_topics_summary(topics_discussed)

    classification_payload = payload.get('waterfall_classification') or {}
    classification = validate_waterfall_func(
        classification_payload if isinstance(classification_payload, dict) else {}
    )

    search_metadata_payload = payload.get('search_metadata') or {}
    if not isinstance(search_metadata_payload, dict):
        search_metadata_payload = {}

    model_config = get_model_config_func(model)
    model_id = model_config['id']

    summary_result = {
        'text': summary_text,
        'depth': options.get('summary_depth', summary_payload.get('depth') or 'standard'),
        'language': options.get('language', summary_payload.get('language') or 'auto'),
        'word_count': len(summary_text.split()) if summary_text else 0,
        'generated_at': generated_at,
        'model_used': model,
        'model_id': model_id,
        'tokens_used': usage['total_tokens'],
        'tokens_input': usage['input_tokens'],
        'tokens_output': usage['output_tokens'],
        'cost_usd': cost_usd,
        'processing_time_seconds': processing_time_seconds
    }

    chapters_result = {
        'chapters': chapters,
        'total_chapters': len(chapters),
        'detection_method': 'semantic_segmentation',
        'model_used': model,
        'model_id': model_id,
        'tokens_used': 0,
        'cost_usd': 0,
        'processing_time_seconds': processing_time_seconds,
        'generated_at': generated_at
    }

    elements_result = {
        'equipment': equipment,
        'topics_discussed': topics_discussed,
        'topics_summary': topics_summary,
        'people': people,
        'speakers': speakers,
        'model_used': model,
        'model_id': model_id,
        'tokens_used': 0,
        'cost_usd': 0,
        'processing_time_seconds': processing_time_seconds,
        'generated_at': generated_at
    }

    classification_result = {
        **classification,
        'model_used': model,
        'model_id': model_id,
        'tokens_used': 0,
        'cost_usd': 0,
        'processing_time_seconds': processing_time_seconds,
        'generated_at': generated_at
    }

    return {
        'summary': summary_result,
        'chapters': chapters_result,
        'elements': elements_result,
        'waterfall_classification': classification_result,
        'search_metadata': search_metadata_payload,
        'totals': {
            'tokens_total': usage['total_tokens'],
            'cost_total_usd': round(cost_usd, 4),
            'processing_time_seconds': round(processing_time_seconds, 2),
            'analyses_completed': len(combined_analysis_types)
        }
    }
