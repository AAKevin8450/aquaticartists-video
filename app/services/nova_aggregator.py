"""
Result aggregation service for multi-chunk Nova video analysis.
Handles intelligent merging of summaries, chapter deduplication, and element consolidation.
"""
import boto3
import json
import logging
from typing import Dict, Any, List, Optional
from botocore.exceptions import ClientError


logger = logging.getLogger(__name__)


class AggregatorError(Exception):
    """Base exception for aggregation errors."""
    pass


class NovaAggregator:
    """Service for aggregating results from chunked video analysis."""

    def __init__(self, region: str, aws_access_key: str = None, aws_secret_key: str = None):
        """
        Initialize Nova aggregator.

        Args:
            region: AWS region
            aws_access_key: AWS access key (optional)
            aws_secret_key: AWS secret key (optional)
        """
        session_kwargs = {'region_name': region}
        if aws_access_key and aws_secret_key:
            session_kwargs['aws_access_key_id'] = aws_access_key
            session_kwargs['aws_secret_access_key'] = aws_secret_key

        self.bedrock_client = boto3.client('bedrock-runtime', **session_kwargs)
        self.region = region

        logger.info(f"NovaAggregator initialized for region: {region}")

    def aggregate_summaries(
        self,
        chunk_results: List[Dict[str, Any]],
        model: str = 'lite'
    ) -> Dict[str, Any]:
        """
        Aggregate summaries from multiple chunks into coherent whole.
        Uses Nova itself to merge summaries intelligently.

        Args:
            chunk_results: List of chunk result dictionaries containing 'chunk' and 'summary' data
            model: Nova model to use for aggregation ('micro', 'lite', 'pro', 'premier')

        Returns:
            Dict with aggregated summary and metadata
        """
        if not chunk_results:
            raise AggregatorError("No chunk results to aggregate")

        # Extract individual chunk summaries
        chunk_summaries = []
        for i, cr in enumerate(chunk_results):
            chunk = cr['chunk']
            summary_data = cr.get('summary', {})

            # Handle both dict and text formats
            if isinstance(summary_data, dict):
                summary_text = summary_data.get('text', str(summary_data))
            else:
                summary_text = str(summary_data)

            time_label = self._format_time_range(chunk['core_start'], chunk['core_end'])

            chunk_summaries.append({
                'index': i,
                'time_range': time_label,
                'summary': summary_text
            })

        logger.info(f"Aggregating {len(chunk_summaries)} chunk summaries using Nova {model}")

        # Build aggregation prompt
        summaries_text = "\n\n".join([
            f"**CHUNK {s['index']+1} ({s['time_range']})**:\n{s['summary']}"
            for s in chunk_summaries
        ])

        aggregation_prompt = f"""You are given summaries from {len(chunk_summaries)} sequential chunks of a video:

{summaries_text}

Create a single, coherent summary of the ENTIRE video that:
1. Integrates all chunks into a unified narrative
2. Identifies overarching themes and structure
3. Highlights the most important points across the full video
4. Maintains logical flow from beginning to end
5. Provides 2-3 comprehensive paragraphs (approximately 150-200 words)

Do NOT simply concatenate the summaries. Synthesize them into a cohesive whole that someone who hasn't seen the video can understand."""

        try:
            # Use Nova to create final summary (text-only, no video needed)
            model_id = self._get_model_id(model)

            response = self.bedrock_client.converse(
                modelId=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": aggregation_prompt}]
                    }
                ],
                inferenceConfig={
                    "maxTokens": 2048,
                    "temperature": 0.3  # Lower temp for factual aggregation
                }
            )

            final_summary = response['output']['message']['content'][0]['text']
            usage = response['usage']

            logger.info(f"Summary aggregation complete. Tokens: {usage['totalTokens']}")

            return {
                'text': final_summary,
                'depth': 'standard',
                'chunks_aggregated': len(chunk_summaries),
                'word_count': len(final_summary.split()),
                'aggregation_method': 'nova_synthesis',
                'tokens_used': usage['totalTokens']
            }

        except ClientError as e:
            error_msg = f"Bedrock error during summary aggregation: {str(e)}"
            logger.error(error_msg)
            raise AggregatorError(error_msg)
        except Exception as e:
            error_msg = f"Failed to aggregate summaries: {str(e)}"
            logger.error(error_msg)
            raise AggregatorError(error_msg)

    def merge_chapters(
        self,
        chunk_results: List[Dict[str, Any]],
        overlap: int
    ) -> Dict[str, Any]:
        """
        Merge chapters from overlapping chunks, deduplicating chapters in overlap regions.

        Args:
            chunk_results: List of chunk result dictionaries containing 'chunk' and 'chapters' data
            overlap: Overlap duration in seconds (for context)

        Returns:
            Dict with merged chapters and metadata
        """
        if not chunk_results:
            raise AggregatorError("No chunk results to merge")

        all_chapters = []
        seen_timestamps = set()  # Track chapter start times to avoid duplicates

        for cr in chunk_results:
            chunk = cr['chunk']
            chapters_data = cr.get('chapters', {})

            # Handle both dict with 'chapters' key and list format
            if isinstance(chapters_data, dict):
                chunk_chapters = chapters_data.get('chapters', [])
            elif isinstance(chapters_data, list):
                chunk_chapters = chapters_data
            else:
                chunk_chapters = []

            for chapter in chunk_chapters:
                # Get absolute start time in seconds
                absolute_start = self._get_chapter_start_seconds(chapter)

                # Round to nearest second for deduplication
                timestamp_key = round(absolute_start)

                # Check if this chapter was already seen in overlap region
                if timestamp_key in seen_timestamps:
                    logger.debug(f"Skipping duplicate chapter at {timestamp_key}s")
                    continue  # Skip duplicate

                # Only include chapters that start within this chunk's CORE region
                # (not in the overlap areas, to avoid duplicates)
                if chunk['core_start'] <= absolute_start < chunk['core_end']:
                    seen_timestamps.add(timestamp_key)
                    all_chapters.append(chapter)
                    logger.debug(f"Added chapter '{chapter.get('title', 'Untitled')}' at {timestamp_key}s")

        # Sort chapters by start time
        all_chapters.sort(key=lambda c: self._get_chapter_start_seconds(c))

        # Reindex chapters
        for i, chapter in enumerate(all_chapters):
            chapter['index'] = i + 1

        logger.info(f"Merged {len(all_chapters)} chapters from {len(chunk_results)} chunks")

        return {
            'chapters': all_chapters,
            'total_chapters': len(all_chapters),
            'chunks_merged': len(chunk_results),
            'detection_method': 'chunked_semantic_segmentation',
            'overlap_seconds': overlap
        }

    def combine_elements(self, chunk_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Combine identified elements (equipment, objects, topics) from all chunks.
        Merges duplicate detections and consolidates time ranges.

        Args:
            chunk_results: List of chunk result dictionaries containing 'chunk' and 'elements' data

        Returns:
            Dict with combined elements and metadata
        """
        if not chunk_results:
            raise AggregatorError("No chunk results to combine")

        combined = {
            'equipment': [],
            'topics_discussed': [],
            'people': {'max_count': 0, 'multiple_speakers': False},
            'speakers': []
        }

        equipment_index = {}  # name -> equipment object mapping
        topics_index = {}     # topic -> topic object mapping

        for cr in chunk_results:
            elements = cr.get('elements', {})
            chunk_index = cr.get('chunk_index', 0)

            # Merge equipment
            for equip in elements.get('equipment', []):
                name = equip.get('name', 'Unknown')

                if name in equipment_index:
                    # Merge with existing detection
                    existing = equipment_index[name]
                    # Combine time ranges
                    existing_ranges = existing.get('time_ranges', [])
                    new_ranges = equip.get('time_ranges', [])
                    existing['time_ranges'] = existing_ranges + new_ranges
                else:
                    # New equipment
                    equipment_index[name] = equip.copy()

            # Merge topics
            for topic in elements.get('topics_discussed', []):
                topic_name = topic.get('topic', 'Unknown')

                if topic_name in topics_index:
                    # Merge with existing topic
                    existing = topics_index[topic_name]
                    existing_ranges = existing.get('time_ranges', [])
                    new_ranges = topic.get('time_ranges', [])
                    existing['time_ranges'] = existing_ranges + new_ranges

                    # Update importance if higher
                    importance_rank = {'high': 3, 'medium': 2, 'low': 1}
                    new_importance = topic.get('importance', 'low')
                    existing_importance = existing.get('importance', 'low')

                    if importance_rank.get(new_importance, 0) > importance_rank.get(existing_importance, 0):
                        existing['importance'] = new_importance
                else:
                    # New topic
                    topics_index[topic_name] = topic.copy()

            # Track max people count and speaker detection
            people_data = elements.get('people', {})
            combined['people']['max_count'] = max(
                combined['people']['max_count'],
                people_data.get('max_count', 0)
            )

            if people_data.get('multiple_speakers', False):
                combined['people']['multiple_speakers'] = True

            # Merge speakers (chunk-scoped IDs to avoid collisions)
            for speaker in elements.get('speakers', []):
                speaker_copy = speaker.copy()
                speaker_id = speaker_copy.get('speaker_id', 'Speaker')
                speaker_copy['speaker_id'] = f"Chunk{chunk_index + 1}_{speaker_id}"
                combined['speakers'].append(speaker_copy)

        # Convert indexes back to lists
        combined['equipment'] = list(equipment_index.values())
        combined['topics_discussed'] = list(topics_index.values())

        # Sort equipment by number of time ranges (most frequently visible first)
        combined['equipment'].sort(
            key=lambda e: len(e.get('time_ranges', [])),
            reverse=True
        )

        # Sort topics by importance
        importance_rank = {'high': 3, 'medium': 2, 'low': 1}
        combined['topics_discussed'].sort(
            key=lambda t: importance_rank.get(t.get('importance', 'low'), 0),
            reverse=True
        )

        if combined['speakers'] and not combined['people'].get('multiple_speakers'):
            combined['people']['multiple_speakers'] = len(combined['speakers']) > 1

        topics_summary = []
        for topic in combined['topics_discussed']:
            name = str(topic.get('topic', '')).strip()
            if not name:
                continue
            topics_summary.append({
                'topic': name,
                'importance': topic.get('importance', 'medium'),
                'time_range_count': len(topic.get('time_ranges', []))
            })

        combined['topics_summary'] = topics_summary

        logger.info(f"Combined {len(combined['equipment'])} equipment items, "
                   f"{len(combined['topics_discussed'])} topics from {len(chunk_results)} chunks")

        return combined

    # Helper methods

    def _format_time_range(self, start_sec: float, end_sec: float) -> str:
        """Format time range as MM:SS - MM:SS."""
        start_min, start_s = divmod(int(start_sec), 60)
        end_min, end_s = divmod(int(end_sec), 60)
        return f"{start_min}:{start_s:02d} - {end_min}:{end_s:02d}"

    def _get_chapter_start_seconds(self, chapter: Dict[str, Any]) -> float:
        """Extract chapter start time in seconds from various formats."""
        # Check for start_seconds field
        if 'start_seconds' in chapter:
            return float(chapter['start_seconds'])

        # Parse MM:SS format
        if 'start_time' in chapter:
            parts = str(chapter['start_time']).split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])

        # Default to 0 if unable to parse
        logger.warning(f"Unable to parse start time for chapter: {chapter}")
        return 0.0

    def _get_model_id(self, model: str) -> str:
        """Get full Bedrock model ID from short name."""
        model_ids = {
            'micro': 'us.amazon.nova-micro-v1:0',
            'lite': 'us.amazon.nova-lite-v1:0',
            'pro': 'us.amazon.nova-pro-v1:0',
            'pro_2_preview': 'us.amazon.nova-pro-v2:0',
            'omni_2_preview': 'us.amazon.nova-omni-v2:0',
            'premier': 'us.amazon.nova-premier-v1:0'
        }

        if model not in model_ids:
            raise AggregatorError(f"Invalid model: {model}. Choose from: {list(model_ids.keys())}")

        return model_ids[model]
