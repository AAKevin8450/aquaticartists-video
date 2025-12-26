# Nova Analysis Enhancement Plan (Searchable Metadata)

## Objective

Enhance Nova combined analysis to leverage filename, file path, and transcript summary as contextual input and return structured, searchable metadata. The goal is reliable discovery by waterfall type (strictly following the established Decision Tree), customer/project, location, and job-specific details that usually live in file naming and transcript text.

---

## Current State

### What Nova Receives Today
- **Video content only**: S3 URI pointing to the video file
- **Generic prompts**: Uses `_load_waterfall_assets()` to inject the Decision Tree, but lacks file-specific context
- **No transcript context**: Existing transcript summaries are not utilized
- **Weak search hooks**: Results are mostly freeform text with limited structured metadata for project/location lookup

### Current Prompt Structure (Combined Analysis)
The current `_get_combined_prompt` injects the `Nova_Waterfall_Classification_Decision_Tree.md` and `Spec`.
It asks for:
1. Summary
2. Chapters
3. Elements
4. Waterfall classification (strictly following the decision tree)

### Available But Unused Context
| Data | Source | Current Status |
|------|--------|----------------|
| Filename | `files.filename` | Not passed to Nova |
| File Path | `files.local_path` | Not passed to Nova |
| Filename tokens | derived from `files.filename` | Not parsed/normalized |
| Path segments | derived from `files.local_path` | Not parsed/normalized |
| Transcript Summary | `transcripts.transcript_summary` | Generated separately, not used |
| Video Duration | `files.duration_seconds` | Only used for cost estimation |

---

## Proposed Changes

### Phase 1: Data Collection Layer

#### Step 1.1: Create Context Gathering Function

**Location**: `app/services/nova_service.py`

Create a new function to gather all available context for a file:

```python
def gather_analysis_context(file_id: int, db) -> dict:
    """
    Gather filename, path, and transcript summary for contextual analysis.

    Returns:
        {
            'filename': str,
            'file_path': str,
            'transcript_summary': str | None,
            'duration_seconds': float | None
        }
    """
```

**Implementation Details**:
1. Query `files` table by `file_id` to get `filename`, `local_path`, `duration_seconds`
2. Query `transcripts` table by matching `file_path` to `files.local_path`
3. Extract `transcript_summary` if available
4. Return structured dict with all context

#### Step 1.2: Update Database Query

**Location**: `app/database.py`

Add a new query method:

```python
def get_file_with_transcript_summary(file_id: int) -> dict:
    """
    Get file record with associated transcript summary via LEFT JOIN.
    """
```

**SQL**:
```sql
SELECT
    f.id, f.filename, f.local_path, f.duration_seconds,
    t.transcript_summary
FROM files f
LEFT JOIN transcripts t ON f.local_path = t.file_path
WHERE f.id = ?
```

#### Step 1.3: Normalize Filename + Path Tokens

**Location**: `app/services/nova_service.py`

Add a helper that parses filenames and paths into clean, searchable tokens:

```python
def normalize_file_context(filename: str | None, file_path: str | None) -> dict:
    """
    Return normalized tokens and path segments for prompting/search.
    """
```

**Expected Output**:
```json
{
  "filename_tokens": ["niagara", "xl", "pro", "install", "part", "2"],
  "path_segments": ["videos", "training", "products", "niagara_xl"],
  "project_like_tokens": ["smith_residence", "job_2024_0812"],
  "raw_filename": "Niagara XL Pro Installation Tutorial Part 2.mp4",
  "raw_path": "E:\\Videos\\Training\\Products\\Niagara_XL\\"
}
```

**Normalization Rules**:
- Split on separators (`_`, `-`, `.`, space, `\`, `/`), camel case, and digits
- Lowercase everything; keep raw values alongside normalized tokens
- Keep likely project/customer identifiers (e.g., `job_2024_0812`, `smith_residence`)
- Drop common noise terms (`final`, `v2`, `export`, `edited`, `copy`) from the token lists

---

### Phase 2: Prompt Enhancement

#### Step 2.1: Create Context-Aware Prompt Wrapper

**Location**: `app/services/nova_service.py`

Create a function to inject context into prompts:

```python
def _build_contextual_prompt(
    base_prompt: str,
    filename: str = None,
    file_path: str = None,
    transcript_summary: str = None,
    filename_tokens: list[str] | None = None,
    path_segments: list[str] | None = None,
    project_like_tokens: list[str] | None = None,
    duration_seconds: float | None = None
) -> str:
    """
    Wrap base prompt with contextual metadata section.
    """
```

**Context Section Format**:
```
=== FILE CONTEXT ===
Filename: {filename}
File Path: {file_path}
Filename Tokens: {filename_tokens}
Path Segments: {path_segments}
Project/Customer Tokens: {project_like_tokens}
Duration: {duration} seconds

=== TRANSCRIPT SUMMARY ===
{transcript_summary}

=== ANALYSIS INSTRUCTIONS ===
Use the above context to guide your analysis:
- The filename often contains important keywords about the content
- The file path may indicate project/category organization
- The transcript summary provides spoken content context
- Path segments can encode customer/project/location; treat as hints with source attribution
- Extract customer, project, and location cues when present
- Do not invent details; use "unknown" when evidence is missing

{base_prompt}
```

#### Step 2.2: Update Combined Analysis Prompt

**Location**: `app/services/nova_service.py` - `_get_combined_prompt()`

**Crucial**: Ensure we **retain** the injection of `decision_tree` and `spec` from `_load_waterfall_assets()`. The new context is additive.

**New Behavior**:
1. Accept optional context parameters
2. Prepend context section to existing prompt
3. Add guidance for using context in each analysis type
4. Require `search_metadata` output for project/location discovery
5. Maintain strict adherence to the Waterfall Classification Decision Tree

**Enhanced Prompt Structure**:
```
=== FILE CONTEXT ===
Filename: Niagara XL Pro Installation Tutorial Part 2.mp4
File Path: E:\\Videos\\Training\\Products\\Niagara_XL\\
Duration: 847 seconds

=== TRANSCRIPT SUMMARY ===
This video demonstrates the installation process for the Niagara XL Pro
waterfall system. The presenter covers mounting bracket placement, water
line connections, and LED lighting integration. Key topics include proper
leveling techniques and troubleshooting common installation issues.

=== ANALYSIS INSTRUCTIONS ===
Use the context above to enhance your analysis. The filename and path
suggest this is product training content for the Niagara XL product line.
The transcript summary indicates installation/how-to content.

Analyze this video and provide a comprehensive analysis in JSON format:

1. SUMMARY
   - Incorporate insights from the transcript summary
   - Note product names from filename if applicable

2. CHAPTERS
   - Identify logical sections matching the tutorial structure

3. ELEMENTS
   - Equipment: Identify products shown (cross-reference with filename)
   - Topics: Tag with searchable terms from transcript

4. WATERFALL CLASSIFICATION
   - STRICTLY follow the Decision Tree and Spec provided below.
   - Use filename hints to assist with "Kit vs Custom" or "Boulder vs No Boulder" differentiation if visual evidence is ambiguous, but prioritize visual evidence.
   - Populate the new "search_tags" and "product_keywords" fields based on file/transcript context.

5. SEARCH METADATA (for discovery)
   - Project: customer_name, project_name, job_number/project_code if present
   - Location: site_name, city, state/region, country (avoid guessing)
   - Water feature type keywords (spillway, sheer, cascade, etc.)
   - Content type and skill level (training, install, troubleshooting, etc.)
   - Provide evidence strings and sources for each item when possible

{existing JSON format specification with Decision Tree appended}
```

---

### Phase 3: Search Metadata Output (Project/Location/Waterfall Findability)

#### Step 3.1: Add `search_metadata` to Combined Output

**Goal**: Produce consistent fields for discovery that can be indexed or embedded.

**Schema (additive)**:
```json
{
  "search_metadata": {
    "project": {
      "customer_name": "string | unknown",
      "project_name": "string | unknown",
      "project_code": "string | unknown",
      "job_number": "string | unknown",
      "project_type": "residential | commercial | municipal | unknown"
    },
    "location": {
      "site_name": "string | unknown",
      "city": "string | unknown",
      "state_region": "string | unknown",
      "country": "string | unknown",
      "address_fragment": "string | unknown"
    },
    "water_feature": {
      "family": "string | unknown",
      "type_keywords": ["string"],
      "style_keywords": ["string"]
    },
    "content": {
      "content_type": "product_overview | installation_tutorial | building_demonstration | troubleshooting | comparison | review | unknown",
      "skill_level": "beginner | intermediate | advanced | professional | unknown"
    },
    "entities": [
      {
        "type": "project | customer | location | product | model | technique",
        "value": "string",
        "normalized": "string",
        "sources": ["filename", "path", "transcript_summary"],
        "evidence": "short quote/snippet",
        "confidence": 0.0
      }
    ],
    "keywords": ["lowercase", "search", "tags"]
  }
}
```

**Extraction Rules**:
- Use filename/path tokens to seed projects and product names, but mark confidence low unless transcript evidence exists.
- Prefer transcript summary for people, place names, and project details.
- If a field is not supported by evidence, set to `"unknown"` and omit from `entities`.
- Keep `keywords` 8-20 terms, lowercase, deduped, covering product, project, location, and techniques.
- Only surface location fields when explicitly present in filename/path/transcript; avoid guessing cities or states.

#### Step 3.2: Prompt Addendum for Metadata

Add a requirement to always return `search_metadata` with evidence and sources:

```
Return a "search_metadata" object with project, location, and water-feature fields.
Each extracted entity must include its sources (filename/path/transcript_summary)
and a short evidence snippet. Use "unknown" when you cannot support a value.
```

---

### Phase 4: Waterfall Classification Enhancement

#### Step 4.1: Improve Waterfall Search Relevance

**Current Issue**: Waterfall classification returns structured data (Family, Type, Tier, Sub-Type) but lacks searchable text fields for specific product names or building techniques.

**Enhancement**: Add new fields to waterfall classification output.
**IMPORTANT**: The core 4 dimensions (Family, Tier, Functional Type, Sub-Type) MUST strictly follow the `Nova_Waterfall_Classification_Decision_Tree.md`.

Example of correct output structure:

```json
{
  "waterfall_classification": {
    "family": "Genesis Formal",  // Must be one of the 4 defined Families
    "functional_type": "Waterfall", // Must be one of the 4 defined Types
    "tier_level": "Deluxe (Medium)", // Must be one of the 3 defined Tiers
    "sub_type": "One-Tier", // Must be one of the 5 defined Sub-Types
    "confidence": { ... },
    
    // NEW FIELDS FOR SEARCH (Additive)
    "search_tags": ["genesis formal", "deluxe", "kit", "rectilinear", "installation"],
    "product_keywords": ["Niagara XL Pro", "NXL-PRO-48", "LED-enabled"],
    "content_type": "installation_tutorial",
    "skill_level": "intermediate",
    "building_techniques": ["bracket mounting", "water line connection", "leveling"]
  }
}
```

#### Step 4.2: Update Waterfall Classification Prompt

**Location**: `app/services/nova_service.py` - `_get_waterfall_classification_prompt()`

**Add to existing prompt (which already contains the Decision Tree)**:
```
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
```

---

### Phase 5: Route Layer Updates

#### Step 5.1: Modify start_nova_analysis_internal()

**Location**: `app/routes/nova_analysis.py`

**Current Flow**:
1. Validate request
2. Get file from DB
3. Create job records
4. Call `nova_service.analyze_video()`

**New Flow**:
1. Validate request
2. Get file from DB **with transcript summary** (use new JOIN query)
3. Create job records
4. **Build context dict with filename, path, transcript_summary**
5. Call `nova_service.analyze_video()` **with context parameter**

**Code Changes**:
```python
# After file validation
file_with_context = db.get_file_with_transcript_summary(file_id)
file_tokens = nova_service.normalize_file_context(
    file_with_context.get('filename'),
    file_with_context.get('local_path')
)
analysis_context = {
    **file_tokens,
    'filename': file_with_context.get('filename'),
    'file_path': file_with_context.get('local_path'),
    'transcript_summary': file_with_context.get('transcript_summary'),
    'duration_seconds': file_with_context.get('duration_seconds')
}

# Pass to analyze_video
result = nova_service.analyze_video(
    s3_key=s3_key,
    analysis_types=analysis_types,
    model=model,
    options=options,
    context=analysis_context,  # NEW PARAMETER
    progress_callback=progress_callback
)
```

#### Step 5.2: Update analyze_video() Method

**Location**: `app/services/nova_service.py` - `analyze_video()` method

**Add parameter**: `context: dict = None`

**Modify prompt building**:
```python
def analyze_video(self, s3_key, analysis_types, model, options,
                  context=None, progress_callback=None):
    # ...existing code...

    if 'combined' in analysis_types or len(analysis_types) > 1:
        prompt = self._get_combined_prompt(
            depth=options.get('summary_depth', 'standard'),
            language=options.get('language', 'auto'),
            context=context  # NEW: Pass context to prompt builder
        )
```

---

### Phase 6: Testing & Validation

#### Step 6.1: Unit Tests

Create test cases in `tests/test_nova_context.py`:

1. **test_context_gathering_with_transcript**
   - File exists with transcript summary
   - Verify all fields populated correctly

2. **test_context_gathering_without_transcript**
   - File exists without transcript
   - Verify graceful handling (None for transcript_summary)

3. **test_prompt_building_with_full_context**
   - All context fields present
   - Verify prompt contains all sections AND the decision tree

4. **test_prompt_building_with_partial_context**
   - Only filename available
   - Verify prompt handles missing fields

5. **test_waterfall_classification_search_fields**
   - Verify new search fields in output
   - Validate field format and types
   - **Crucial**: Verify strict adherence to Family/Type/Tier/Sub-Type enums

6. **test_search_metadata_extraction**
   - Verify project/location/customer fields populate from filename/path/transcript

7. **test_normalize_file_context**
   - Filename/path tokenization drops noise and preserves identifiers

#### Step 6.2: Integration Test

Create `tests/test_nova_integration.py`:

1. End-to-end test with sample video
2. Verify context flows from route -> service -> prompt
3. Validate response includes enhanced waterfall fields and strict classification
4. Confirm search_tags are lowercase and relevant
5. Validate search_metadata fields are populated when evidence exists

---

### Phase 7: Search Enhancement

#### Step 7.1: Update Search Indexing

**Location**: `app/routes/search.py`

**Current**: Searches nova_jobs results as JSON text

**Enhancement**: Extract and index `search_metadata` plus waterfall search fields:

```python
def index_nova_results_for_search(nova_job):
    """Extract searchable content from Nova results."""
    combined = json.loads(nova_job.get('combined_result', '{}'))
    metadata = combined.get('search_metadata', {})
    waterfall = combined.get('waterfall_classification', {})

    searchable_text = []
    # Core classification terms
    searchable_text.append(waterfall.get('family', ''))
    searchable_text.append(waterfall.get('functional_type', ''))
    searchable_text.append(waterfall.get('tier_level', ''))
    searchable_text.append(waterfall.get('sub_type', ''))
    
    # New search tags
    searchable_text.extend(metadata.get('keywords', []))
    searchable_text.extend(waterfall.get('search_tags', []))
    searchable_text.extend(waterfall.get('product_keywords', []))
    
    # Metadata
    searchable_text.append(metadata.get('project', {}).get('customer_name', ''))
    searchable_text.append(metadata.get('project', {}).get('project_name', ''))
    searchable_text.append(metadata.get('project', {}).get('project_code', ''))
    searchable_text.append(metadata.get('location', {}).get('city', ''))
    searchable_text.append(metadata.get('location', {}).get('state_region', ''))
    searchable_text.append(metadata.get('location', {}).get('country', ''))
    searchable_text.append(metadata.get('content', {}).get('content_type', ''))
    searchable_text.extend(waterfall.get('building_techniques', []))
    searchable_text.extend([e.get('normalized', '') for e in metadata.get('entities', [])])

    return ' '.join(filter(None, searchable_text))
```

#### Step 7.2: Add Semantic Search for Waterfall + Project/Location Content

Leverage existing `nova_embeddings_service.py` to create embeddings from:
- `search_metadata.keywords`
- Project/customer names and codes
- Location fields
- Waterfall search_tags and product keywords
- Building techniques

---

## Implementation Order

| Order | Phase | Component | Estimated Complexity |
|-------|-------|-----------|---------------------|
| 1 | Phase 1.2 | Database query update | Low |
| 2 | Phase 1.1 | Context gathering function | Low |
| 3 | Phase 1.3 | Normalize filename/path tokens | Low |
| 4 | Phase 2.1 | Context-aware prompt wrapper | Medium |
| 5 | Phase 2.2 | Combined prompt update | Medium |
| 6 | Phase 3.1 | Add search_metadata output | Medium |
| 7 | Phase 3.2 | Prompt addendum for metadata | Low |
| 8 | Phase 4.1 | Waterfall search relevance (add fields) | Medium |
| 9 | Phase 4.2 | Waterfall classification prompt (keep decision tree) | Medium |
| 10 | Phase 5.1 | Route layer updates | Low |
| 11 | Phase 5.2 | Service method updates | Low |
| 12 | Phase 6.1 | Unit tests | Medium |
| 13 | Phase 6.2 | Integration tests | Medium |
| 14 | Phase 7.1 | Search indexing | Medium |
| 15 | Phase 7.2 | Semantic search enhancement | High |

---

## Files to Modify

| File | Changes |
|------|---------|
| `app/database.py` | Add `get_file_with_transcript_summary()` method |
| `app/services/nova_service.py` | Add context gathering, update prompts (retain decision tree), add context parameter |
| `app/routes/nova_analysis.py` | Fetch context, pass to service |
| `app/routes/search.py` | Index new waterfall search fields and metadata |
| `tests/test_nova_context.py` | New file - unit tests |
| `tests/test_nova_integration.py` | New file - integration tests |

---

## Appendix: Sample Enhanced Prompt

```
=== FILE CONTEXT ===
Filename: Atlantic Pro Series Installation Guide - Water Feature Basics.mp4
File Path: E:\\Videos\\Training\\Atlantic\\Professional_Series\\
Filename Tokens: atlantic, pro, series, installation, guide, water, feature, basics
Path Segments: videos, training, atlantic, professional_series
Project/Customer Tokens: atlantic, pro_series
Duration: 1247 seconds

=== TRANSCRIPT SUMMARY ===
This comprehensive guide covers the installation of Atlantic Pro Series
water features. The instructor demonstrates proper basin preparation,
pump selection based on head height calculations, and plumbing best
practices. Key emphasis on achieving optimal water flow rates and
avoiding common mistakes that lead to warranty issues.

=== ANALYSIS INSTRUCTIONS ===
Context Analysis:
- Filename indicates: Atlantic Pro Series product, installation content
- Path suggests: Professional training material, Atlantic brand focus
- Transcript reveals: Basin prep, pump selection, plumbing, flow rates

Use this context to:
1. Prioritize Atlantic Pro Series in product identification
2. Tag as installation/tutorial content
3. Extract specific building techniques mentioned
4. Note skill level based on content complexity
5. ASSIST with Waterfall Classification by inferring "Custom Formal" or "Genesis Formal" if "Atlantic Pro" implies a specific kit vs custom style, BUT always prioritize visual evidence for the final classification.

Analyze this video and return comprehensive JSON with:
Include all existing fields plus a top-level "search_metadata" object.

{
  "summary": { ... },
  "chapters": [ ... ],
  "elements": { ... },
  "waterfall_classification": {
    "family": "Custom Formal",  // Matches strict Decision Tree
    "functional_type": "Waterfall", // Matches strict Decision Tree
    "tier_level": "Deluxe (Medium)", // Matches strict Decision Tree
    "sub_type": "One-Tier", // Matches strict Decision Tree
    "confidence": 0.85,
    "search_tags": ["atlantic pro", "installation", "spillway", "formal"],
    "product_keywords": ["Atlantic Pro Series", "Basin Kit"],
    "content_type": "installation_tutorial",
    "skill_level": "professional",
    "building_techniques": ["basin preparation", "pump selection"]
  },
  "search_metadata": {
    "project": {
      "customer_name": "Atlantic",
      "project_name": "unknown",
      "project_code": "unknown",
      "job_number": "unknown",
      "project_type": "commercial"
    },
    "location": {
      "site_name": "unknown",
      "city": "unknown",
      "state_region": "unknown",
      "country": "unknown",
      "address_fragment": "unknown"
    },
    "water_feature": {
      "family": "Atlantic Pro Series",
      "type_keywords": ["water feature", "spillway"],
      "style_keywords": ["professional series"]
    },
    "content": {
      "content_type": "installation_tutorial",
      "skill_level": "intermediate"
    },
    "entities": [
      {
        "type": "product",
        "value": "Atlantic Pro Series",
        "normalized": "atlantic pro series",
        "sources": ["filename", "path", "transcript_summary"],
        "evidence": "Atlantic Pro Series",
        "confidence": 0.82
      }
    ],
    "keywords": ["atlantic", "pro", "series", "installation", "basin", "pump", "plumbing"]
  }
}
```

Note: Keep waterfall fields focused on waterfall/product info. Project/location/customer fields belong in `search_metadata`.

```