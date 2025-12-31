"""Prompt templates for Nova image analysis."""
import json
from typing import Dict, Any, List, Optional

from app.services.nova.parsers import load_waterfall_assets


def get_image_description_prompt(depth: str = 'standard') -> str:
    """
    Generate prompt for comprehensive image description.

    Args:
        depth: 'brief', 'standard', or 'detailed'

    Returns:
        Prompt string for image description analysis
    """
    word_targets = {
        'brief': '100-150',
        'standard': '250-350',
        'detailed': '500-700'
    }

    word_count = word_targets.get(depth, '250-350')

    return f"""Analyze this image and provide a comprehensive description.

OUTPUT STRUCTURE:
{{
  "description": {{
    "overview": "1-2 sentence high-level summary",
    "detailed": "2-4 paragraph detailed description ({word_count} words) covering:
      - Primary subject and focal point
      - Setting and environment
      - Activities or state captured
      - Notable details and context
      - Technical/professional observations if relevant"
  }},
  "scene_type": "outdoor|indoor|studio|construction_site|residential|commercial|industrial|natural|etc",
  "primary_subject": "main focus of the image",
  "context": "situational context - what is happening in this image",
  "mood_atmosphere": "visual mood, lighting description, time of day if determinable",
  "technical_observations": "professional/technical notes if applicable (construction phase, installation quality, materials used, etc.)"
}}

GUIDELINES:
- Be specific and descriptive, not generic
- Note professional equipment, materials, or techniques visible
- Identify construction phases, product installations, or work in progress
- Describe quality, condition, and craftsmanship where visible
- Note environmental conditions (weather, lighting, season)
- For waterfall/pool images: describe water features, materials, construction details
- For product images: describe condition, installation state, brand/model if visible

OUTPUT REQUIREMENTS:
Return ONLY raw JSON - no markdown code fences, no explanatory text.
"""


def get_image_elements_prompt() -> str:
    """
    Generate prompt for visual elements extraction from image.

    Returns:
        Prompt string for elements analysis
    """
    return """Analyze this image and identify all visual elements in detail.

OUTPUT STRUCTURE:
{
  "equipment": [
    {
      "name": "specific equipment name",
      "category": "tools|machinery|vehicles|materials|safety|electronics|waterfall_component|pool_equipment|etc",
      "location_in_image": "foreground|background|left|right|center|top|bottom",
      "prominence": "primary|secondary|incidental",
      "condition": "new|used|in-use|installed|damaged|etc",
      "confidence": "high|medium|low"
    }
  ],
  "objects": [
    {
      "name": "object name",
      "category": "structure|natural|manufactured|furniture|landscape|etc",
      "material": "material if identifiable",
      "description": "brief description"
    }
  ],
  "structures": [
    {
      "type": "building|pool|waterfall|spillway|retaining_wall|deck|patio|etc",
      "description": "detailed description",
      "materials": ["visible materials used"],
      "construction_phase": "planning|foundation|framing|installation|finishing|complete|etc"
    }
  ],
  "people": {
    "count": 0,
    "descriptions": ["role-based descriptions: 'worker in safety vest', 'customer viewing installation', 'installer working on spillway'"],
    "activities": ["what people are doing"]
  },
  "text_visible": [
    {
      "text": "exact readable text",
      "location": "position in image",
      "type": "sign|label|document|logo|watermark|license_plate|brand_name|model_number|etc",
      "relevance": "high|medium|low"
    }
  ],
  "materials": {
    "primary": ["main visible materials: natural stone, concrete, steel, etc"],
    "secondary": ["supporting materials: rebar, mortar, sealant, etc"],
    "finishes": ["surface treatments visible: polished, textured, painted, sealed, etc"]
  },
  "environment": {
    "setting": "indoor|outdoor|mixed",
    "location_type": "residential|commercial|industrial|natural|jobsite|showroom|etc",
    "weather_conditions": "if outdoor: sunny, cloudy, rainy, snowy, etc",
    "time_of_day": "morning|afternoon|evening|night (if determinable from lighting)"
  }
}

GUIDELINES:
- Be specific with equipment/product names when identifiable
- Note brand names, model numbers, or SKUs if visible (especially for waterfall products)
- Identify construction materials and techniques
- Describe the construction/installation phase if applicable
- Note safety equipment and PPE if present
- For waterfalls: identify spillway types, rock types, pump equipment, lighting
- For pools: identify liner type, coping, decking materials, equipment visible
- Extract all readable text including product labels, brand names, license plates

OUTPUT REQUIREMENTS:
Return ONLY raw JSON - no markdown code fences, no explanatory text.
"""


def get_image_waterfall_prompt() -> str:
    """
    Generate prompt for waterfall classification in images.
    Uses the same taxonomy as video waterfall classification.

    Returns:
        Prompt string for waterfall classification
    """
    decision_tree, spec = load_waterfall_assets()
    spec_json = json.dumps(spec, indent=2, ensure_ascii=True)

    return f"""You are classifying waterfall content in a static image.

This is a SEQUENTIAL 4-step classification process. You must:
1. First determine FAMILY (boulder vs no boulder, then kit vs custom)
2. Then determine FUNCTIONAL TYPE (slide and/or grotto detection)
3. Then determine TIER LEVEL (size/complexity assessment)
4. Finally determine SUB-TYPE (water path analysis)

Each step builds on the previous. Follow this order strictly as defined in the spec.

EVIDENCE PRIORITY (use this ranking):
1. Visual evidence (HIGHEST) - geometry, materials, physical features
2. Text visible in image - brand names, product labels, model numbers
3. Context / environment cues - equipment visible, scale, installation setting

CRITICAL: The family taxonomy uses a 4-type model:
- Custom Natural Stone (boulders + custom)
- Custom Formal (no boulders + custom)
- Genesis Natural (boulders + kit)
- Genesis Formal (no boulders + kit)

First split on BOULDER PRESENCE, then split on KIT vs CUSTOM.

CONFIDENCE & UNKNOWN POLICY:
- Minimum confidence threshold: 0.70 (0.75 for functional_type)
- If confidence is below threshold, set dimension to "Unknown" with reason
- DO NOT GUESS - use "Unknown" when evidence is insufficient
- Overall confidence = minimum of all four dimension confidences
- If there is no waterfall content in the image, set all four dimensions to "Unknown" and explain why

Additionally, for search optimization, provide:

1. "search_tags": Array of 5-10 lowercase keywords for semantic search
   - Include product family, type, tier variations
   - Include visible features (materials, installation state, etc.)

2. "product_keywords": Array of exact product names/model numbers visible
   - Extract from labels, packaging, or visible branding
   - Include SKUs if visible

3. "installation_state": One of:
   - "pre_installation" - Product before installation
   - "during_installation" - Installation in progress
   - "completed" - Finished installation
   - "product_only" - Product display/showroom

4. "visible_components": Array of specific waterfall components visible:
   - E.g., ["spillway", "basin", "pump", "lighting", "weir", "decorative_rocks"]

OUTPUT REQUIREMENTS:
Return ONLY raw JSON - no markdown code fences, no explanatory text.

WATERFALL CLASSIFICATION SPECIFICATION:
{spec_json}
"""


def get_image_metadata_prompt(file_context: Dict[str, Any]) -> str:
    """
    Generate prompt for metadata extraction from image.

    Args:
        file_context: Dictionary containing:
            - filename: str
            - path_segments: List[str]
            - file_date: str
            - exif_capture_date: Optional[str]
            - exif_gps: Optional[Dict] with latitude/longitude
            - exif_camera: Optional[str]
            - exif_description: Optional[str]

    Returns:
        Prompt string for metadata extraction
    """
    filename = file_context.get('filename', 'unknown')
    path_segments = file_context.get('path_segments', [])
    file_date = file_context.get('file_date', 'unknown')
    exif_capture_date = file_context.get('exif_capture_date')
    exif_gps = file_context.get('exif_gps')
    exif_camera = file_context.get('exif_camera', 'unknown')
    exif_description = file_context.get('exif_description')

    path_string = ' / '.join(path_segments) if path_segments else 'unknown'

    exif_section = "EXIF DATA (pre-extracted, use as authoritative when available):\n"
    if exif_capture_date:
        exif_section += f"- Capture date: {exif_capture_date}\n"
    if exif_gps:
        exif_section += f"- GPS coordinates: {exif_gps.get('latitude')}, {exif_gps.get('longitude')}\n"
    if exif_camera and exif_camera != 'unknown':
        exif_section += f"- Camera: {exif_camera}\n"
    if exif_description:
        exif_section += f"- Original description: {exif_description}\n"

    if not any([exif_capture_date, exif_gps, exif_camera != 'unknown', exif_description]):
        exif_section += "- No EXIF data available\n"

    return f"""Extract metadata from the image content, file path, and EXIF data.

FILE CONTEXT:
- Filename: {filename}
- Path segments: {path_string}
- File date: {file_date}

{exif_section}

EXTRACT THE FOLLOWING:

1. RECORDING DATE (Priority order):
   1. EXIF capture_date (most reliable if present) - SET date_source to "exif"
   2. Visual cues: timestamps visible in image, date displays, seasonal indicators
   3. Path patterns: YYYYMMDD, YYYY-MM-DD formats in path/filename
   - Output: ISO YYYY-MM-DD format
   - Set date_source appropriately

2. LOCATION (Priority order):
   1. EXIF GPS coordinates (if present) - SET location_source to "exif"
   2. Visible addresses, street signs, landmarks in the image
   3. License plates (state identification)
   4. Architectural/environmental regional indicators
   5. Path segments containing city/state names
   - Include GPS coordinates if from EXIF
   - Set location_source appropriately

3. CUSTOMER/PROJECT NAME:
   - Path segments (often first folder after drive = customer name)
   - Visible signage, logos, or labels in the image
   - Project identifiers in filename
   - Set name_source to "path", "filename", "visual", or "unknown"

4. KEYWORDS:
   - 8-20 descriptive search terms
   - Include: subject, setting, materials, techniques, products visible
   - Include brand names, product types, construction phases
   - Use lowercase, specific terms

OUTPUT STRUCTURE:
{{
  "recording_date": {{
    "date": "YYYY-MM-DD or null",
    "date_source": "exif|visual|path|filename|unknown",
    "confidence": 0.0,
    "raw_date_string": "original pattern found if any"
  }},
  "project": {{
    "customer_name": "extracted name or null",
    "project_name": "extracted project or null",
    "name_source": "path|filename|visual|unknown",
    "name_confidence": 0.0,
    "project_code": "code if found",
    "job_number": "number if found"
  }},
  "location": {{
    "site_name": "identifiable site name or null",
    "city": "extracted city or null",
    "state_region": "state/region or null",
    "country": "country or null",
    "gps_coordinates": {{"latitude": 0.0, "longitude": 0.0}},
    "location_source": "exif|visual|path|filename|unknown",
    "location_confidence": 0.0
  }},
  "exif": {{
    "capture_date": "{exif_capture_date or 'null'}",
    "gps": {exif_gps or 'null'},
    "camera": "{exif_camera}",
    "original_description": "{exif_description or 'null'}"
  }},
  "entities": [
    {{
      "entity": "extracted entity (name, location, product, etc.)",
      "entity_type": "person|organization|location|product|event",
      "source": "path|filename|visual|exif",
      "confidence": 0.0
    }}
  ],
  "keywords": ["8-20 search tags"]
}}

CRITICAL RULES:
- Use null when evidence is missing - DO NOT GUESS
- ALWAYS set source fields to indicate where information came from
- Prioritize EXIF data as most reliable when present
- Include confidence scores (0.0-1.0) based on evidence strength
- Extract all visible text and brands as entities or keywords

OUTPUT REQUIREMENTS:
Return ONLY raw JSON - no markdown code fences, no explanatory text.
"""


def get_image_combined_prompt(
    analysis_types: List[str],
    file_context: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generate a combined prompt for all requested image analysis types.
    This enables a single API call to get all results.

    Args:
        analysis_types: List of analysis types to include:
            - 'description': Comprehensive image description
            - 'elements': Visual elements extraction
            - 'waterfall': Waterfall classification
            - 'metadata': Metadata extraction
        file_context: Optional file context for metadata extraction

    Returns:
        Combined prompt string requesting all analyses in a single JSON response
    """
    if not analysis_types:
        raise ValueError("At least one analysis type must be specified")

    file_context = file_context or {}

    sections = []
    output_structure = {}

    # Build the combined prompt sections
    if 'description' in analysis_types:
        sections.append("""
=== TASK 1: IMAGE DESCRIPTION ===
Provide a comprehensive description of this image.
""" + get_image_description_prompt().split('OUTPUT STRUCTURE:')[0])
        output_structure['description'] = {
            'overview': 'string',
            'detailed': 'string',
            'scene_type': 'string',
            'primary_subject': 'string',
            'context': 'string',
            'mood_atmosphere': 'string',
            'technical_observations': 'string'
        }

    if 'elements' in analysis_types:
        sections.append("""
=== TASK 2: VISUAL ELEMENTS ===
Identify all visual elements in this image.
""" + get_image_elements_prompt().split('OUTPUT STRUCTURE:')[0])
        output_structure['elements'] = {
            'equipment': 'array',
            'objects': 'array',
            'structures': 'array',
            'people': 'object',
            'text_visible': 'array',
            'materials': 'object',
            'environment': 'object'
        }

    if 'waterfall' in analysis_types:
        sections.append("""
=== TASK 3: WATERFALL CLASSIFICATION ===
Classify waterfall content if present in this image.
""")
        output_structure['waterfall_classification'] = {
            'family': 'string',
            'functional_type': 'string',
            'tier_level': 'string',
            'sub_type': 'string',
            'search_tags': 'array',
            'product_keywords': 'array'
        }

    if 'metadata' in analysis_types:
        sections.append(f"""
=== TASK 4: METADATA EXTRACTION ===
Extract metadata from image content, EXIF data, and file context.

FILE CONTEXT:
- Filename: {file_context.get('filename', 'unknown')}
- Path segments: {' / '.join(file_context.get('path_segments', [])) or 'unknown'}
- EXIF capture date: {file_context.get('exif_capture_date') or 'not available'}
- EXIF GPS: {file_context.get('exif_gps') or 'not available'}
- EXIF camera: {file_context.get('exif_camera', 'unknown')}
""")
        output_structure['metadata'] = {
            'recording_date': 'object',
            'project': 'object',
            'location': 'object',
            'exif': 'object',
            'entities': 'array',
            'keywords': 'array'
        }

    # Build the complete combined prompt
    tasks_section = "\n".join(sections)

    output_structure_json = json.dumps(output_structure, indent=2)

    combined = f"""You are analyzing a static image. Complete ALL of the following tasks and return results in a single JSON response.

{tasks_section}

CRITICAL OUTPUT FORMAT:
Return a SINGLE JSON object with top-level keys matching the tasks:

{output_structure_json}

RULES:
- Return ONLY raw JSON - no markdown code fences, no explanatory text
- Include ALL requested analysis types in the response
- Use null for missing values, do not guess
- Be specific and detailed in descriptions
- Include confidence scores where requested
- Extract all visible text and identifiable elements

Begin your analysis now and return the complete JSON response.
"""

    return combined
