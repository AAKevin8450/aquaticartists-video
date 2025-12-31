"""Prompt templates for Nova video analysis."""
import json
import re
from typing import Optional, Dict, Any, List

from app.services.nova.parsers import load_waterfall_assets


def normalize_file_context(filename: Optional[str], file_path: Optional[str]) -> Dict[str, Any]:
    """
    Return normalized tokens and path segments for prompting/search.

    Args:
        filename: The filename (e.g., "my_video.mp4")
        file_path: The full file path

    Returns:
        Dictionary with tokenized filename, path segments, and project-like tokens
    """
    if not filename and not file_path:
        return {}

    def tokenize(text: str) -> List[str]:
        if not text:
            return []
        # Split on common separators
        tokens = re.split(r'[_\-\.\s\\/]', text)
        # Split camelCase
        tokens = [re.sub(r'([a-z])([A-Z])', r'\1 \2', t).split() for t in tokens]
        # Flatten list
        tokens = [item for sublist in tokens for item in (sublist if isinstance(sublist, list) else [sublist])]
        # Clean and filter
        return [t.lower().strip() for t in tokens if t and t.strip()]

    filename_tokens = tokenize(filename)
    path_segments = tokenize(file_path)

    # Extract potential project/customer identifiers (heuristic)
    project_like_tokens = []
    for t in path_segments:
        # Look for job numbers or project names (often numeric or mixed)
        if re.search(r'\d', t) or len(t) > 4:
            project_like_tokens.append(t)

    # Filter out common noise words
    noise = {'video', 'videos', 'mp4', 'mov', 'final', 'v1', 'v2', 'copy', 'edited', 'training', 'products'}
    filename_tokens = [t for t in filename_tokens if t not in noise]
    path_segments = [t for t in path_segments if t not in noise]

    return {
        "filename_tokens": filename_tokens,
        "path_segments": path_segments,
        "project_like_tokens": project_like_tokens,
        "raw_filename": filename,
        "raw_path": file_path
    }


def build_contextual_prompt(
    base_prompt: str,
    filename: str = None,
    file_path: str = None,
    transcript_summary: str = None,
    filename_tokens: List[str] = None,
    path_segments: List[str] = None,
    project_like_tokens: List[str] = None,
    duration_seconds: float = None
) -> str:
    """
    Wrap base prompt with contextual metadata section.

    Args:
        base_prompt: The core analysis prompt
        filename: Original filename
        file_path: Full file path
        transcript_summary: Summary of audio transcript if available
        filename_tokens: Tokenized filename parts
        path_segments: Tokenized path parts
        project_like_tokens: Tokens that appear to be project/job identifiers
        duration_seconds: Video duration in seconds

    Returns:
        Enhanced prompt with context prepended
    """
    context_parts = []
    if filename:
        context_parts.append(f"Filename: {filename}")
    if file_path:
        context_parts.append(f"File Path: {file_path}")
    if filename_tokens:
        context_parts.append(f"Filename Tokens: {', '.join(filename_tokens)}")
    if path_segments:
        context_parts.append(f"Path Segments: {', '.join(path_segments)}")
    if project_like_tokens:
        context_parts.append(f"Project/Customer Tokens: {', '.join(project_like_tokens)}")
    if duration_seconds:
        context_parts.append(f"Duration: {duration_seconds} seconds")

    context_section = ""
    if context_parts:
        context_section = "=== FILE CONTEXT ===\n" + "\n".join(context_parts) + "\n\n"

    transcript_section = ""
    if transcript_summary:
        transcript_section = f"=== TRANSCRIPT SUMMARY ===\n{transcript_summary}\n\n"

    instructions = ""
    if context_section or transcript_section:
        instructions = """=== ANALYSIS INSTRUCTIONS ===
Use the above context to guide your analysis:

CRITICAL EXTRACTION TARGETS:
1. RECORDING DATE: Look for dates in file path (YYYYMMDD, YYYY-MM-DD, MM-DD-YYYY patterns),
   filename, transcript ("today is...", "recorded on..."), or visual timestamps. Output as YYYY-MM-DD.
2. CUSTOMER/PROJECT NAME (synonymous): Check file path (first segment after drive is often customer),
   filename (e.g., "Smith_Pool.mp4"), and transcript (property owner names, client mentions).
3. LOCATION: Check path for city/state names, transcript for "here in [city]" or address mentions,
   and video for visible addresses, business signs, or license plates indicating state.

GENERAL GUIDANCE:
- The filename often contains important keywords about the content
- The file path may indicate project/category organization
- The transcript summary provides spoken content context
- Path segments can encode customer/project/location; treat as hints with source attribution
- Always include the source (path, filename, transcript, visual) for extracted entities
- Do not invent details; use null when evidence is missing

"""

    return f"{context_section}{transcript_section}{instructions}{base_prompt}"


def get_waterfall_classification_prompt() -> str:
    """Build prompt for waterfall classification using the decision tree and spec.

    Returns:
        Complete waterfall classification prompt string
    """
    decision_tree, spec = load_waterfall_assets()
    spec_json = json.dumps(spec, indent=2, ensure_ascii=True)

    return f"""You are classifying waterfall content in a video segment.

This is a SEQUENTIAL 4-step classification process. You must:
1. First determine FAMILY (boulder vs no boulder, then kit vs custom)
2. Then determine FUNCTIONAL TYPE (slide and/or grotto detection)
3. Then determine TIER LEVEL (size/complexity assessment)
4. Finally determine SUB-TYPE (water path analysis)

Each step builds on the previous. Follow this order strictly as defined in the spec.

EVIDENCE PRIORITY (use this ranking):
1. Visual evidence (HIGHEST) - geometry, materials, physical features
2. Spoken narration / on-screen text - brand names, product terms
3. Context / environment cues - equipment, scale, jobsite complexity

Always prefer visual evidence over narration when they conflict.

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
- If there is no waterfall content, set all four dimensions to "Unknown" and explain why

Additionally, for search optimization, provide:

1. "search_tags": Array of 5-10 lowercase keywords for semantic search
   - Include product family, type, tier variations
   - Include content type (tutorial, review, demo, etc.)

2. "product_keywords": Array of exact product names/model numbers mentioned
   - Extract from filename and visual elements
   - Include brand names and SKUs if visible

3. "content_type": One of:
   - "product_overview" - General product introduction
   - "installation_tutorial" - How to install
   - "building_demonstration" - Waterfall construction
   - "troubleshooting" - Problem solving
   - "comparison" - Product comparison
   - "review" - Product review/opinion

4. "skill_level": One of:
   - "beginner", "intermediate", "advanced", "professional"

5. "building_techniques": Array of specific techniques shown:
   - E.g., ["bracket mounting", "silicone sealing", "pump sizing"]

OUTPUT REQUIREMENTS:
Return ONLY raw JSON - no markdown code fences, no explanatory text.
Output must be valid JSON parseable by json.loads().
All four dimensions are required: family, tier_level, functional_type, sub_type.
Include confidence object with per-dimension scores and overall score.
Include evidence array with specific cues observed.
Include unknown_reasons object for any "Unknown" classifications.
Include the search optimization fields defined above.

Decision Tree:
{decision_tree}

Spec:
{spec_json}
"""


def get_summary_prompt(depth: str, language: str) -> str:
    """Build summary prompt based on depth and language.

    Args:
        depth: Summary depth level ('brief', 'standard', 'detailed')
        language: Target language or 'auto' for original

    Returns:
        Summary analysis prompt string
    """
    prompts = {
        'brief': """Analyze this video and provide a concise 2-3 sentence summary of the main content and purpose.
Focus on what the video is about and its primary objective. Keep it under 50 words.""",

        'standard': """Analyze this video and provide a comprehensive summary including:

1. **Context & Purpose**: What this video is about, who it's for, and why it was created
2. **Main Topics**: The primary subjects and themes covered
3. **Key Information**: Important details, facts, techniques, or concepts presented
4. **Visual & Audio Elements**: Notable demonstrations, equipment shown, or speaker insights
5. **Conclusions & Takeaways**: What viewers should understand or be able to do after watching

Provide 2-4 well-structured paragraphs (approximately 250-350 words).
Be specific and informative, including:
- Concrete examples and specific details mentioned in the video
- Any technical specifications, product names, or model numbers discussed
- Key visual demonstrations or on-screen elements
- Relevant timestamps for important sections (e.g., "At 2:15, the presenter demonstrates...")""",

        'detailed': """Analyze this video thoroughly and provide an in-depth, comprehensive summary including:

1. **Opening & Context** (1 paragraph):
   - How the video begins and sets context
   - Purpose, intended audience, and production quality
   - Overall tone and presentation style

2. **Content Structure & Flow** (1-2 paragraphs):
   - How the video is organized and structured
   - Major sections and transitions
   - Teaching or presentation methodology used

3. **Detailed Topic Coverage** (2-3 paragraphs):
   - In-depth exploration of each major topic covered
   - Specific techniques, processes, or concepts explained
   - Technical details, specifications, measurements, or data presented
   - Equipment, tools, materials, or products featured (include brands/models)
   - Step-by-step procedures or demonstrations shown

4. **Visual & Audio Analysis** (1 paragraph):
   - Key visual elements: camera angles, graphics, on-screen text, product shots
   - Speaker delivery: expertise level, presentation quality, multiple speakers
   - Audio quality and background elements

5. **Critical Moments & Highlights** (1 paragraph):
   - Most important or impactful moments with timestamps
   - Before/after comparisons or results shown
   - Common mistakes addressed or troubleshooting tips
   - Expert tips, pro advice, or insider knowledge shared

6. **Conclusions & Practical Applications** (1 paragraph):
   - Final recommendations or summary by presenter
   - Practical takeaways viewers can implement
   - Resources mentioned or next steps suggested
   - Overall value and who would benefit most

Provide 6-10 comprehensive, detailed paragraphs (approximately 600-900 words).
Include specific examples, exact quotes when relevant, and precise timestamps for key moments.
Extract and mention any: product names, model numbers, measurements, prices, locations, dates, or technical specifications."""
    }

    prompt = prompts.get(depth, prompts['standard'])

    if language != 'auto':
        prompt += f"\n\nProvide the summary in {language} language."

    return prompt


def get_chapters_prompt() -> str:
    """Build chapter detection prompt.

    Returns:
        Chapter detection prompt string
    """
    return """Analyze this video and identify logical chapters based on content transitions and topic changes.

For each chapter, provide:
1. **Title** (3-8 words): A clear, descriptive title that indicates the chapter's content
2. **Start timestamp** (MM:SS or HH:MM:SS if duration exceeds 59:59)
3. **End timestamp** (MM:SS or HH:MM:SS if duration exceeds 59:59)
4. **Brief summary** (2-3 sentences): A concise overview of what happens in that chapter
5. **Detailed summary** (4-8 sentences, 100-200 words): An in-depth description including:
   - Specific actions, demonstrations, or explanations shown
   - Technical details, measurements, or specifications mentioned
   - Equipment, tools, or products featured
   - Key visual elements or camera shots
   - Important dialogue, quotes, or narrator insights
   - Techniques or processes demonstrated step-by-step
   - Any problems solved or challenges addressed
6. **Key points** (3-8 bullet points): Specific, actionable takeaways from this chapter

Return the results in this exact JSON format:
{
  "chapters": [
    {
      "index": 1,
      "title": "...",
      "start_time": "00:00",
      "end_time": "03:00",
      "summary": "Brief 2-3 sentence overview...",
      "detailed_summary": "Comprehensive 4-8 sentence description with specific details, timestamps, technical information, and exact procedures shown...",
      "key_points": ["Specific point 1", "Specific point 2", "Specific point 3"]
    }
  ]
}

IMPORTANT GUIDELINES:
- Create chapters that align with natural content divisions (topic changes, scene transitions, new demonstrations)
- Aim for chapters between 1-10 minutes in length where appropriate
- Use contiguous chapters that cover the full video without gaps when possible
- In detailed_summary, be VERY specific: mention exact products, measurements, techniques, and visual demonstrations
- Include relevant sub-timestamps within detailed_summary (e.g., "At 2:35 within this section, the installer...")
- Make key_points concrete and actionable, not vague generalizations
- Extract any product names, model numbers, measurements, or technical specifications mentioned

Do NOT include any text outside the JSON structure."""


def get_elements_prompt() -> str:
    """Build element identification prompt.

    Returns:
        Element identification prompt string
    """
    return """Analyze this video and identify:

1. EQUIPMENT/TOOLS: All visible equipment, tools, and devices
   For each item provide:
   - Name (be specific - include brand/model if visible)
   - Category (e.g., photography, computing, tools, kitchen, sports)
   - Time ranges when visible (format: "MM:SS-MM:SS" or single "MM:SS" if brief)
   - Whether it's discussed in audio (true/false)
   - Confidence (high/medium/low)

2. TOPICS DISCUSSED: Main topics covered in the video
   For each topic provide:
   - Topic name
   - Time ranges when discussed (format: "MM:SS-MM:SS")
   - Importance (high/medium/low)
   - Brief description (1 sentence)
   - Keywords (3-8 terms)

3. PEOPLE: Count of people visible
   - Maximum number of people visible at once
   - Whether there are multiple speakers (true/false)

4. SPEAKER DIARIZATION: If multiple speakers are present
   For each speaker provide:
   - Speaker ID (e.g., Speaker_1, Speaker_2)
   - Role (host, instructor, interviewer, guest, etc.)
   - Approximate time ranges when speaking
   - Speaking percentage (0-100)

Return as JSON:
{
  "equipment": [
    {
      "name": "...",
      "category": "...",
      "time_ranges": ["MM:SS-MM:SS"],
      "discussed": true,
      "confidence": "high"
    }
  ],
  "topics_discussed": [
    {
      "topic": "...",
      "time_ranges": ["MM:SS-MM:SS"],
      "importance": "high",
      "description": "...",
      "keywords": ["..."]
    }
  ],
  "people": {
    "max_count": 2,
    "multiple_speakers": true
  },
  "speakers": [
    {
      "speaker_id": "Speaker_1",
      "role": "...",
      "time_ranges": ["MM:SS-MM:SS"],
      "speaking_percentage": 65
    }
  ]
}

Do NOT include any text outside the JSON structure."""


def get_combined_prompt(depth: str, language: str, context: Optional[Dict[str, Any]] = None) -> str:
    """Build combined analysis prompt for a single-pass output.

    Args:
        depth: Summary depth level ('brief', 'standard', 'detailed')
        language: Target language or 'auto' for original
        context: Optional context dict with filename, file_path, transcript_summary, etc.

    Returns:
        Combined analysis prompt string with all sections
    """
    language_note = ""
    if language != 'auto':
        language_note = f"Provide the summary in {language} language."

    depth_guidance = {
        'brief': "2-3 sentences, under 50 words.",
        'standard': "2-4 paragraphs, 250-350 words, include context, main topics, key information, visual elements, and conclusions with specific details.",
        'detailed': ("6-10 paragraphs, 600-900 words, include opening context, content structure, detailed topic coverage, "
                     "visual/audio analysis, critical moments with timestamps, and practical applications.")
    }
    summary_guidance = depth_guidance.get(depth, depth_guidance['standard'])

    decision_tree, spec = load_waterfall_assets()
    spec_json = json.dumps(spec, indent=2, ensure_ascii=True)

    # Extract context fields if available
    context = context or {}
    filename = context.get('filename')
    file_path = context.get('file_path')
    transcript_summary = context.get('transcript_summary')
    filename_tokens = context.get('filename_tokens')
    path_segments = context.get('path_segments')
    project_like_tokens = context.get('project_like_tokens')
    duration_seconds = context.get('duration_seconds')

    base_prompt = f"""Analyze this video and return a SINGLE JSON object that includes all five analysis sections.

SUMMARY REQUIREMENTS:
- {summary_guidance}
- {language_note or "Use the video's original language."}
- Incorporate insights from the transcript summary if provided.
- Include specific examples, product names, technical details, and timestamps.

CHAPTERS REQUIREMENTS:
- Title (3-8 words): Clear, descriptive chapter title
- Start/end timecodes (MM:SS or HH:MM:SS)
- Summary (2-3 sentences): Brief overview of the chapter
- Detailed_summary (4-8 sentences, 100-200 words): In-depth description including:
  * Specific actions, demonstrations, or explanations shown
  * Technical details, measurements, specifications mentioned
  * Equipment, tools, or products featured with brands/models
  * Key visual elements and camera work
  * Important dialogue or narrator insights
  * Step-by-step techniques or processes
  * Problems solved or challenges addressed
- Key_points (3-8 bullets): Specific, actionable takeaways
- Chapters should be contiguous and cover the full video without gaps when possible.

ELEMENTS REQUIREMENTS:
- Equipment: name, category, time_ranges, discussed (true/false), confidence (high/medium/low).
- Topics: topic, time_ranges, importance (high/medium/low), description, keywords (3-8 terms).
- People: max_count, multiple_speakers.
- Speakers: speaker_id, role, time_ranges, speaking_percentage.

WATERFALL CLASSIFICATION REQUIREMENTS:
- Follow the sequential 4-step decision process and spec below.
- Apply Unknown rules and include confidence, evidence, unknown_reasons.
- Additionally provide "search_tags", "product_keywords", "content_type", "skill_level", "building_techniques".

SEARCH METADATA REQUIREMENTS (for discovery):

DATE EXTRACTION (CRITICAL - check all sources):
- File path patterns: YYYYMMDD, YYYY-MM-DD, YYYY_MM_DD, MM-DD-YYYY, MMDDYYYY
- Example paths: "2024-03-15_Johnson_Pool" -> recording_date: "2024-03-15"
- Transcript mentions: "today is March 15th", "recorded on...", "this was filmed in June 2023"
- Visual cues: on-screen dates, timestamps, calendars visible
- If multiple dates found, prefer the one closest to the start of the path/filename
- Output as ISO format YYYY-MM-DD when possible; null if no date evidence

CUSTOMER/PROJECT NAME EXTRACTION (these are synonymous - check all sources):
- File path: First segment after drive/root is often the customer (e.g., "E:/videos/Johnson Family/..." -> "Johnson Family")
- Filename: May contain customer name directly (e.g., "Smith_Pool_Installation.mp4" -> "Smith")
- Transcript: "Mr. Johnson", "the Smith residence", "working for ABC Pools", "this is the Martinez project"
- Look for proper nouns, family names, business names in any source
- Cross-reference across sources for higher confidence (e.g., path says "Johnson" and transcript mentions "Mr. Johnson")

LOCATION EXTRACTION (multiple sources):
- File path: city names, state abbreviations, addresses in folder names
- Transcript: "here in Phoenix", "this property in Scottsdale", "Arizona weather", street addresses
- Visual: address signs, business names with locations, license plates (state), landmarks
- Normalize to: city, state_region, country when identifiable

STANDARD FIELDS:
- Project: customer_name, project_name, job_number/project_code, project_type.
- Location: site_name, city, state_region, country, address_fragment.
- Water feature: family, type_keywords, style_keywords.
- Content: content_type, skill_level.
- Entities: list of ALL extracted entities (dates, names, locations, etc.) with sources and evidence.
- Keywords: 8-20 lowercase search tags.

OUTPUT JSON SCHEMA (return ONLY JSON, no markdown):
{{
  "summary": {{
    "text": "...",
    "depth": "{depth}",
    "language": "{language}"
  }},
  "chapters": {{
    "chapters": [
      {{
        "index": 1,
        "title": "...",
        "start_time": "00:00",
        "end_time": "03:00",
        "summary": "Brief 2-3 sentence overview...",
        "detailed_summary": "Comprehensive 4-8 sentence description with specific details, technical information, exact procedures, and visual demonstrations shown...",
        "key_points": ["Specific point 1", "Specific point 2", "Specific point 3"]
      }}
    ]
  }},
  "elements": {{
    "equipment": [
      {{
        "name": "...",
        "category": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "discussed": true,
        "confidence": "high"
      }}
    ],
    "topics_discussed": [
      {{
        "topic": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "importance": "high",
        "description": "...",
        "keywords": ["..."]
      }}
    ],
    "people": {{
      "max_count": 2,
      "multiple_speakers": true
    }},
    "speakers": [
      {{
        "speaker_id": "Speaker_1",
        "role": "...",
        "time_ranges": ["MM:SS-MM:SS"],
        "speaking_percentage": 65
      }}
    ]
  }},
  "waterfall_classification": {{
    "family": "...",
    "tier_level": "...",
    "functional_type": "...",
    "sub_type": "...",
    "confidence": {{
      "family": 0.0,
      "tier_level": 0.0,
      "functional_type": 0.0,
      "sub_type": 0.0,
      "overall": 0.0
    }},
    "evidence": ["..."],
    "unknown_reasons": {{}},
    "search_tags": ["..."],
    "product_keywords": ["..."],
    "content_type": "...",
    "skill_level": "...",
    "building_techniques": ["..."]
  }},
  "search_metadata": {{
    "recording_date": {{
      "date": "YYYY-MM-DD or null if unknown",
      "date_source": "path|filename|transcript|visual|unknown",
      "confidence": 0.0,
      "raw_date_string": "original text/pattern found (e.g., '20240315', 'March 15th')"
    }},
    "project": {{
      "customer_name": "extracted customer/client/project name or null (synonymous with project_name)",
      "project_name": "same as customer_name - use identical value",
      "name_source": "path|filename|transcript|unknown",
      "name_confidence": 0.0,
      "project_code": "any project/job code found or null",
      "job_number": "any job number found or null",
      "project_type": "..."
    }},
    "location": {{
      "site_name": "...",
      "city": "extracted city name or null",
      "state_region": "extracted state/region or null",
      "country": "USA if US state detected, else extracted or null",
      "address_fragment": "any partial address found",
      "location_source": "path|transcript|visual|unknown",
      "location_confidence": 0.0
    }},
    "water_feature": {{
      "family": "...",
      "type_keywords": ["..."],
      "style_keywords": ["..."]
    }},
    "content": {{
      "content_type": "...",
      "skill_level": "..."
    }},
    "entities": [
      {{
        "type": "...",
        "value": "...",
        "normalized": "...",
        "sources": ["filename", "path", "transcript_summary"],
        "evidence": "...",
        "confidence": 0.0
      }}
    ],
    "keywords": ["..."]
  }}
}}

Decision Tree:
{decision_tree}

Spec:
{spec_json}
"""
    return build_contextual_prompt(
        base_prompt,
        filename=filename,
        file_path=file_path,
        transcript_summary=transcript_summary,
        filename_tokens=filename_tokens,
        path_segments=path_segments,
        project_like_tokens=project_like_tokens,
        duration_seconds=duration_seconds
    )
