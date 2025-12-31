# Large File Splitting Plan

## Overview

This document outlines the plan to address files exceeding Claude Code's 25,000 token read limit, ensuring the entire codebase can be efficiently read and maintained.

**Token Limit:** 25,000 tokens (hardcoded in Claude Code)
**Scan Date:** 2025-12-30
**Last Updated:** 2025-12-30

---

## Files Exceeding Token Limit

| File | Lines | Status | Action |
|------|-------|--------|--------|
| `app/database.py` | 3,937 | Legacy - superseded by package | Delete |
| `app/routes/file_management/core.py` | 2,342 | Contains duplicate routes | Remove duplicates |
| `app/static/js/file_management.js` | 3,735 | Monolithic JS | Refactor (Phase 3) |

---

## Current State Analysis

### Route Registration Conflict
Both `core.py` and submodule blueprints define the same routes. Flask registers all blueprints in `app/__init__.py`:
- Main `file_management_bp` (from core.py) registered first
- Submodule blueprints (`batch_bp`, `s3_files_bp`, etc.) registered after

**Result:** Submodule routes take precedence, but duplicate code in core.py wastes tokens and creates maintenance burden.

### Database Module Resolution
Python package import precedence: `app/database/` package is imported when using `from app.database import`.
The old `app/database.py` file is bypassed but still exists (3,937 lines of dead code).

---

## Phase 1: Delete Legacy Database File

**File:** `app/database.py` (3,937 lines)
**Status:** Legacy - fully replaced by `app/database/` package
**Risk:** LOW

### Pre-Deletion Verification

```bash
# 1. Verify all imports resolve to package (should show no results)
grep -r "from app import database" app/ scripts/

# 2. Verify package exports match old file's public interface
python -c "from app.database import get_db, init_db, Database; print('OK')"

# 3. Run the application and verify database operations work
python run.py
# Test: Navigate to /files, verify files list loads
```

### Deletion Steps
1. Create backup: `copy app\database.py app\database.py.bak`
2. Delete the file: `del app\database.py`
3. Test application startup and basic operations
4. If successful, remove backup

### Rollback
```bash
# If issues occur, restore from backup or git:
git checkout HEAD -- app/database.py
```

---

## Phase 2: Remove Duplicate Routes from core.py

**File:** `app/routes/file_management/core.py`
**Current:** 2,342 lines
**Target:** ~800 lines (remove ~1,500 lines of duplicates)
**Risk:** MEDIUM - Requires careful verification

### Duplicate Route Mapping

| Route in core.py | Also in | Line Range (core.py) |
|-----------------|---------|---------------------|
| `/api/files/browse` | `directory_browser.py` | 411-480 |
| `/api/files/system-browse` | `directory_browser.py` | 482-519 |
| `/api/files/import-directory` | `import_jobs.py` | 522-570 |
| `/api/files/import-directory/<job_id>/status` | `import_jobs.py` | 573-610 |
| `/api/files/import-directory/<job_id>/cancel` | `import_jobs.py` | 612-643 |
| `/api/s3-files` | `s3_files.py` | 1247-1300 |
| `/api/s3-file/<path:s3_key>/download-url` | `s3_files.py` | 1302-1328 |
| `/api/s3-file/<path:s3_key>` (DELETE) | `s3_files.py` | 1330-1355 |
| `/api/s3-files/delete-all` | `s3_files.py` | 1357-1405 |
| `/api/batch/*` (all 8 endpoints) | `batch.py` | 1418-2010 |
| `/api/files/rescan` | `rescan_jobs.py` | 2013-2069 |
| `/api/files/rescan/<job_id>/status` | `rescan_jobs.py` | 2071-2105 |
| `/api/files/rescan/<job_id>/cancel` | `rescan_jobs.py` | 2107-2138 |
| `/api/files/rescan/apply` | `rescan_jobs.py` | 2140-2212 |

### Also Remove (Already in shared.py)
- `BatchJob` class (lines 30-111)
- `_batch_jobs` dict and lock (lines 26-27)
- `_normalize_transcription_provider()` (lines 112-123)
- `_select_latest_completed_transcript()` (lines 125-142)
- `_run_batch_*` worker functions (lines 2214-2812)

### Routes to KEEP in core.py
These routes are NOT duplicated elsewhere:
- `GET /files` - Page route (line 144)
- `GET /api/files` - List files with filters (line 154)
- `GET /api/files/<int:file_id>` - Get single file (line 645)
- `GET /api/files/<int:file_id>/s3-files` - Get S3 files for file (line 752)
- `GET /api/files/<int:file_id>/nova-analyses` - Get Nova analyses (line 795)
- `POST /api/files/<int:file_id>/create-proxy` - Create proxy (line 875)
- `POST /api/files/<int:file_id>/start-analysis` - Start Rekognition (line 908)
- `POST /api/files/<int:file_id>/start-transcription` - Start transcription (line 969)
- `POST /api/files/<int:file_id>/start-nova` - Start Nova analysis (line 1103)
- `DELETE /api/files/<int:file_id>` - Delete file (line 1169)

### Pre-Cleanup Verification

```bash
# 1. Verify submodule routes are working (run app, test these endpoints)
curl http://localhost:5700/api/s3-files
curl -X POST http://localhost:5700/api/files/browse -H "Content-Type: application/json" -d "{\"path\": \".\"}"

# 2. Verify submodules import from shared.py correctly
python -c "from app.routes.file_management.batch import bp; print('batch OK')"
python -c "from app.routes.file_management.s3_files import bp; print('s3_files OK')"

# 3. Check core.py still has necessary imports
grep "from app.routes.file_management.shared import" app/routes/file_management/core.py
```

### Implementation Steps

1. **Backup core.py**
   ```bash
   copy app\routes\file_management\core.py app\routes\file_management\core.py.bak
   ```

2. **Update imports in core.py** (if not already done)
   Add at top of file:
   ```python
   from app.routes.file_management.shared import (
       BatchJob,
       get_batch_job,
       set_batch_job,
       delete_batch_job,
       normalize_transcription_provider,
       select_latest_completed_transcript,
   )
   ```

3. **Remove duplicate code sections** in order from bottom to top:
   - Lines 2214-2812: `_run_batch_*` worker functions
   - Lines 2013-2212: Rescan routes
   - Lines 1418-2010: Batch routes
   - Lines 1247-1405: S3 files routes
   - Lines 522-643: Import job routes
   - Lines 411-519: Directory browser routes
   - Lines 112-142: Helper functions (if using shared.py)
   - Lines 26-111: BatchJob class and state

4. **Verify Python syntax**
   ```bash
   python -m py_compile app/routes/file_management/core.py
   ```

5. **Test all endpoints** (see verification checklist below)

### Rollback
```bash
copy app\routes\file_management\core.py.bak app\routes\file_management\core.py
```

---

## Phase 3: Refactor file_management.js (Optional)

**File:** `app/static/js/file_management.js`
**Current:** 3,735 lines
**Target:** Split into 5-6 modules, each under 1,000 lines
**Risk:** HIGH - Extensive testing required
**Priority:** LOW - Functional but large

### Proposed Module Structure

```
app/static/js/file_management/
├── index.js              # Main entry point, imports and initializes modules
├── state.js              # Application state management
├── api.js                # API calls and data fetching
├── filters.js            # Filter UI and logic
├── table.js              # Table rendering and interactions
├── batch-operations.js   # Batch processing UI
├── modals.js             # Modal dialogs
└── utils.js              # Utility functions
```

### Considerations
- Requires ES6 module support or bundler (Webpack/Vite)
- Must update HTML to use new module structure
- Maintain backward compatibility with existing event handlers
- Extensive testing required for all interactive features

### Recommended Approach
1. Create new module structure alongside existing file
2. Migrate one module at a time
3. Test thoroughly after each migration
4. Only delete original file after full validation

---

## Verification Checklist

### After Phase 1 (Delete database.py)
- [ ] Application starts: `python run.py`
- [ ] Navigate to http://localhost:5700/files - page loads
- [ ] Files list displays correctly
- [ ] Can view file details (click on a file)
- [ ] No import errors in console/logs

### After Phase 2 (Clean core.py)
Test each endpoint category:

**Core File Operations (should still work - kept in core.py)**
- [ ] `GET /files` - Page loads
- [ ] `GET /api/files` - Files list returns JSON
- [ ] `GET /api/files/<id>` - File details return
- [ ] `DELETE /api/files/<id>` - File deletion works
- [ ] `POST /api/files/<id>/create-proxy` - Proxy creation starts
- [ ] `POST /api/files/<id>/start-analysis` - Rekognition starts
- [ ] `POST /api/files/<id>/start-transcription` - Transcription starts
- [ ] `POST /api/files/<id>/start-nova` - Nova analysis starts

**Batch Operations (now in batch.py)**
- [ ] `POST /api/batch/proxy` - Batch proxy starts
- [ ] `POST /api/batch/transcribe` - Batch transcription starts
- [ ] `POST /api/batch/nova` - Batch Nova starts
- [ ] `GET /api/batch/<job_id>/status` - Status returns
- [ ] `POST /api/batch/<job_id>/cancel` - Cancel works

**S3 Operations (now in s3_files.py)**
- [ ] `GET /api/s3-files` - S3 files list
- [ ] `GET /api/s3-file/<key>/download-url` - Download URL works
- [ ] `DELETE /api/s3-file/<key>` - S3 delete works

**Directory Operations (now in directory_browser.py)**
- [ ] `POST /api/files/browse` - Directory browse works
- [ ] `POST /api/files/system-browse` - System browse works

**Import/Rescan Operations**
- [ ] `POST /api/files/import-directory` - Import starts
- [ ] `POST /api/files/rescan` - Rescan starts

### After Phase 3 (Split file_management.js)
- [ ] File list loads and displays correctly
- [ ] Filters work (all filter types)
- [ ] Pagination works
- [ ] Batch operations UI works
- [ ] File details modal works
- [ ] No JavaScript console errors

---

## Safety Notes

1. **Always backup before changes**
   ```bash
   git stash   # Or commit current changes
   ```

2. **Test with the application running**
   ```bash
   python run.py
   ```

3. **Check logs for errors**
   Watch the terminal running run.py for any import or route errors.

4. **Commit after each phase**
   ```bash
   git add -A && git commit -m "Phase N: description"
   ```

5. **Don't proceed to next phase until current phase is verified**

---

## Related Files

- `tasks.md` - Overall codebase reorganization tracking
- `program_retooling.md` - Original reorganization plan
- `CLAUDE.md` - Project documentation
