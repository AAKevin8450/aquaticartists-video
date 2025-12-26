"""
Routes for unified search functionality.
"""
from flask import Blueprint, request, jsonify, render_template
from app.database import get_db
from typing import Optional, List, Dict, Any
import time
import json
import re
import logging

# Import for semantic search
from app.services.embedding_manager import EmbeddingManager

logger = logging.getLogger(__name__)

bp = Blueprint('search', __name__, url_prefix='/search')


def extract_preview_text(source_type: str, row: Dict[str, Any], query: str, max_length: int = 150) -> str:
    """
    Extract preview text from search result with context around the matched term.

    Args:
        source_type: Type of search result (file, transcript, rekognition, nova, collection)
        row: Database row dict
        query: Search query
        max_length: Maximum preview length in characters

    Returns:
        Preview text with ellipsis if truncated
    """
    text = ""

    # Extract the most relevant text based on source type
    if source_type == 'file':
        # For files, use filename or metadata
        text = row.get('title', '')
        metadata = row.get('metadata')
        if metadata and isinstance(metadata, str):
            try:
                metadata_dict = json.loads(metadata)
                if metadata_dict:
                    text += f" - {str(metadata_dict)[:100]}"
            except:
                pass

    elif source_type == 'transcript':
        # For transcripts, try to find context around the search term
        db = get_db()
        transcript_id = row.get('source_id')
        if transcript_id:
            transcript = db.get_transcript(transcript_id)
            if transcript and transcript.get('transcript_text'):
                full_text = transcript['transcript_text']
                text = _extract_context(full_text, query, max_length)
                if text:
                    return text
        text = row.get('title', '')

    elif source_type == 'rekognition':
        # For Rekognition, try to extract relevant analysis results
        db = get_db()
        job_id = row.get('source_id')
        if job_id:
            job = db.get_job(job_id)
            if job and job.get('results'):
                results = job['results']
                if isinstance(results, str):
                    try:
                        results = json.loads(results)
                    except:
                        pass

                # Extract relevant fields based on analysis type
                category = row.get('category', '')
                if 'label_detection' in category.lower():
                    text = _extract_label_preview(results, query)
                elif 'celebrity' in category.lower():
                    text = _extract_celebrity_preview(results, query)
                elif 'text_detection' in category.lower():
                    text = _extract_text_detection_preview(results, query)
                else:
                    text = f"{row.get('title', '')} - {category}"
        if not text:
            text = row.get('title', '')

    elif source_type == 'nova':
        # For Nova, extract from summary, chapters, or elements
        db = get_db()
        nova_id = row.get('source_id')
        if nova_id:
            nova_job = db.get_nova_job(nova_id)
            if nova_job:
                match_field = row.get('match_field', 'summary')
                if match_field == 'summary' and nova_job.get('summary_result'):
                    summary = nova_job['summary_result']
                    if isinstance(summary, str):
                        try:
                            summary = json.loads(summary)
                        except:
                            pass
                    if isinstance(summary, dict):
                        text = summary.get('text', str(summary)[:max_length])
                    else:
                        text = str(summary)[:max_length]
                elif match_field == 'chapters' and nova_job.get('chapters_result'):
                    chapters = nova_job['chapters_result']
                    if isinstance(chapters, str):
                        try:
                            chapters = json.loads(chapters)
                        except:
                            pass
                    if isinstance(chapters, list) and len(chapters) > 0:
                        # Find chapter that matches the query
                        for chapter in chapters:
                            if isinstance(chapter, dict):
                                title = chapter.get('title', '')
                                summary = chapter.get('summary', '')
                                if query.lower() in title.lower() or query.lower() in summary.lower():
                                    text = f"{title}: {summary}"
                                    break
                        if not text:
                            # Use first chapter as fallback
                            first_chapter = chapters[0]
                            if isinstance(first_chapter, dict):
                                text = f"{first_chapter.get('title', '')}: {first_chapter.get('summary', '')}"
                elif match_field == 'elements' and nova_job.get('elements_result'):
                    elements = nova_job['elements_result']
                    if isinstance(elements, str):
                        try:
                            elements = json.loads(elements)
                        except:
                            text = elements[:max_length]
                    if isinstance(elements, dict):
                        text = str(elements)[:max_length]
                elif match_field == 'waterfall_classification' and nova_job.get('waterfall_classification_result'):
                    classification = nova_job['waterfall_classification_result']
                    if isinstance(classification, str):
                        try:
                            classification = json.loads(classification)
                        except:
                            text = classification[:max_length]
                    if isinstance(classification, dict):
                        family = classification.get('family', '')
                        tier = classification.get('tier_level', '')
                        functional = classification.get('functional_type', '')
                        subtype = classification.get('sub_type', '')
                        parts = [v for v in [family, tier, functional, subtype] if v and v != 'Unknown']
                        
                        # Add search tags if available
                        search_tags = classification.get('search_tags', [])
                        if isinstance(search_tags, list) and search_tags:
                            parts.append(f"Tags: {', '.join(search_tags[:3])}")
                            
                        text = " | ".join(parts) or str(classification)[:max_length]
                        
                elif match_field == 'search_metadata' and nova_job.get('search_metadata'):
                    metadata = nova_job['search_metadata']
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except:
                            text = metadata[:max_length]
                    if isinstance(metadata, dict):
                        parts = []
                        project = metadata.get('project', {})
                        location = metadata.get('location', {})
                        water_feature = metadata.get('water_feature', {})
                        
                        if project.get('customer_name') and project.get('customer_name') != 'unknown':
                            parts.append(f"Customer: {project['customer_name']}")
                        if project.get('project_name') and project.get('project_name') != 'unknown':
                            parts.append(f"Project: {project['project_name']}")
                        if location.get('city') and location.get('city') != 'unknown':
                            loc = location['city']
                            if location.get('state_region') and location.get('state_region') != 'unknown':
                                loc += f", {location['state_region']}"
                            parts.append(f"Loc: {loc}")
                        if water_feature.get('family') and water_feature.get('family') != 'unknown':
                            parts.append(f"WF: {water_feature['family']}")
                            
                        text = " | ".join(parts) or "Metadata found"
        if not text:
            text = row.get('title', '')

    elif source_type == 'face_collection':
        text = f"Face Collection: {row.get('title', '')}"

    # Truncate to max_length
    if len(text) > max_length:
        text = text[:max_length] + "..."

    return text if text else row.get('title', 'No preview available')


def _extract_context(text: str, query: str, max_length: int = 150) -> str:
    """Extract text context around the search query."""
    if not text or not query:
        return text[:max_length] if text else ""

    # Find the first occurrence of the query (case-insensitive)
    query_lower = query.lower()
    text_lower = text.lower()

    pos = text_lower.find(query_lower)
    if pos == -1:
        # Query not found, return beginning of text
        return text[:max_length] + ("..." if len(text) > max_length else "")

    # Calculate how much context to show before and after
    half_length = max_length // 2

    # Determine start position
    start = max(0, pos - half_length)

    # Determine end position
    end = min(len(text), pos + len(query) + half_length)

    # Extract the substring
    excerpt = text[start:end]

    # Add ellipsis if truncated
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(text):
        excerpt = excerpt + "..."

    return excerpt


def _extract_label_preview(results: Any, query: str) -> str:
    """Extract preview text from label detection results."""
    if not isinstance(results, dict):
        return ""

    labels = []

    # Extract labels from different result structures
    if 'Labels' in results:
        for label in results['Labels'][:5]:  # Top 5 labels
            if isinstance(label, dict):
                name = label.get('Name', '')
                confidence = label.get('Confidence', 0)
                if name:
                    labels.append(f"{name} ({confidence:.0f}%)")

    return f"Detected: {', '.join(labels)}" if labels else ""


def _extract_celebrity_preview(results: Any, query: str) -> str:
    """Extract preview text from celebrity recognition results."""
    if not isinstance(results, dict):
        return ""

    celebrities = []

    if 'Celebrities' in results:
        for celeb in results['Celebrities'][:5]:
            if isinstance(celeb, dict):
                name = celeb.get('Name', '')
                confidence = celeb.get('Confidence', 0)
                if name:
                    celebrities.append(f"{name} ({confidence:.0f}%)")

    return f"Celebrities: {', '.join(celebrities)}" if celebrities else ""


def _extract_text_detection_preview(results: Any, query: str) -> str:
    """Extract preview text from text detection results."""
    if not isinstance(results, dict):
        return ""

    detected_texts = []

    if 'TextDetections' in results:
        for text_item in results['TextDetections'][:10]:
            if isinstance(text_item, dict):
                detected_text = text_item.get('DetectedText', '')
                if detected_text and len(detected_text) > 2:  # Skip very short text
                    detected_texts.append(detected_text)

    return f"Text: {', '.join(detected_texts[:5])}" if detected_texts else ""


def build_action_links(source_type: str, row: Dict[str, Any]) -> Dict[str, str]:
    """Build action links for a search result based on its type."""
    actions = {}
    source_id = row.get('source_id')

    if source_type == 'file':
        actions['view'] = f'/files?id={source_id}'
        actions['download'] = f'/api/files/{source_id}/download'

    elif source_type == 'transcript':
        actions['view'] = f'/files?highlight=transcript_{source_id}'
        actions['view_transcript'] = f'/transcriptions?id={source_id}'
        actions['download'] = f'/transcriptions/api/transcript/{source_id}/download?format=txt'

    elif source_type == 'rekognition':
        # Get the job details to find the dashboard link
        actions['view'] = f'/files?job_id={source_id}'
        actions['view_dashboard'] = f'/dashboard/{source_id}'
        actions['download_json'] = f'/api/history/{source_id}?format=json'

    elif source_type == 'nova':
        actions['view'] = f'/files?nova_id={source_id}'
        actions['view_results'] = f'/api/nova/results/{source_id}'

    elif source_type == 'face_collection':
        actions['view'] = f'/collections?id={source_id}'

    return actions


@bp.route('/')
def index():
    """Render the search page."""
    return render_template('search.html')


@bp.route('/api/search', methods=['GET'])
def search():
    """
    Unified search API endpoint.

    Query Parameters:
        q: Search query (required, min 2 chars)
        sources: Comma-separated list of sources (file,transcript,rekognition,nova,collection)
        file_type: Filter by file type (video/image)
        from_date: Start date filter (YYYY-MM-DD)
        to_date: End date filter (YYYY-MM-DD)
        status: Filter by status
        analysis_type: Filter by Rekognition analysis type
        model: Filter by model (Whisper or Nova)
        sort_by: Sort field (relevance/date/name, default: relevance)
        sort_order: Sort order (asc/desc, default: desc)
        page: Page number (default: 1)
        per_page: Results per page (default: 50, max: 200)

    Returns:
        JSON response with search results and pagination
    """
    start_time = time.time()

    # Get query parameters
    query = request.args.get('q', '').strip()
    semantic = request.args.get('semantic', 'false').lower() == 'true'
    sources_str = request.args.get('sources', '')
    file_type = request.args.get('file_type')
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    status = request.args.get('status')
    analysis_type = request.args.get('analysis_type')
    model = request.args.get('model')
    sort_by = request.args.get('sort_by', 'relevance')
    sort_order = request.args.get('sort_order', 'desc')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Validate query
    if not query:
        return jsonify({
            'error': 'Search query required',
            'details': "Parameter 'q' must be provided"
        }), 400

    if len(query) < 2:
        return jsonify({
            'error': 'Search query too short',
            'details': "Parameter 'q' must be at least 2 characters"
        }), 400

    if len(query) > 500:
        return jsonify({
            'error': 'Search query too long',
            'details': "Parameter 'q' must be at most 500 characters"
        }), 400

    # Validate pagination
    if page < 1:
        page = 1
    if per_page < 10:
        per_page = 10
    if per_page > 200:
        per_page = 200

    # Parse sources
    sources = None
    if sources_str:
        sources = [s.strip() for s in sources_str.split(',') if s.strip()]
        valid_sources = {'file', 'transcript', 'rekognition', 'nova', 'collection'}
        sources = [s for s in sources if s in valid_sources]
        if not sources:
            sources = None

    # Calculate offset
    offset = (page - 1) * per_page

    # Route to semantic search if enabled
    if semantic and query:
        return semantic_search(
            query=query,
            sources=sources,
            page=page,
            per_page=per_page,
            start_time=start_time
        )

    # Execute search (keyword search)
    try:
        db = get_db()

        # Get search results
        results = db.search_all(
            query=query,
            sources=sources,
            file_type=file_type,
            from_date=from_date,
            to_date=to_date,
            status=status,
            analysis_type=analysis_type,
            model=model,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=per_page,
            offset=offset
        )

        # Get result counts
        counts = db.count_search_results(
            query=query,
            sources=sources,
            file_type=file_type,
            from_date=from_date,
            to_date=to_date,
            status=status,
            analysis_type=analysis_type,
            model=model
        )

        # Build response
        response_results = []
        for row in results:
            source_type = row['source_type']

            # Generate preview text
            preview = extract_preview_text(source_type, row, query)

            # Build action links
            actions = build_action_links(source_type, row)

            # Build metadata
            metadata = {
                'source_id': row.get('source_id'),
                'match_field': row.get('match_field'),
                'size_bytes': row.get('size_bytes'),
                'duration_seconds': row.get('duration_seconds')
            }

            response_results.append({
                'id': f"{source_type}_{row['source_id']}",
                'source_type': source_type,
                'source_id': row['source_id'],
                'title': row['title'],
                'category': row['category'],
                'timestamp': row['timestamp'],
                'match_field': row.get('match_field'),
                'preview': preview,
                'metadata': metadata,
                'actions': actions
            })

        # Calculate pagination
        total_results = counts.get('total', 0)
        total_pages = (total_results + per_page - 1) // per_page

        # Calculate search time
        search_time_ms = int((time.time() - start_time) * 1000)

        return jsonify({
            'query': query,
            'total_results': total_results,
            'results_by_source': {
                'file': counts.get('file', 0),
                'transcript': counts.get('transcript', 0),
                'rekognition': counts.get('rekognition', 0),
                'nova': counts.get('nova', 0),
                'collection': counts.get('collection', 0)
            },
            'results': response_results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_results,
                'pages': total_pages
            },
            'filters_applied': {
                'sources': sources,
                'file_type': file_type,
                'from_date': from_date,
                'to_date': to_date,
                'status': status,
                'analysis_type': analysis_type,
                'model': model
            },
            'search_time_ms': search_time_ms
        })

    except Exception as e:
        return jsonify({
            'error': 'Search failed',
            'details': str(e)
        }), 500


@bp.route('/api/search/filters', methods=['GET'])
def get_filters():
    """
    Get available filter options for search.

    Returns:
        JSON response with filter options
    """
    try:
        db = get_db()
        filters = db.get_search_filters()

        return jsonify(filters)

    except Exception as e:
        return jsonify({
            'error': 'Failed to get filters',
            'details': str(e)
        }), 500


@bp.route('/api/search/suggestions', methods=['GET'])
def get_suggestions():
    """
    Get search query suggestions (autocomplete).

    Query Parameters:
        q: Partial search query (min 2 chars)

    Returns:
        JSON response with suggestions
    """
    query = request.args.get('q', '').strip()

    if len(query) < 2:
        return jsonify({
            'query': query,
            'suggestions': []
        })

    # For now, return static suggestions
    # TODO: Implement dynamic suggestions based on popular searches
    static_suggestions = [
        'video analysis',
        'image detection',
        'face recognition',
        'text detection',
        'label detection',
        'content moderation',
        'transcript',
        'summary',
        'chapters'
    ]

    # Filter suggestions that contain the query
    query_lower = query.lower()
    matching_suggestions = [s for s in static_suggestions if query_lower in s.lower()]

    return jsonify({
        'query': query,
        'suggestions': matching_suggestions[:10]
    })


def semantic_search(
    query: str,
    sources: Optional[List[str]],
    page: int,
    per_page: int,
    start_time: float
) -> Any:
    """
    Perform semantic vector search using Nova embeddings.

    Args:
        query: Search query text
        sources: List of source types to search (file, transcript, rekognition, nova, collection)
        page: Page number
        per_page: Results per page
        start_time: Request start time for performance tracking

    Returns:
        JSON response with semantic search results
    """
    try:
        db = get_db()
        manager = EmbeddingManager(db)

        # Generate query embedding (optimized for retrieval)
        query_embedding = manager.embeddings_service.embed_query(query)

        # Map source names to source_types for embedding search
        # Only transcript and nova_analysis have embeddings
        source_type_map = {
            'transcript': 'transcript',
            'nova': 'nova_analysis'
        }

        # Filter sources to only those that support semantic search
        if sources:
            filtered_sources = []
            for s in sources:
                if s in source_type_map:
                    filtered_sources.append(source_type_map[s])
            source_types = filtered_sources if filtered_sources else None
        else:
            # Default to both transcript and nova_analysis
            source_types = ['transcript', 'nova_analysis']

        # Vector search (fetch enough for pagination)
        results = db.search_embeddings(
            query_vector=query_embedding,
            limit=per_page * page,  # Fetch enough for current page
            source_types=source_types if source_types else None,
            min_similarity=0.0  # No minimum threshold by default
        )

        # Paginate results
        start = (page - 1) * per_page
        paginated = results[start:start + per_page]

        # Enrich with actual content
        enriched = db.get_content_for_embedding_results(paginated)

        # Format response to match existing search API
        response_results = []
        for r in enriched:
            # Map source_type back to frontend naming
            source_display = 'transcript' if r['source_type'] == 'transcript' else 'nova'

            response_results.append({
                'id': f"{source_display}_{r['source_id']}",
                'source_type': source_display,
                'source_id': r['source_id'],
                'title': r.get('title', 'Unknown'),
                'category': source_display.capitalize(),
                'timestamp': r.get('created_at', ''),
                'match_field': 'semantic',
                'preview': r.get('preview', ''),
                'metadata': {
                    'source_id': r['source_id'],
                    'similarity': round(r.get('similarity', 0), 3),
                    'distance': round(r.get('distance', 0), 3)
                },
                'actions': build_action_links(source_display, r)
            })

        # Calculate pagination
        total_results = len(results)
        total_pages = (total_results + per_page - 1) // per_page

        # Calculate search time
        search_time_ms = int((time.time() - start_time) * 1000)

        # Count results by source
        source_counts = {'transcript': 0, 'nova': 0, 'file': 0, 'rekognition': 0, 'collection': 0}
        for r in results:
            if r['source_type'] == 'transcript':
                source_counts['transcript'] += 1
            elif r['source_type'] == 'nova_analysis':
                source_counts['nova'] += 1

        return jsonify({
            'query': query,
            'total_results': total_results,
            'results_by_source': source_counts,
            'results': response_results,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_results,
                'pages': total_pages
            },
            'filters_applied': {
                'sources': sources,
                'semantic': True
            },
            'search_time_ms': search_time_ms,
            'semantic': True
        })

    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return jsonify({
            'error': 'Semantic search failed',
            'details': str(e),
            'fallback': 'Try disabling semantic search or check that embeddings have been generated'
        }), 500
