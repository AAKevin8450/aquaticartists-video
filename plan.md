# Nova Image Analysis Implementation Plan

## Overview

Implement Nova-powered image analysis using Amazon Bedrock's Nova models for static images. This feature will analyze proxy images (896px optimized for Nova 2 Lite) to extract content descriptions, visual elements, and metadata similar to video analysis but adapted for single-frame analysis.

## Current State

### Existing Video Analysis Features
- **Summary**: 2-4 paragraph content overview (250-350 words)
- **Chapters**: Timeline-based content segments (not applicable to images)
- **Elements**: Equipment, topics, people count, speakers
- **Waterfall Classification**: Product family/tier/type taxonomy
- **Metadata Extraction**: Recording date, customer/project, location

### Existing Image Infrastructure
- **Proxy System**: 896px shorter side, JPEG/PNG format (`proxy_image/` folder)
- **Naming**: `{name}_{source_file_id}_nova.{ext}`
- **Database**: `files` table with `is_proxy=1`, `source_file_id` FK
- **Rekognition**: Labels, faces, text, celebrities, moderation

---

## Proposed Analysis Types for Images

### 1. Image Description (replaces Video Summary)
**Purpose**: Comprehensive description of the image content
**Output**:
```json
{
  "description": "2-4 paragraph detailed description",
  "scene_type": "outdoor|indoor|studio|construction_site|etc",
  "primary_subject": "main focus of the image",
  "context": "what is happening in the image",
  "mood_atmosphere": "descriptive mood/lighting/atmosphere",
  "word_count": 250
}
```

### 2. Visual Elements (adapted from Video Elements)
**Purpose**: Identify objects, equipment, people, and text visible in the image
**Output**:
```json
{
  "equipment": [
    {
      "name": "item name",
      "category": "tools|machinery|vehicles|materials|safety|etc",
      "location_in_image": "foreground|background|left|right|center",
      "prominence": "primary|secondary|incidental",
      "confidence": "high|medium|low"
    }
  ],
  "objects": [
    {
      "name": "object name",
      "category": "structure|natural|manufactured|etc",
      "description": "brief description"
    }
  ],
  "people": {
    "count": 0,
    "descriptions": ["person descriptions if identifiable roles"]
  },
  "text_visible": [
    {
      "text": "readable text",
      "location": "where in image",
      "type": "sign|label|document|watermark|etc"
    }
  ],
  "materials": ["visible materials: concrete, steel, wood, etc"]
}
```

### 3. Waterfall Classification (same as video)
**Purpose**: Classify product family, tier, type for waterfall-related images
**Output**: Same structure as video waterfall classification
- family, functional_type, tier_level, sub_type
- confidence scores, evidence, search_tags

### 4. Metadata Extraction (adapted from video)
**Purpose**: Extract contextual metadata from EXIF, image content, and file path
**Output**:
```json
{
  "recording_date": {
    "date": "YYYY-MM-DD or null",
    "date_source": "exif|visual|path|filename|unknown",
    "confidence": 0.0,
    "raw_date_string": "original pattern found"
  },
  "project": {
    "customer_name": "extracted name or null",
    "project_name": "extracted project or null",
    "name_source": "path|filename|visual|unknown",
    "name_confidence": 0.0,
    "project_code": "code if found",
    "job_number": "number if found"
  },
  "location": {
    "site_name": "identifiable site",
    "city": "extracted city",
    "state_region": "state/region",
    "country": "country",
    "gps_coordinates": {"latitude": 0.0, "longitude": 0.0},
    "location_source": "exif|visual|path|unknown",
    "location_confidence": 0.0
  },
  "exif": {
    "capture_date": "YYYY-MM-DD or null",
    "gps": {"latitude": 0.0, "longitude": 0.0},
    "camera": "Make Model",
    "original_description": "embedded description if any"
  },
  "entities": [],
  "keywords": ["8-20 search tags"]
}
```

---

## Database Schema Changes

### Option A: Extend nova_jobs Table (Recommended)
Add support for image analysis in existing table:

```sql
-- Migration: Add image analysis support to nova_jobs
ALTER TABLE nova_jobs ADD COLUMN content_type VARCHAR(10) DEFAULT 'video';
-- Values: 'video' or 'image'

ALTER TABLE nova_jobs ADD COLUMN description_result TEXT;
-- JSON object for image description (replaces summary for images)

-- Existing columns reused:
-- elements_result: Visual elements (adapted structure)
-- waterfall_classification_result: Same as video
-- search_metadata: Same structure
```

### Option B: New nova_image_jobs Table
Create separate table for image-specific jobs:

```sql
CREATE TABLE nova_image_jobs (
    id INTEGER PRIMARY KEY,
    analysis_job_id INTEGER NOT NULL,
    model VARCHAR(20),
    analysis_types TEXT,  -- JSON array

    -- Results
    description_result TEXT,  -- JSON: description, scene_type, etc.
    elements_result TEXT,     -- JSON: equipment, objects, people, text
    waterfall_classification_result TEXT,
    search_metadata TEXT,
    raw_response TEXT,

    -- Performance
    tokens_input INTEGER,
    tokens_output INTEGER,
    tokens_total INTEGER,
    processing_time_seconds FLOAT,
    cost_usd FLOAT,

    -- Status
    status VARCHAR(20),
    error_message TEXT,
    progress_percent INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    FOREIGN KEY (analysis_job_id) REFERENCES analysis_jobs(id)
);
```

**Recommendation**: Option A - extend existing table for code reuse and unified querying.

---

## Implementation Steps

### Phase 1: Prompt Development

#### 1.1 Create Image Analysis Prompts
**File**: `app/services/nova/image_prompts.py` (new file)

**Functions to create**:
```python
def get_image_description_prompt(depth: str = 'standard') -> str:
    """Prompt for image description analysis"""

def get_image_elements_prompt() -> str:
    """Prompt for visual elements extraction"""

def get_image_waterfall_prompt() -> str:
    """Prompt for waterfall classification (reuse video version with minor tweaks)"""

def get_image_combined_prompt(analysis_types: List[str], context: dict) -> str:
    """Combined prompt for all requested analysis types"""
```

#### 1.2 Image Description Prompt Design
```text
Analyze this image and provide a comprehensive description.

OUTPUT STRUCTURE:
{
  "description": {
    "overview": "1-2 sentence high-level summary",
    "detailed": "2-4 paragraph detailed description covering:
      - Primary subject and focal point
      - Setting and environment
      - Activities or state captured
      - Notable details and context
      - Technical/professional observations if relevant"
  },
  "scene_type": "category of scene",
  "primary_subject": "main focus",
  "context": "situational context",
  "mood_atmosphere": "visual mood/lighting description",
  "technical_observations": "professional/technical notes if applicable"
}

GUIDELINES:
- Be specific and descriptive, not generic
- Note professional equipment, materials, or techniques visible
- Identify construction phases, product installations, or work in progress
- Describe quality, condition, and craftsmanship where visible
- Note environmental conditions (weather, lighting, time of day)
```

#### 1.3 Visual Elements Prompt Design
```text
Analyze this image and identify all visual elements.

OUTPUT STRUCTURE:
{
  "equipment": [
    {
      "name": "specific equipment name",
      "category": "tools|machinery|vehicles|materials|safety|electronics|etc",
      "location_in_image": "foreground|background|left|right|center",
      "prominence": "primary|secondary|incidental",
      "condition": "new|used|in-use|damaged|etc",
      "confidence": "high|medium|low"
    }
  ],
  "objects": [
    {
      "name": "object name",
      "category": "structure|natural|manufactured|furniture|etc",
      "material": "material if identifiable",
      "description": "brief description"
    }
  ],
  "structures": [
    {
      "type": "building|pool|waterfall|retaining_wall|etc",
      "description": "detailed description",
      "materials": ["visible materials"],
      "construction_phase": "planning|foundation|framing|finishing|complete|etc"
    }
  ],
  "people": {
    "count": 0,
    "descriptions": ["role-based descriptions: 'worker in safety vest', 'customer viewing installation'"],
    "activities": ["what people are doing"]
  },
  "text_visible": [
    {
      "text": "exact readable text",
      "location": "position in image",
      "type": "sign|label|document|logo|watermark|license_plate|etc",
      "relevance": "high|medium|low"
    }
  ],
  "materials": {
    "primary": ["main visible materials"],
    "secondary": ["supporting materials"],
    "finishes": ["surface treatments visible"]
  },
  "environment": {
    "setting": "indoor|outdoor|mixed",
    "location_type": "residential|commercial|industrial|natural|etc",
    "weather_conditions": "if outdoor and visible",
    "time_of_day": "if determinable from lighting"
  }
}

GUIDELINES:
- Be specific with equipment/product names when identifiable
- Note brand names, model numbers, or SKUs if visible
- Identify construction materials and techniques
- Describe the construction/installation phase if applicable
- Note safety equipment and PPE
```

#### 1.4 Image Metadata Extraction
```text
Extract metadata from the image content, file path, and EXIF data.

FILE CONTEXT:
- Filename: {filename}
- Path segments: {path_segments}
- File date: {file_date}

EXIF DATA (pre-extracted, use as authoritative when available):
- Capture date: {exif_capture_date}
- GPS coordinates: {exif_gps}
- Camera: {exif_camera}
- Original description: {exif_description}

EXTRACT:
1. RECORDING DATE (Priority order)
   1. EXIF capture_date (most reliable if present)
   2. Visual cues: timestamps, date displays, seasonal indicators
   3. Path patterns: YYYYMMDD, YYYY-MM-DD formats
   - Output: ISO YYYY-MM-DD format
   - Set date_source to "exif" if using EXIF data

2. LOCATION (Priority order)
   1. EXIF GPS coordinates (reverse geocode to city/state)
   2. Visible addresses, street signs, landmarks
   3. License plates (state identification)
   4. Architectural/environmental regional indicators
   5. Path segments containing city/state names
   - Set location_source to "exif" if using GPS data

3. CUSTOMER/PROJECT NAME
   - Path segments (often first folder = customer)
   - Visible signage, logos, or labels
   - Project identifiers in filename

4. KEYWORDS
   - 8-20 descriptive search terms
   - Include: subject, setting, materials, techniques, products
```

---

### Phase 2: Service Layer

#### 2.1 EXIF Metadata Extraction
**File**: `app/services/nova_image_service.py` (new file)

Extract EXIF data before Nova analysis to provide accurate metadata context:

```python
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

def extract_exif_metadata(self, image_path: str) -> dict:
    """Extract EXIF metadata from image file"""
    exif_data = {
        'capture_date': None,
        'gps_coordinates': None,
        'camera_make': None,
        'camera_model': None,
        'original_description': None
    }

    try:
        with Image.open(image_path) as img:
            exif = img._getexif()
            if not exif:
                return exif_data

            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)

                if tag == 'DateTimeOriginal':
                    # Format: "2024:03:15 14:30:00" → "2024-03-15"
                    exif_data['capture_date'] = self._parse_exif_date(value)
                elif tag == 'GPSInfo':
                    exif_data['gps_coordinates'] = self._parse_gps_info(value)
                elif tag == 'Make':
                    exif_data['camera_make'] = value.strip()
                elif tag == 'Model':
                    exif_data['camera_model'] = value.strip()
                elif tag == 'ImageDescription':
                    exif_data['original_description'] = value.strip()

    except Exception as e:
        logger.warning(f"Failed to extract EXIF from {image_path}: {e}")

    return exif_data

def _parse_exif_date(self, date_str: str) -> str:
    """Convert EXIF date format to ISO format"""
    # "2024:03:15 14:30:00" → "2024-03-15"
    try:
        date_part = date_str.split(' ')[0]
        return date_part.replace(':', '-')
    except:
        return None

def _parse_gps_info(self, gps_info: dict) -> dict:
    """Parse GPS EXIF data to coordinates"""
    try:
        def dms_to_decimal(dms, ref):
            degrees = float(dms[0])
            minutes = float(dms[1]) / 60
            seconds = float(dms[2]) / 3600
            decimal = degrees + minutes + seconds
            if ref in ['S', 'W']:
                decimal = -decimal
            return round(decimal, 6)

        lat = dms_to_decimal(gps_info[2], gps_info[1])
        lon = dms_to_decimal(gps_info[4], gps_info[3])

        return {'latitude': lat, 'longitude': lon}
    except:
        return None
```

**Usage in file context**:
```python
def build_file_context(self, file_record: dict, image_path: str) -> dict:
    """Build context dict for Nova prompt"""
    exif = self.extract_exif_metadata(image_path)

    return {
        'filename': file_record['filename'],
        'path_segments': file_record['s3_key'].split('/'),
        'file_date': file_record.get('created_at'),
        # EXIF enrichment
        'exif_capture_date': exif['capture_date'],
        'exif_gps': exif['gps_coordinates'],
        'exif_camera': f"{exif['camera_make']} {exif['camera_model']}".strip(),
        'exif_description': exif['original_description']
    }
```

#### 2.2 Create Image Analysis Service
**File**: `app/services/nova_image_service.py` (new file)

**Class structure**:
```python
class NovaImageService:
    """Service for analyzing images using Amazon Bedrock Nova models"""

    def __init__(self):
        self.client = boto3.client('bedrock-runtime', ...)
        self.timeout_config = Config(
            read_timeout=120,  # Shorter than video
            connect_timeout=30
        )

    def analyze_image(
        self,
        image_path: str,
        analysis_types: List[str],
        model: str = 'lite',
        file_context: dict = None
    ) -> dict:
        """
        Main entry point - single combined API call for all analysis types.

        Args:
            image_path: Path to proxy image file
            analysis_types: List of ['description', 'elements', 'waterfall', 'metadata']
            model: 'lite', 'pro', or 'premier'
            file_context: Dict with filename, path_segments, exif data

        Returns:
            Combined results dict with all requested analysis types
        """
        # Build combined prompt
        prompt = get_image_combined_prompt(analysis_types, file_context)

        # Single API call
        response = self._invoke_nova_image(image_path, prompt, model)

        # Parse and return all results
        return self._parse_combined_response(response, analysis_types)

    def _invoke_nova_image(
        self,
        image_path: str,
        prompt: str,
        model: str
    ) -> dict:
        """Core Bedrock API invocation for image"""

    def _prepare_image_content(self, image_path: str) -> dict:
        """Prepare image for Bedrock Converse API (base64 encoding)"""

    def _parse_combined_response(self, response: dict, analysis_types: List[str]) -> dict:
        """Parse combined JSON response into typed results"""
```

#### 2.2 Image Content Preparation
```python
def _prepare_image_content(self, image_path: str) -> dict:
    """Prepare image for Bedrock Converse API"""
    with open(image_path, 'rb') as f:
        image_bytes = f.read()

    # Determine media type
    ext = Path(image_path).suffix.lower()
    media_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp'
    }
    media_type = media_types.get(ext, 'image/jpeg')

    return {
        "image": {
            "format": ext.lstrip('.'),
            "source": {
                "bytes": image_bytes
            }
        }
    }
```

#### 2.3 Bedrock Converse API Call for Images
```python
def _invoke_nova_image(self, image_path: str, prompt: str, model: str) -> dict:
    """Invoke Nova model with image content"""
    model_id = MODEL_IDS[model]  # e.g., 'amazon.nova-lite-v1:0'

    image_content = self._prepare_image_content(image_path)

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

    return {
        'text': output_text,
        'tokens_input': usage['inputTokens'],
        'tokens_output': usage['outputTokens'],
        'tokens_total': usage['inputTokens'] + usage['outputTokens'],
        'cost': self._calculate_cost(model, usage),
        'raw_response': response
    }
```

---

### Phase 3: Database Layer

#### 3.1 Migration Script
**File**: `migrations/XXX_add_image_analysis_support.sql`

```sql
-- Add content_type to distinguish video vs image analysis
ALTER TABLE nova_jobs ADD COLUMN content_type VARCHAR(10) DEFAULT 'video';

-- Add description_result for image descriptions
ALTER TABLE nova_jobs ADD COLUMN description_result TEXT;

-- Create index for content_type queries
CREATE INDEX idx_nova_jobs_content_type ON nova_jobs(content_type);

-- Update existing records to have content_type='video'
UPDATE nova_jobs SET content_type = 'video' WHERE content_type IS NULL;
```

#### 3.2 Database Mixin Updates
**File**: `app/database/nova_jobs.py` (update existing)

Add methods:
```python
def create_nova_image_job(self, analysis_job_id: int, model: str,
                           analysis_types: list) -> int:
    """Create a nova job record for image analysis"""

def update_nova_image_results(self, job_id: int, results: dict):
    """Update image analysis results"""

def get_image_analysis_results(self, file_id: int) -> dict:
    """Get all Nova image analysis results for a file"""
```

---

### Phase 4: API Routes

#### 4.1 New Route File
**File**: `app/routes/nova_image_analysis.py` (new file)

```python
from flask import Blueprint, request, jsonify

nova_image_bp = Blueprint('nova_image', __name__)

@nova_image_bp.route('/api/nova/image/analyze', methods=['POST'])
def start_image_analysis():
    """
    Start Nova image analysis

    Request:
    {
        "file_id": 123,
        "model": "lite",  # lite, pro, premier
        "analysis_types": ["description", "elements", "waterfall", "metadata"]
    }

    Response:
    {
        "nova_job_id": 456,
        "status": "SUBMITTED",
        "estimated_cost": 0.001
    }
    """

@nova_image_bp.route('/api/nova/image/status/<int:job_id>', methods=['GET'])
def get_image_analysis_status(job_id: int):
    """Get status of image analysis job"""

@nova_image_bp.route('/api/nova/image/results/<int:job_id>', methods=['GET'])
def get_image_analysis_results(job_id: int):
    """Get results of completed image analysis"""

@nova_image_bp.route('/api/nova/image/models', methods=['GET'])
def get_image_models():
    """Get available models and pricing for image analysis"""

@nova_image_bp.route('/api/nova/image/estimate-cost', methods=['POST'])
def estimate_image_cost():
    """Estimate cost for image analysis"""
```

#### 4.2 Register Blueprint
**File**: `app/__init__.py` (update)

```python
from app.routes.nova_image_analysis import nova_image_bp
app.register_blueprint(nova_image_bp)
```

---

### Phase 5: Batch Processing

#### 5.1 Add Image Analysis to Batch Operations
**File**: `app/routes/file_management/batch.py` (update)

Add new action type `nova-image`:
```python
@batch_bp.route('/api/batch/nova-image', methods=['POST'])
def batch_nova_image():
    """
    Batch Nova image analysis

    Request:
    {
        "file_ids": [1, 2, 3],
        "model": "lite",
        "analysis_types": ["description", "elements", "metadata"]
    }
    """
```

#### 5.2 Update file_management.js
Add UI controls for batch Nova image analysis:
- Model selector (Lite/Pro/Premier)
- Analysis type checkboxes
- Progress tracking similar to video batch

---

### Phase 6: Frontend Integration

#### 6.1 Update Image Details View
**File**: `app/templates/file_management.html` (update)

Add Nova Image Analysis section to image detail panel:
```html
<div class="nova-image-analysis-section" data-file-type="image">
    <h4>Nova Image Analysis</h4>

    <!-- Analysis Controls -->
    <div class="analysis-controls">
        <select id="image-nova-model">
            <option value="lite">Nova Lite ($0.00006/image)</option>
            <option value="pro">Nova Pro ($0.0008/image)</option>
            <option value="premier">Nova Premier ($0.008/image)</option>
        </select>

        <div class="analysis-types">
            <label><input type="checkbox" value="description" checked> Description</label>
            <label><input type="checkbox" value="elements" checked> Visual Elements</label>
            <label><input type="checkbox" value="waterfall"> Waterfall Classification</label>
            <label><input type="checkbox" value="metadata" checked> Metadata Extraction</label>
        </div>

        <button id="start-image-analysis">Analyze Image</button>
    </div>

    <!-- Results Display -->
    <div class="analysis-results">
        <div class="description-result"></div>
        <div class="elements-result"></div>
        <div class="waterfall-result"></div>
        <div class="metadata-result"></div>
    </div>
</div>
```

#### 6.2 Add JavaScript Handlers
**File**: `app/static/js/file_management.js` (update)

```javascript
async function startImageNovaAnalysis(fileId) {
    const model = document.getElementById('image-nova-model').value;
    const analysisTypes = getSelectedImageAnalysisTypes();

    const response = await fetch('/api/nova/image/analyze', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            file_id: fileId,
            model: model,
            analysis_types: analysisTypes
        })
    });

    const data = await response.json();
    pollImageAnalysisStatus(data.nova_job_id);
}

function pollImageAnalysisStatus(jobId) {
    // Similar to video polling logic
}

function displayImageAnalysisResults(results) {
    // Render description, elements, waterfall, metadata
}
```

---

### Phase 7: Search Integration

#### 7.1 Generate Embeddings for Image Analysis
**File**: `app/services/nova_embeddings_service.py` (update)

Add method to generate embeddings from image analysis text:
```python
def generate_image_analysis_embedding(self, nova_job_id: int) -> int:
    """Generate embedding from image analysis results"""
    # Combine description + elements + metadata into searchable text
    # Generate embedding via Nova Embeddings API
    # Store in nova_embeddings table
```

#### 7.2 Update Search to Include Image Results
**File**: `app/routes/search.py` (update)

Ensure search queries include image analysis results in:
- Keyword search: description, elements, metadata keywords
- Semantic search: image analysis embeddings

---

## File Structure Summary

### New Files
```
app/services/
├── nova_image_service.py          # Image analysis service
└── nova/
    └── image_prompts.py           # Image-specific prompts

app/routes/
└── nova_image_analysis.py         # API endpoints

migrations/
└── XXX_add_image_analysis_support.sql
```

### Modified Files
```
app/__init__.py                    # Register new blueprint
app/database/nova_jobs.py          # Add image analysis methods
app/routes/file_management/batch.py # Add nova-image batch action
app/templates/file_management.html  # Add image analysis UI
app/static/js/file_management.js   # Add image analysis JS
app/routes/search.py               # Include image results
app/services/nova_embeddings_service.py # Image embedding generation
```

---

## Cost Estimation

### Per-Image Costs (Approximate)
| Model | Input Tokens | Output Tokens | Cost/Image |
|-------|--------------|---------------|------------|
| Lite | ~1,500 | ~1,000 | ~$0.00006 |
| Pro | ~1,500 | ~1,000 | ~$0.0008 |
| Premier | ~1,500 | ~1,000 | ~$0.008 |

### Batch Analysis (100 images)
| Model | Total Cost |
|-------|------------|
| Lite | ~$0.006 |
| Pro | ~$0.08 |
| Premier | ~$0.80 |

---

## Testing Plan

### Unit Tests
1. Prompt generation for each analysis type
2. Image content preparation (base64, media types)
3. Response parsing for each result type
4. Database operations (create, update, query)

### Integration Tests
1. End-to-end image analysis flow
2. Batch processing with multiple images
3. Error handling (invalid images, API failures)
4. Cost tracking accuracy

### Manual Testing
1. Various image types (JPEG, PNG)
2. Different content (construction sites, products, documentation)
3. Edge cases (very small/large images, transparent PNGs)
4. UI/UX for single and batch operations

---

## Key Differences from Video Analysis

| Aspect | Video | Image |
|--------|-------|-------|
| Chapters | Yes (timeline-based) | No (single frame) |
| Transcript | Yes (audio) | No |
| Duration-based chunking | Yes | No |
| Temporal context | Full video flow | Single moment |
| Description depth | Summary of content | Detailed visual description |
| Elements | Time-ranged appearances | Single-frame presence |
| Processing time | 30-120s | 5-15s |
| Token usage | Higher (video tokens) | Lower (image tokens) |

---

## Implementation Priority

### P0 - Core Functionality
1. Image prompts (description, elements, metadata)
2. NovaImageService with basic analysis
3. Database migration
4. API endpoints (analyze, status, results)

### P1 - Integration
5. Frontend UI for single image analysis
6. Batch processing support
7. Search integration (keyword + semantic)

### P2 - Enhancement
8. Waterfall classification for images
9. Cost reporting integration
10. Performance optimization

---

## Design Decisions

### 1. Nova Replaces Rekognition for Images
Nova image analysis will **replace** Rekognition for image analysis, not complement it. Rationale:
- Nova provides richer contextual understanding vs Rekognition's structured labels
- Single API reduces complexity and cost tracking overhead
- Nova can identify the same objects/text/people that Rekognition detects, plus interpret context
- Eliminates need to maintain two parallel analysis pipelines for images

**Migration Note**: Existing Rekognition image results remain in database but new analyses use Nova only.

### 2. EXIF Metadata Extraction
Extract EXIF data from images **before** sending to Nova to enrich metadata:
- **DateTimeOriginal**: Photo capture date (most reliable date source)
- **GPSInfo**: Latitude/longitude for location extraction
- **Make/Model**: Camera information
- **ImageDescription**: Existing metadata if present

**Implementation**: Use Pillow's `ExifTags` module to extract before Nova analysis, include in file context sent to prompt.

### 3. Combined API Call

Use a **single combined API call** for all analysis types. One prompt requests all analyses, one response contains all results.

**Request Flow**:
```
Single prompt with all analysis types → Single response with all results
```

**Benefits**:
- **Cost efficient**: Image tokens counted once (not 3x for separate calls)
- **Faster**: Single round-trip vs multiple sequential calls
- **Context sharing**: Model sees full context for all tasks simultaneously
- **Simpler code**: One API call, one response to parse

**Implementation**:
```python
def analyze_image(self, image_path, analysis_types, file_context):
    prompt = get_image_combined_prompt(analysis_types, file_context)
    response = self._invoke_nova_image(image_path, prompt, model)
    return self._parse_combined_response(response, analysis_types)
```

**Error Handling**:
- If JSON parsing fails, use existing `parsers.py` repair logic (trailing commas, truncation fixes)
- Log partial failures but return what was successfully parsed
- Store raw_response for debugging

### 4. Always Use Proxy Images
Always use proxy images (896px) for Nova analysis:
- Consistent with Nova 2 Lite's internal rescaling threshold
- Reduces API payload size and cost
- Standardized input for reproducible results
