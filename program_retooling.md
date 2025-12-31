# AWS Video & Image Analysis Application - Codebase Reorganization Plan

## Executive Summary

This document provides a comprehensive analysis of the AWS Video & Image Analysis Flask application codebase and proposes a structured reorganization plan to improve maintainability, reduce code duplication, and establish clearer separation of concerns.

### Key Findings
- **7 files exceed 300 lines** and are candidates for splitting
- **4 significant code duplications** identified across frontend JavaScript files
- **Heavy import dependencies** in file_management.py route (30+ inline imports)
- **Database.py monolith** at ~3,500 lines handling multiple domains

### Recommended Actions
1. Split `database.py` into domain-specific modules
2. Split `file_management.py` route into focused handlers
3. Split `nova_service.py` into analysis and prompt modules
4. Consolidate JavaScript utility functions
5. Centralize JSON parsing utilities

---

## Current State Analysis

### File Size Metrics

#### Python Files (Sorted by Line Count)

| File | Lines | Functions | Status | Reason for Flag |
|------|-------|-----------|--------|-----------------|
| `app/database.py` | ~3,500 | 80+ | **CRITICAL** | Monolithic - handles files, transcripts, jobs, embeddings, billing cache, rescan/import jobs |
| `app/routes/file_management.py` | ~2,800 | 40+ | **CRITICAL** | Too many responsibilities - file CRUD, batch operations, rescan, import, S3 management |
| `app/services/nova_service.py` | ~2,500 | 35+ | **HIGH** | Mixed concerns - prompts, analysis, validation, aggregation |
| `app/routes/search.py` | ~720 | 15 | MODERATE | Multiple search modes mixed |
| `app/routes/transcription.py` | ~900 | 20 | MODERATE | Could separate API from business logic |
| `app/services/billing_service.py` | ~620 | 15 | OK | Single responsibility |
| `app/services/rekognition_video.py` | ~450 | 20 | OK | Focused on Rekognition |
| `app/routes/upload.py` | ~530 | 12 | OK | File upload handling |
| `app/routes/reports.py` | ~350 | 8 | OK | Report generation |
| `app/routes/nova_analysis.py` | ~320 | 8 | OK | Nova API endpoints |

#### JavaScript Files (Sorted by Line Count)

| File | Lines | Functions | Status | Reason for Flag |
|------|-------|-----------|--------|-----------------|
| `app/static/js/file_management.js` | ~3,750 | 70+ | **CRITICAL** | UI, state, API calls, modals, batch ops mixed |
| `app/static/js/search.js` | ~950 | 25 | HIGH | Duplicates escapeHtml, contains modal logic |
| `app/static/js/dashboard.js` | ~930 | 20 | HIGH | Duplicates escapeHtml |
| `app/static/js/nova-dashboard.js` | ~320 | 10 | MODERATE | Duplicates escapeHtml |
| `app/static/js/reports.js` | ~600 | 15 | OK | Report-specific UI |
| `app/static/js/utils.js` | ~320 | 15 | OK | Centralized utilities (should be imported everywhere) |

#### Scripts Directory

| File | Lines | Purpose |
|------|-------|---------|
| `scripts/reconcile_proxies.py` | 361 | Proxy file reconciliation |
| `scripts/estimate_chunked_response_size.py` | 230 | Video chunking estimation |
| `scripts/analyze_nova_failures.py` | 187 | Nova failure analysis |
| `scripts/backfill_transcript_summaries.py` | 144 | Transcript backfill |
| `scripts/backfill_embeddings.py` | 136 | Embedding backfill |

---

### Duplication Report

#### Critical Duplications

| Issue | Files | Lines | Description |
|-------|-------|-------|-------------|
| `escapeHtml` function | 4 files | ~10 each | Same HTML escaping logic duplicated |
| `formatDuration` function | 2 files | ~15 each | Duration formatting duplicated in JS and Python |
| `formatBytes/formatFileSize` | 3 files | ~10 each | File size formatting duplicated |
| JSON parsing try/catch | 34 occurrences | ~5 each | Repetitive JSON.loads error handling |

#### escapeHtml Duplications

**Location 1 - utils.js (canonical, line 182):**
```javascript
export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
```

**Location 2 - search.js (duplicate, line 751):**
```javascript
function escapeHtml(text) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(text || '').replace(/[&<>"']/g, m => map[m]);
}
```

**Location 3 - nova-dashboard.js (duplicate, line 309):**
Same implementation as search.js

**Location 4 - dashboard.js (duplicate, line 918):**
Same implementation as search.js

**Location 5 - file_management.js (duplicate, line 2165):**
Same implementation as search.js

**Recommendation:** Remove all duplicates, import from utils.js

#### formatDuration Duplications

**Python (formatters.py:120):**
```python
def format_duration(duration_seconds: float) -> str:
    total_seconds = int(duration_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    ...
```

**JavaScript (reports.js:19):**
```javascript
const formatDuration = (seconds) => {
    const total = Math.max(0, Math.round(seconds || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    ...
```

**Recommendation:** Keep both but ensure consistent output format

#### JSON Parsing Pattern Duplication

**Pattern found in database.py (~34 occurrences):**
```python
if job.get('analysis_types'):
    job['analysis_types'] = json.loads(job['analysis_types'])
if job.get('user_options'):
    job['user_options'] = json.loads(job['user_options'])
if job.get('summary_result'):
    job['summary_result'] = json.loads(job['summary_result'])
...
```

**Files with this pattern:**
- `app/database.py` - lines 1970-2010, 1989-2011, 2096-2120, 2129-2157
- `app/routes/search.py` - lines 99-143
- `app/routes/nova_analysis.py` - lines 85-110

**Recommendation:** Create a helper function `parse_json_fields(dict, fields)` in database.py

---

## Proposed Reorganization

### Phase 1: Database Layer Refactoring (HIGHEST PRIORITY)

#### Current Structure
```
app/database.py (~3,500 lines)
├── Connection management
├── Schema creation
├── File operations
├── Transcript operations
├── Embedding operations
├── Nova job operations
├── Rescan job operations
├── Import job operations
├── Analysis job operations
├── Search operations
├── Billing cache operations
└── Collection operations
```

#### Proposed Structure
```
app/
├── database/
│   ├── __init__.py           # Re-exports Database class + get_db()
│   ├── base.py               # Connection, schema, base operations (~300 lines)
│   ├── files.py              # File CRUD operations (~400 lines)
│   ├── transcripts.py        # Transcript operations (~250 lines)
│   ├── embeddings.py         # Vector embedding operations (~300 lines)
│   ├── nova_jobs.py          # Nova analysis job operations (~300 lines)
│   ├── analysis_jobs.py      # Rekognition job operations (~200 lines)
│   ├── async_jobs.py         # Rescan/Import job operations (~400 lines)
│   ├── search.py             # Search operations (~400 lines)
│   ├── billing_cache.py      # Billing cache operations (~200 lines)
│   └── collections.py        # Face collection operations (~150 lines)
```

#### Function Migration Map - database.py

**base.py (~300 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `__init__` | 45-85 | Initialize database connection |
| `get_connection` | 87-110 | Context manager for connections |
| `create_tables` | 112-350 | Schema creation |
| `_load_vector_extension` | 380-420 | sqlite-vec loading |
| `_ensure_embedding_tables` | 422-460 | Vector table initialization |
| `_parse_json_field` | 478-510 | JSON parsing helper |

**files.py (~400 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `create_file` | 520-580 | Create file record |
| `get_file` | 582-610 | Get file by ID |
| `get_file_by_s3_key` | 612-630 | Get file by S3 key |
| `get_file_by_fingerprint` | 632-660 | Get by content hash |
| `list_files` | 680-800 | Paginated file listing |
| `update_file` | 802-840 | Update file record |
| `delete_file` | 842-870 | Delete file |
| `get_files_summary` | 872-920 | Aggregate stats |

**transcripts.py (~250 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `create_transcript` | 1520-1560 | Create transcript record |
| `get_transcript` | 1562-1580 | Get transcript by ID |
| `get_transcripts_for_file` | 1582-1620 | Get transcripts for file |
| `count_transcripts` | 1620-1658 | Count with filters |
| `get_available_models` | 1660-1665 | List distinct models |
| `get_available_languages` | 1667-1672 | List distinct languages |

**embeddings.py (~300 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `_serialize_embedding` | 1677-1680 | Serialize vector to bytes |
| `_validate_embedding_dimension` | 1682-1686 | Validate vector dimension |
| `get_embedding_by_hash` | 1688-1698 | Get by content hash |
| `create_nova_embedding` | 1700-1728 | Store embedding |
| `search_embeddings` | 1730-1798 | KNN vector search |
| `get_content_for_embedding_results` | 1800-1891 | Enrich results |
| `delete_embeddings_for_source` | 1893-1921 | Delete embeddings |
| `get_embedding_stats` | 1922-1948 | Statistics |

**nova_jobs.py (~300 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `create_nova_job` | 1954-1963 | Create Nova job |
| `get_nova_job` | 1965-1988 | Get job by ID |
| `get_nova_job_by_analysis_job` | 1989-2012 | Get by analysis job ID |
| `update_nova_job` | 2013-2030 | Update job |
| `update_nova_job_status` | 2032-2046 | Update status |
| `update_nova_job_chunk_progress` | 2063-2090 | Chunk progress |
| `list_nova_jobs` | 2091-2120 | List with filters |
| `delete_nova_job` | 2122-2127 | Delete job |
| `get_nova_jobs_by_file` | 2129-2158 | Get for file |

**async_jobs.py (~400 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `create_rescan_job` | 2161-2169 | Create rescan job |
| `get_rescan_job` | 2171-2183 | Get rescan job |
| `update_rescan_job` | 2185-2201 | Update rescan job |
| `update_rescan_job_progress` | 2203-2228 | Update progress |
| `complete_rescan_job` | 2237-2251 | Mark complete |
| `cancel_rescan_job` | 2253-2263 | Cancel job |
| `create_import_job` | 2274-2282 | Create import job |
| `get_import_job` | 2284-2298 | Get import job |
| `update_import_job` | 2300-2316 | Update import job |
| `complete_import_job` | 2371-2386 | Mark complete |

#### Implementation Example - base.py

```python
# app/database/base.py
"""Base database operations and connection management."""
import sqlite3
import os
from contextlib import contextmanager
from typing import Optional, Any, Dict, List
import json

class DatabaseBase:
    """Base class with connection and schema management."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.getenv('DATABASE_PATH', 'data/app.db')
        self._vec_loaded = False

    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _parse_json_field(self, value: Any, default: Any = None) -> Any:
        """Parse JSON string to Python object."""
        if value is None:
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default

    def _parse_json_fields(self, row: Dict, fields: List[str]) -> Dict:
        """Parse multiple JSON fields in a row dict."""
        for field in fields:
            if field in row and row[field]:
                row[field] = self._parse_json_field(row[field])
        return row
```

---

### Phase 2: Route Handler Refactoring

#### Current Structure - file_management.py
```
app/routes/file_management.py (~2,800 lines)
├── File CRUD endpoints
├── Batch operation endpoints
├── S3 file management
├── Directory browsing
├── Import job endpoints
├── Rescan job endpoints
├── Proxy creation
├── Transcription endpoints
├── Nova analysis triggers
└── Rekognition triggers
```

#### Proposed Structure
```
app/routes/
├── file_management/
│   ├── __init__.py           # Blueprint + register subroutes
│   ├── files.py              # Core file CRUD (~400 lines)
│   ├── batch.py              # Batch operations (~600 lines)
│   ├── s3_files.py           # S3 browser endpoints (~200 lines)
│   ├── directory_browser.py  # Directory browsing (~150 lines)
│   ├── import_jobs.py        # Import job endpoints (~300 lines)
│   └── rescan_jobs.py        # Rescan job endpoints (~400 lines)
```

#### Function Migration Map - file_management.py

**files.py (~400 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `list_files` | 30-120 | GET /api/files |
| `get_file` | 122-200 | GET /api/files/<id> |
| `update_file` | 202-250 | PUT /api/files/<id> |
| `delete_file` | 252-300 | DELETE /api/files/<id> |
| `get_file_proxy` | 302-350 | GET /api/files/<id>/proxy |

**batch.py (~600 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `get_batch_files` | 850-920 | POST /api/batch/files |
| `start_batch_proxy` | 922-1000 | POST /api/batch/proxy |
| `start_batch_transcribe` | 1002-1100 | POST /api/batch/transcribe |
| `start_batch_nova` | 1110-1200 | POST /api/batch/nova |
| `start_batch_rekognition` | 1220-1300 | POST /api/batch/rekognition |
| `get_batch_status` | 1320-1400 | GET /api/batch/<id>/status |
| `cancel_batch` | 1402-1450 | POST /api/batch/<id>/cancel |

**import_jobs.py (~300 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `start_import` | 500-560 | POST /api/files/import-directory |
| `get_import_status` | 562-600 | GET /api/files/import-directory/<id>/status |
| `cancel_import` | 602-640 | POST /api/files/import-directory/<id>/cancel |

**rescan_jobs.py (~400 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `start_rescan` | 2000-2100 | POST /api/files/rescan |
| `get_rescan_status` | 2102-2180 | GET /api/files/rescan/<id>/status |
| `cancel_rescan` | 2182-2220 | POST /api/files/rescan/<id>/cancel |
| `apply_rescan` | 2222-2350 | POST /api/files/rescan/<id>/apply |

---

### Phase 3: Service Layer Refactoring

#### Current Structure - nova_service.py
```
app/services/nova_service.py (~2,500 lines)
├── Model configuration
├── Prompt templates (4 types)
├── JSON parsing
├── Analysis methods
├── Video chunking integration
├── Result aggregation
├── Data enrichment
└── Validation
```

#### Proposed Structure
```
app/services/nova/
├── __init__.py               # Re-exports NovaVideoService
├── service.py                # Main service class (~500 lines)
├── prompts.py                # Prompt templates (~600 lines)
├── parsers.py                # JSON parsing/validation (~300 lines)
├── enrichment.py             # Data enrichment functions (~200 lines)
└── models.py                 # Model configuration (~100 lines)
```

#### Function Migration Map - nova_service.py

**prompts.py (~600 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `_get_summary_prompt` | 340-390 | Summary analysis prompt |
| `_get_chapters_prompt` | 392-500 | Chapter detection prompt |
| `_get_elements_prompt` | 502-640 | Element identification prompt |
| `_get_waterfall_classification_prompt` | 642-800 | Waterfall classification prompt |
| `_get_combined_prompt` | 1637-1865 | Combined analysis prompt |
| `_load_waterfall_assets` | 802-840 | Load waterfall spec files |
| `_build_contextual_prompt` | 842-900 | Build context-aware prompt |

**parsers.py (~300 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `_parse_json_response` | 1048-1120 | Parse Nova JSON response |
| `_validate_waterfall_classification` | 1122-1180 | Validate classification |
| `_fix_unterminated_string` | 1182-1220 | Fix JSON errors |

**enrichment.py (~200 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `_enrich_chapter_data` | 900-940 | Add computed chapter fields |
| `_enrich_equipment_data` | 942-970 | Add computed equipment fields |
| `_enrich_topic_data` | 972-1000 | Add computed topic fields |
| `_enrich_speaker_data` | 1002-1030 | Add computed speaker fields |
| `_build_topics_summary` | 1032-1046 | Build summary from topics |

**models.py (~100 lines)**
| Function | Current Line | Purpose |
|----------|--------------|---------|
| `MODELS` | 88-120 | Model configuration dict |
| `get_model_config` | 122-135 | Get config by name |
| `calculate_cost` | 137-160 | Calculate token costs |

---

### Phase 4: Frontend JavaScript Refactoring

#### Current Structure - file_management.js
```
app/static/js/file_management.js (~3,750 lines)
├── State management (50 lines)
├── Event listeners (300 lines)
├── Filter management (200 lines)
├── Directory import (200 lines)
├── Directory filter (100 lines)
├── File loading/rendering (400 lines)
├── Pagination (100 lines)
├── File details modal (400 lines)
├── Transcript modal (200 lines)
├── S3 files section (300 lines)
├── Batch operations (800 lines)
├── Single file actions (400 lines)
├── Rescan operations (400 lines)
└── Utility functions (150 lines)
```

#### Proposed Structure
```
app/static/js/file_management/
├── index.js                  # Main entry, state, initialization
├── state.js                  # State management
├── filters.js                # Filter UI and logic
├── file-list.js              # File loading and rendering
├── file-details.js           # File details modal
├── batch-operations.js       # Batch action handling
├── s3-browser.js             # S3 file management
├── import-export.js          # Import/rescan operations
└── actions.js                # Single file actions
```

#### escapeHtml Consolidation

**Files to modify:**
1. `search.js` - Remove duplicate, add import
2. `dashboard.js` - Remove duplicate, add import
3. `nova-dashboard.js` - Remove duplicate, add import
4. `file_management.js` - Remove duplicate, add import

**Current duplicate (to remove):**
```javascript
// search.js:751, dashboard.js:918, nova-dashboard.js:309, file_management.js:2165
function escapeHtml(text) {
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return String(text || '').replace(/[&<>"']/g, m => map[m]);
}
```

**Add to each file:**
```javascript
import { escapeHtml } from './utils.js';
```

---

## Dependency Impact Analysis

### Import Changes Required

#### Database Module Refactoring

**Before:**
```python
from app.database import get_db
```

**After:**
```python
from app.database import get_db  # Re-exported from __init__.py - no change needed
```

**app/database/__init__.py:**
```python
from app.database.base import DatabaseBase
from app.database.files import FilesMixin
from app.database.transcripts import TranscriptsMixin
from app.database.embeddings import EmbeddingsMixin
from app.database.nova_jobs import NovaJobsMixin
from app.database.async_jobs import AsyncJobsMixin
from app.database.search import SearchMixin
from app.database.billing_cache import BillingCacheMixin
from app.database.collections import CollectionsMixin

class Database(
    DatabaseBase,
    FilesMixin,
    TranscriptsMixin,
    EmbeddingsMixin,
    NovaJobsMixin,
    AsyncJobsMixin,
    SearchMixin,
    BillingCacheMixin,
    CollectionsMixin
):
    """Unified database interface using mixins."""
    pass

_db_instance = None

def get_db():
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
```

#### Route Blueprint Refactoring

**Before (app/__init__.py):**
```python
from app.routes import (
    file_management,
    nova_analysis,
    # ...
)
app.register_blueprint(file_management.bp)
```

**After:**
```python
from app.routes import (
    file_management,  # Now a package with sub-blueprints
    nova_analysis,
    # ...
)
app.register_blueprint(file_management.bp)  # Same API
```

**app/routes/file_management/__init__.py:**
```python
from flask import Blueprint

bp = Blueprint('file_management', __name__)

from app.routes.file_management import files
from app.routes.file_management import batch
from app.routes.file_management import s3_files
from app.routes.file_management import import_jobs
from app.routes.file_management import rescan_jobs
```

### Circular Dependency Risks

| Risk Area | Current State | Mitigation |
|-----------|---------------|------------|
| file_management -> upload | Imports create_proxy_internal | Move to shared service |
| file_management -> analysis | Imports start_analysis_job | Move to shared service |
| file_management -> nova_analysis | Imports start_nova_analysis_internal | Move to shared service |
| nova_service -> video_chunker | Late import in method | Keep late import |
| nova_service -> nova_aggregator | Late import in method | Keep late import |

**Recommended Solution:**
Create `app/services/orchestration.py` with shared functions:
- `trigger_proxy_creation(file_id)`
- `trigger_transcription(file_id, options)`
- `trigger_nova_analysis(file_id, options)`
- `trigger_rekognition_analysis(file_id, analysis_types)`

---

## Migration Steps

### Step 1: Database Layer (Week 1-2)

1. **Create database package structure**
   ```bash
   mkdir -p app/database
   touch app/database/__init__.py
   touch app/database/base.py
   touch app/database/files.py
   touch app/database/transcripts.py
   touch app/database/embeddings.py
   touch app/database/nova_jobs.py
   touch app/database/async_jobs.py
   touch app/database/search.py
   touch app/database/billing_cache.py
   touch app/database/collections.py
   ```

2. **Extract base module** - Move connection management, schema creation
3. **Extract files module** - Move file CRUD operations
4. **Extract remaining modules** - One at a time, testing after each
5. **Create unified Database class** using mixins
6. **Update __init__.py** to re-export get_db()
7. **Run full test suite**

### Step 2: Service Layer (Week 3)

1. **Create nova package structure**
   ```bash
   mkdir -p app/services/nova
   touch app/services/nova/__init__.py
   touch app/services/nova/service.py
   touch app/services/nova/prompts.py
   touch app/services/nova/parsers.py
   touch app/services/nova/enrichment.py
   touch app/services/nova/models.py
   ```

2. **Extract prompts module** - All `_get_*_prompt` methods
3. **Extract parsers module** - JSON parsing and validation
4. **Extract enrichment module** - Data enrichment functions
5. **Extract models module** - Model configuration
6. **Update NovaVideoService** to import from submodules
7. **Run Nova analysis tests**

### Step 3: Route Handlers (Week 4)

1. **Create file_management package structure**
   ```bash
   mkdir -p app/routes/file_management
   touch app/routes/file_management/__init__.py
   touch app/routes/file_management/files.py
   touch app/routes/file_management/batch.py
   touch app/routes/file_management/s3_files.py
   touch app/routes/file_management/import_jobs.py
   touch app/routes/file_management/rescan_jobs.py
   ```

2. **Create orchestration service** for cross-route function calls
3. **Extract files module** - Core CRUD endpoints
4. **Extract batch module** - Batch operation endpoints
5. **Extract remaining modules**
6. **Update __init__.py** with blueprint registration
7. **Run API integration tests**

### Step 4: JavaScript Consolidation (Week 5)

1. **Remove escapeHtml duplicates** from search.js, dashboard.js, nova-dashboard.js, file_management.js
2. **Add imports** from utils.js
3. **Verify all pages still work**

### Step 5: JSON Parsing Utility (Week 5)

1. **Add _parse_json_fields helper** to database base module
2. **Refactor all get_* methods** to use the helper
3. **Test database operations**

---

## Risk Assessment

### What Could Break

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Import path changes | Medium | High | Use re-exports in __init__.py |
| Circular imports | Medium | High | Use late imports where needed |
| Missing function migrations | Low | Medium | Comprehensive testing |
| Blueprint registration | Low | High | Test all routes after changes |
| JavaScript module loading | Low | Medium | Use ES module imports correctly |

### Testing Requirements

1. **Unit Tests**
   - Database operations still work after split
   - Nova service methods produce same results
   - Route handlers respond correctly

2. **Integration Tests**
   - File upload flow
   - Batch operation flow
   - Import/rescan flow
   - Nova analysis flow
   - Search flow

3. **Manual Testing**
   - All UI pages load
   - All modals function
   - All batch operations complete
   - All filters work

### Rollback Considerations

1. **Keep original files** until migration complete
2. **Git feature branch** for each phase
3. **Database schema unchanged** - no migration needed
4. **API contracts unchanged** - frontend compatible

---

## Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Database | 2 weeks | None |
| Phase 2: Services | 1 week | Phase 1 |
| Phase 3: Routes | 1 week | Phase 1 |
| Phase 4: JavaScript | 1 week | None |
| Phase 5: Testing | 1 week | All phases |
| **Total** | **6 weeks** | |

---

## Appendix: Function Count by File

### Python Files
| File | Functions | Classes | Lines |
|------|-----------|---------|-------|
| database.py | 82 | 1 | ~3,500 |
| file_management.py | 45 | 0 | ~2,800 |
| nova_service.py | 38 | 1 | ~2,500 |
| search.py | 15 | 0 | ~720 |
| transcription.py | 22 | 0 | ~900 |
| billing_service.py | 18 | 2 | ~620 |
| rekognition_video.py | 22 | 2 | ~450 |
| upload.py | 14 | 0 | ~530 |

### JavaScript Files
| File | Functions | Lines |
|------|-----------|-------|
| file_management.js | 72 | ~3,750 |
| search.js | 28 | ~950 |
| dashboard.js | 24 | ~930 |
| reports.js | 18 | ~600 |
| nova-dashboard.js | 12 | ~320 |
| utils.js | 16 | ~320 |

---

*Document generated: 2025-12-30*
*Analysis performed on: AWS Video & Image Analysis Application*
