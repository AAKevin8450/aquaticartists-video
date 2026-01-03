# Codebase Cleanup Plan

This document provides a comprehensive, step-by-step plan to remove legacy code, unused database fields, and organize the codebase. Each section can be executed independently.

---

## Table of Contents

1. [Face Collections Complete Removal](#1-face-collections-complete-removal)
2. [Root Directory Cleanup](#2-root-directory-cleanup)
3. [Database Schema Cleanup](#3-database-schema-cleanup)
4. [Search Page Collection References](#4-search-page-collection-references)
5. [Deprecated Endpoint Cleanup](#5-deprecated-endpoint-cleanup)
6. [Test Files and Artifacts Cleanup](#6-test-files-and-artifacts-cleanup)
7. [Documentation Consolidation](#7-documentation-consolidation)
8. [Final Verification](#8-final-verification)

---

## 1. Face Collections Complete Removal

**Status**: Face Collections was a planned feature that was never fully implemented. UI references were already removed. This section removes all backend code.

### 1.1 Remove Database Table and Index

**File**: `app/database/base.py`

**Action 1**: Remove the face_collections table creation (lines 182-192):
```python
# DELETE THIS ENTIRE BLOCK:
            # Face collections table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS face_collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_id TEXT UNIQUE NOT NULL,
                    collection_arn TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    face_count INTEGER DEFAULT 0,
                    metadata JSON
                )
            ''')
```

**Action 2**: Remove the face_collections index from search_indexes list (line 375):
```python
# DELETE THIS LINE:
                ('idx_collections_created_at', 'face_collections', 'created_at DESC'),
```

### 1.2 Delete Collections Mixin File

**Action**: Delete the entire file:
```
app/database/collections.py
```

### 1.3 Remove Collections Mixin from Database Class

**File**: `app/database/__init__.py`

**Action 1**: Remove import (line 23):
```python
# DELETE THIS LINE:
from app.database.collections import CollectionsMixin
```

**Action 2**: Remove from class inheritance (line 36):
```python
# DELETE: CollectionsMixin from the class definition
# Change from:
class Database(
    DatabaseBase,
    FilesMixin,
    TranscriptsMixin,
    EmbeddingsMixin,
    NovaJobsMixin,
    AnalysisJobsMixin,
    AsyncJobsMixin,
    SearchMixin,
    BillingCacheMixin,
    CollectionsMixin  # <-- DELETE THIS LINE
):

# To:
class Database(
    DatabaseBase,
    FilesMixin,
    TranscriptsMixin,
    EmbeddingsMixin,
    NovaJobsMixin,
    AnalysisJobsMixin,
    AsyncJobsMixin,
    SearchMixin,
    BillingCacheMixin
):
```

**Action 3**: Update docstring (lines 41-51) - Remove:
```python
# DELETE THIS LINE from docstring:
        - CollectionsMixin: Collection operations
```

### 1.4 Create Database Migration Script

**Action**: Create a new migration file `migrations/011_remove_face_collections.sql`:
```sql
-- Migration 011: Remove face_collections table (legacy feature never implemented)
-- Date: 2026-01-03

-- Drop the index first
DROP INDEX IF EXISTS idx_collections_created_at;

-- Drop the table
DROP TABLE IF EXISTS face_collections;
```

---

## 2. Root Directory Cleanup

The root directory contains many legacy scripts from early development. These should be moved or deleted.

### 2.1 Files to DELETE (One-time migration/test scripts no longer needed)

| File | Reason |
|------|--------|
| `migrate_db.py` | Legacy migration for file_modified_time column - already applied |
| `migrate_transcripts.py` | One-time migration to import transcripts - already applied |
| `migrate_transcript_metadata.py` | One-time metadata migration - already applied |
| `run_migration.py` | Runs 001_add_nova_jobs.sql - already applied |
| `run_migration_004.py` | Runs 004 migration - already applied |
| `backfill_file_timestamps.py` | One-time backfill - already applied |
| `fix_file_hash.py` | One-time hash fix - already applied |
| `check_completeness.py` | Debug script - no longer needed |
| `check_database_status.py` | Debug script - superseded by dashboard |
| `check_db.py` | Uses outdated schema (model_used, file_size_bytes) |
| `check_duration_summary.py` | Debug script - no longer needed |
| `verify_schema.py` | Uses outdated schema (file_modified_time, model_used, etc.) |
| `verify_migration.py` | One-time verification - already done |
| `test_api_simple.py` | Ad-hoc test - not part of test suite |
| `test_duration_query.py` | Ad-hoc test - not part of test suite |
| `test_endpoints.py` | Ad-hoc test - not part of test suite |
| `test_escape_fix.py` | One-time bug fix test - already resolved |
| `test_final_verification.py` | One-time verification - already done |
| `test_fix_simple.py` | One-time bug fix test - already resolved |
| `test_image_analysis.py` | Ad-hoc test - not part of test suite |
| `test_migration.py` | One-time migration test - already done |
| `test_multiselect.py` | Feature test - already verified |
| `test_new_methods.py` | Ad-hoc test - not part of test suite |
| `test_nova_setup.py` | Setup verification - already done |
| `test_summary.py` | Ad-hoc test - not part of test suite |
| `nul` | Accidental Windows file creation artifact |

### 2.2 Files to KEEP

| File | Reason |
|------|--------|
| `run.py` | Main application entry point |
| `fix_s3_cors.py` | Utility - may be needed for new deployments |
| `requirements.txt` | Dependencies |
| `README.md` | Project documentation |
| `CLAUDE.md` | AI instructions |
| `AGENTS.md` | AI configuration |
| `.env` | Environment configuration |
| `.env.example` | Environment template |
| `.gitignore` | Git configuration |
| `changelog.txt` | Change history |

### 2.3 Command to Execute Deletions

```bash
# Windows PowerShell
Remove-Item -Path @(
    "migrate_db.py",
    "migrate_transcripts.py",
    "migrate_transcript_metadata.py",
    "run_migration.py",
    "run_migration_004.py",
    "backfill_file_timestamps.py",
    "fix_file_hash.py",
    "check_completeness.py",
    "check_database_status.py",
    "check_db.py",
    "check_duration_summary.py",
    "verify_schema.py",
    "verify_migration.py",
    "test_api_simple.py",
    "test_duration_query.py",
    "test_endpoints.py",
    "test_escape_fix.py",
    "test_final_verification.py",
    "test_fix_simple.py",
    "test_image_analysis.py",
    "test_migration.py",
    "test_multiselect.py",
    "test_new_methods.py",
    "test_nova_setup.py",
    "test_summary.py",
    "nul"
)

# Or Git Bash / Linux
rm -f migrate_db.py migrate_transcripts.py migrate_transcript_metadata.py \
      run_migration.py run_migration_004.py backfill_file_timestamps.py \
      fix_file_hash.py check_completeness.py check_database_status.py \
      check_db.py check_duration_summary.py verify_schema.py verify_migration.py \
      test_api_simple.py test_duration_query.py test_endpoints.py \
      test_escape_fix.py test_final_verification.py test_fix_simple.py \
      test_image_analysis.py test_migration.py test_multiselect.py \
      test_new_methods.py test_nova_setup.py test_summary.py nul
```

---

## 3. Database Schema Cleanup

The current schema has some legacy fields in the transcripts table that may need review.

### 3.1 Transcripts Table Current vs Original Schema

The current `transcripts` table in `base.py` (lines 194-218) uses:
- `file_size` (INTEGER) - Current name
- `modified_time` (REAL) - Current name
- `model_name` (TEXT) - Current name
- `segments` (TEXT) - Current name

Some root directory scripts (now deleted) referenced old column names:
- `file_size_bytes` - Old name
- `file_modified_time` - Old name
- `model_used` - Old name
- `transcript_segments` - Old name

**No action needed** - The scripts using old names are being deleted in Section 2.

### 3.2 Migration Columns Cleanup (Optional)

**File**: `app/database/base.py` (lines 220-238)

The migration_columns list contains column additions that are now part of the main schema. These can remain for backward compatibility with existing databases but the comments could be updated:

```python
# No action required - these ensure old databases get upgraded
migration_columns = [
    ('transcripts', 'character_count', 'INTEGER'),
    ('transcripts', 'word_count', 'INTEGER'),
    # ... etc
]
```

---

## 4. Search Page Collection References

**Status**: Partially done (search.js updated), but search.html still has UI elements.

### 4.1 Remove Collection Checkbox from Search Filters

**File**: `app/templates/search.html`

**Action**: Find and remove the collection filter checkbox (lines 97-99):
```html
<!-- DELETE THIS ENTIRE BLOCK -->
                            <input class="form-check-input source-filter" type="checkbox" value="collection" id="sourceCollection" checked>
                            <label class="form-check-label" for="sourceCollection">
                                <i class="bi bi-people"></i> Collections
```

Also remove the closing `</label>` and any `</div>` wrapper that was specific to this checkbox.

**Full context** - Look for a structure like this and remove the collection item:
```html
<div class="form-check">
    <input class="form-check-input source-filter" type="checkbox" value="file" id="sourceFile" checked>
    <label class="form-check-label" for="sourceFile">
        <i class="bi bi-file-earmark"></i> Files
    </label>
</div>
<div class="form-check">
    <input class="form-check-input source-filter" type="checkbox" value="transcript" id="sourceTranscript" checked>
    <label class="form-check-label" for="sourceTranscript">
        <i class="bi bi-card-text"></i> Transcripts
    </label>
</div>
<div class="form-check">
    <input class="form-check-input source-filter" type="checkbox" value="nova" id="sourceNova" checked>
    <label class="form-check-label" for="sourceNova">
        <i class="bi bi-stars"></i> Nova
    </label>
</div>
<!-- DELETE THE FOLLOWING -->
<div class="form-check">
    <input class="form-check-input source-filter" type="checkbox" value="collection" id="sourceCollection" checked>
    <label class="form-check-label" for="sourceCollection">
        <i class="bi bi-people"></i> Collections
    </label>
</div>
```

---

## 5. Deprecated Endpoint Cleanup

### 5.1 Remove Deprecated Batch Image Proxy Endpoint

**File**: `app/routes/file_management/batch.py`

**Status**: Currently has a deprecated endpoint that redirects to the unified endpoint.

**Action**: Delete the entire function (lines 161-189):
```python
# DELETE THIS ENTIRE FUNCTION:
@bp.route('/api/batch/image-proxy', methods=['POST'])
def batch_create_image_proxy():
    """
    DEPRECATED: Use /api/batch/proxy instead (supports both videos and images).
    ...
    """
    current_app.logger.info(f"DEPRECATED batch image-proxy endpoint called, redirecting to unified proxy endpoint")
    return batch_create_proxy()
```

**Note**: Before deleting, verify no external systems are calling this endpoint. The CLAUDE.md already documents using `/api/batch/proxy` instead.

---

## 6. Test Files and Artifacts Cleanup

### 6.1 Tests Directory Cleanup

**Location**: `tests/`

**Files to DELETE** (old test artifacts, not actual test code):
- `tests/IntroVideo.json` - Test fixture JSON (3MB)
- `tests/job-d5feb45a5a1c1b9e4beea439162323406bece4f5775f87e0d1e27541f86a1abc-results.xlsx` - Test output
- `tests/Robinson.jpg` - Test image
- `tests/Two_puppet_friends_202507101845.mp4` - Test video (10MB)

**Directories to DELETE** (empty):
- `tests/test_routes/`
- `tests/test_services/`

**Files to KEEP**:
- `tests/test_nova_context.py` - Active unit tests
- `tests/test_nova_integration.py` - Active integration tests

**Command**:
```bash
rm -f tests/IntroVideo.json \
      "tests/job-d5feb45a5a1c1b9e4beea439162323406bece4f5775f87e0d1e27541f86a1abc-results.xlsx" \
      tests/Robinson.jpg \
      tests/Two_puppet_friends_202507101845.mp4
rmdir tests/test_routes tests/test_services
```

### 6.2 Results Templates Directory (Empty)

**Location**: `app/templates/results/`

**Status**: Empty directory

**Action**: Delete if empty, or check if it should contain anything:
```bash
rmdir app/templates/results
```

---

## 7. Documentation Consolidation

### 7.1 Docs Directory Review

**Location**: `docs/`

**Files that could be archived or deleted** (superseded by CLAUDE.md):
| File | Status |
|------|--------|
| `20251217_testing_plan.md` | Historical - archive or delete |
| `20251218NovaImplementation.md` | Historical - archive or delete |
| `20251221_Improvements.txt` | Historical - archive or delete |
| `20251221_nova_embeddings.md` | Historical - archive or delete |
| `FILE_TRACKING_IMPROVEMENTS.md` | Historical - archive or delete |
| `IAM_POLICY_NOVA.json` | **KEEP** - reference for deployment |
| `IMPLEMENTATION_SUMMARY.md` | Historical - archive or delete |
| `MULTI_SELECT_TESTING.md` | Historical - archive or delete |
| `nova_combined.md` | Historical - archive or delete |
| `NOVA_IAM_SETUP.md` | **KEEP** - reference for deployment |
| `NOVA_PROGRESS.md` | Historical - archive or delete |
| `Nova_Waterfall_Classification_Decision_Tree.md` | **KEEP** - reference for waterfall logic |
| `Nova_Waterfall_Classification_Spec.json` | **KEEP** - reference for waterfall logic |
| `program_plan.md` | Historical - contains face_collection references |
| `status.md` | Historical - archive or delete |
| `TRANSCRIPTION_SETUP.md` | **KEEP** - reference for setup |
| `UX_IMPROVEMENTS_SUMMARY.md` | Historical - archive or delete |

**Recommendation**: Create `docs/archive/` and move historical files there rather than deleting.

### 7.2 Planning Directory

**Location**: `planning/`

**Action**: Contains one active file (`search-page-plan.md`). Can be archived after cleanup is complete.

### 7.3 Prompts Directory

**Location**: `prompts/`

**Status**: Contains historical Claude prompts used during development.

**Action**: Archive to `prompts/archive/` or delete after cleanup is verified.

---

## 8. Final Verification

After completing all sections, run these verification steps:

### 8.1 Application Startup Test
```bash
cd E:\coding\video
.\.venv\Scripts\activate
python run.py
```
Verify the application starts without errors.

### 8.2 Database Migration Test
```bash
# Backup database first
copy data\app.db data\app.db.backup

# Run migration
sqlite3 data\app.db < migrations\011_remove_face_collections.sql

# Verify table is gone
sqlite3 data\app.db "SELECT name FROM sqlite_master WHERE type='table' AND name='face_collections';"
# Should return empty (no output)
```

### 8.3 Search Functionality Test
1. Navigate to `/search`
2. Verify no "Collections" checkbox appears in filters
3. Perform a search and verify results display correctly

### 8.4 Grep Verification
```bash
# Verify no face_collection references remain in active code
grep -r "face_collection" app/ --include="*.py" --include="*.html" --include="*.js"
# Should return empty or only comments

grep -r "CollectionsMixin" app/
# Should return empty
```

### 8.5 Git Status
```bash
git status
# Review all deleted files before committing
```

---

## Execution Order

For safe execution, follow this order:

1. **Backup first**: `copy data\app.db data\app.db.backup`
2. Section 4: Search page HTML cleanup (low risk)
3. Section 1: Face Collections removal (database + code)
4. Section 5: Deprecated endpoint removal (low risk)
5. Section 2: Root directory cleanup (file deletions)
6. Section 6: Test artifacts cleanup (file deletions)
7. Section 3: Verify database schema (read-only check)
8. Section 7: Documentation consolidation (optional)
9. Section 8: Final verification

---

## Summary of Changes

| Category | Items Removed | Impact |
|----------|---------------|--------|
| Database Table | `face_collections` | None - never used |
| Database Index | `idx_collections_created_at` | None - never used |
| Python Files | 1 mixin file + 27 root scripts | Cleanup only |
| Template Changes | 1 checkbox element | UI cleanup |
| Deprecated Endpoints | `/api/batch/image-proxy` | Breaking change if used externally |
| Test Artifacts | 4 files + 2 empty dirs | Cleanup only |

**Total Files Removed**: ~35 files
**Lines of Code Removed**: ~2,500 lines (estimated)
**Risk Level**: Low (Face Collections was never functional)
