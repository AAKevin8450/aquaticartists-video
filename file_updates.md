# Folder Rescan & File Update Implementation Plan

## Overview

This document outlines the implementation plan for a folder rescan feature that allows users to detect and handle changes to source files, including:
- **Renamed/moved folders** - Update file records to new paths while preserving analysis data
- **Deleted files** - Remove orphaned database records
- **New files** - Import newly discovered files

## Current State Analysis

### Database Schema (files table)
Key fields relevant to this feature:
- `id` - Primary key
- `filename` - Original filename
- `s3_key` - S3 object key (NULL for local imports)
- `local_path` - Absolute filesystem path (used for local imports)
- `size_bytes` - File size
- `metadata` - JSON field containing:
  - `source_directory` - Original import directory
  - `file_mtime` - File modification timestamp
  - `file_ctime` - File creation timestamp

### Related Tables (CASCADE DELETE)
- `files` (proxy) → `source_file_id` REFERENCES `files(id)`
- `analysis_jobs` → `file_id` REFERENCES `files(id)`
- `nova_jobs` → `analysis_job_id` REFERENCES `analysis_jobs(id)`
- `transcripts` → Links via `file_path` or `file_id`
- `nova_embedding_metadata` → `file_id` FOREIGN KEY

### Key Insight
Files can be uniquely identified by a **fingerprint** combining:
- `filename` (basename only)
- `size_bytes`
- `file_mtime` (modification timestamp from metadata)

This fingerprint approach allows detecting files that moved to new folders without requiring expensive file hashing.

---

## Implementation Strategy

### Two-Tier Approach

**Tier 1: Smart Matching (Preferred)**
- Use fingerprint matching to detect moved files
- Update `local_path` and `metadata.source_directory` in place
- Preserves ALL existing analysis data (proxies, transcripts, nova jobs, rekognition jobs)

**Tier 2: Simple Resync (Fallback)**
- Delete all records for files not found at original paths
- Re-import files at new locations
- Requires user to reprocess moved files

The implementation will attempt Tier 1 matching first, falling back to Tier 2 for ambiguous cases.

---

## Detailed Implementation Plan

### Phase 1: Database Enhancements

#### 1.1 Add File Fingerprint Index
**File**: `app/database.py`

Add a computed fingerprint column or create a helper function:

```python
def get_file_fingerprint(filename, size_bytes, mtime):
    """Generate a fingerprint for file matching."""
    return f"{filename}|{size_bytes}|{int(mtime)}"
```

Add new database methods:

```python
def get_files_by_source_directory(self, directory_path):
    """Get all files that were imported from a specific directory (including subdirs)."""
    # Query: WHERE metadata->>'source_directory' LIKE ?%

def get_file_by_fingerprint(self, filename, size_bytes, mtime_tolerance=2):
    """Find file by fingerprint (name + size + approx mtime)."""
    # Query: WHERE filename = ? AND size_bytes = ?
    #        AND ABS(json_extract(metadata, '$.file_mtime') - ?) < tolerance

def update_file_local_path(self, file_id, new_local_path, new_source_directory):
    """Update file path without touching related records."""
    # UPDATE files SET local_path = ?,
    #        metadata = json_set(metadata, '$.source_directory', ?)
    # WHERE id = ?

def get_all_local_files(self):
    """Get all files with local_path set (imported files only)."""
    # Query: WHERE local_path IS NOT NULL

def bulk_delete_files_by_ids(self, file_ids):
    """Delete multiple files by ID (cascades to related tables)."""
    # DELETE FROM files WHERE id IN (?)
```

#### 1.2 Add Rescan Tracking Table (Optional Enhancement)
**File**: `app/database.py`

```sql
CREATE TABLE IF NOT EXISTS rescan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    directory_path TEXT NOT NULL,
    scan_started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    scan_completed_at TIMESTAMP,
    files_scanned INTEGER DEFAULT 0,
    files_matched INTEGER DEFAULT 0,
    files_moved INTEGER DEFAULT 0,
    files_deleted INTEGER DEFAULT 0,
    files_added INTEGER DEFAULT 0,
    status TEXT DEFAULT 'in_progress',
    error_message TEXT
)
```

---

### Phase 2: Rescan Service

#### 2.1 Create Rescan Service
**File**: `app/services/rescan_service.py` (NEW)

```python
class RescanService:
    """Service for rescanning directories and reconciling file changes."""

    def __init__(self, db):
        self.db = db

    def scan_directory(self, directory_path, recursive=True):
        """
        Scan directory and return list of discovered files with fingerprints.

        Returns: [
            {
                'path': '/full/path/to/file.mp4',
                'filename': 'file.mp4',
                'size_bytes': 123456,
                'mtime': 1703456789.0,
                'fingerprint': 'file.mp4|123456|1703456789'
            },
            ...
        ]
        """

    def get_database_files_for_directory(self, directory_path):
        """
        Get all database files that were originally imported from this directory.

        Returns: [
            {
                'id': 1,
                'local_path': '/old/path/to/file.mp4',
                'filename': 'file.mp4',
                'size_bytes': 123456,
                'mtime': 1703456789.0,
                'fingerprint': 'file.mp4|123456|1703456789',
                'has_proxy': True,
                'has_analysis': True,
                'has_transcripts': True
            },
            ...
        ]
        """

    def reconcile(self, directory_path, mode='smart'):
        """
        Main reconciliation logic.

        Args:
            directory_path: Directory to rescan
            mode: 'smart' (fingerprint matching) or 'simple' (delete & reimport)

        Returns: {
            'matched': [(db_file, disk_file), ...],      # Same path
            'moved': [(db_file, disk_file), ...],        # Different path, same fingerprint
            'deleted': [db_file, ...],                    # In DB but not on disk
            'new': [disk_file, ...],                      # On disk but not in DB
            'ambiguous': [(db_file, [disk_files]), ...]  # Multiple matches
        }
        """
        disk_files = self.scan_directory(directory_path)
        db_files = self.get_database_files_for_directory(directory_path)

        # Build fingerprint indexes
        disk_by_fingerprint = {}
        disk_by_path = {f['path']: f for f in disk_files}

        for f in disk_files:
            fp = f['fingerprint']
            if fp not in disk_by_fingerprint:
                disk_by_fingerprint[fp] = []
            disk_by_fingerprint[fp].append(f)

        db_by_fingerprint = {}
        db_by_path = {f['local_path']: f for f in db_files}

        for f in db_files:
            fp = f['fingerprint']
            if fp not in db_by_fingerprint:
                db_by_fingerprint[fp] = []
            db_by_fingerprint[fp].append(f)

        results = {
            'matched': [],
            'moved': [],
            'deleted': [],
            'new': [],
            'ambiguous': []
        }

        matched_db_ids = set()
        matched_disk_paths = set()

        # Pass 1: Exact path matches (unchanged files)
        for db_file in db_files:
            if db_file['local_path'] in disk_by_path:
                disk_file = disk_by_path[db_file['local_path']]
                results['matched'].append((db_file, disk_file))
                matched_db_ids.add(db_file['id'])
                matched_disk_paths.add(disk_file['path'])

        # Pass 2: Fingerprint matches (moved files)
        for db_file in db_files:
            if db_file['id'] in matched_db_ids:
                continue

            fp = db_file['fingerprint']
            candidates = [
                f for f in disk_by_fingerprint.get(fp, [])
                if f['path'] not in matched_disk_paths
            ]

            if len(candidates) == 1:
                # Unique match - file was moved
                results['moved'].append((db_file, candidates[0]))
                matched_db_ids.add(db_file['id'])
                matched_disk_paths.add(candidates[0]['path'])
            elif len(candidates) > 1:
                # Multiple candidates - ambiguous
                results['ambiguous'].append((db_file, candidates))
                matched_db_ids.add(db_file['id'])

        # Pass 3: Identify deleted files (in DB, not on disk)
        for db_file in db_files:
            if db_file['id'] not in matched_db_ids:
                results['deleted'].append(db_file)

        # Pass 4: Identify new files (on disk, not in DB)
        for disk_file in disk_files:
            if disk_file['path'] not in matched_disk_paths:
                results['new'].append(disk_file)

        return results

    def apply_changes(self, reconcile_results, options):
        """
        Apply reconciliation changes to database.

        Args:
            reconcile_results: Output from reconcile()
            options: {
                'update_moved': True,       # Update paths for moved files
                'delete_missing': True,     # Delete files not found on disk
                'import_new': True,         # Import new files
                'handle_ambiguous': 'skip'  # 'skip', 'delete', or 'first_match'
            }

        Returns: {
            'updated': int,
            'deleted': int,
            'imported': int,
            'skipped': int,
            'errors': [...]
        }
        """
```

---

### Phase 3: API Endpoints

#### 3.1 Add Rescan Endpoints
**File**: `app/routes/file_management.py`

```python
@file_management.route('/api/files/rescan', methods=['POST'])
def rescan_directory():
    """
    Rescan a directory and return detected changes.

    Request body:
    {
        "directory_path": "/path/to/scan",
        "recursive": true
    }

    Response:
    {
        "success": true,
        "summary": {
            "total_on_disk": 150,
            "total_in_database": 145,
            "matched": 140,
            "moved": 3,
            "deleted": 2,
            "new": 7,
            "ambiguous": 0
        },
        "details": {
            "moved": [
                {
                    "id": 1,
                    "old_path": "/old/folder/video.mp4",
                    "new_path": "/new/folder/video.mp4",
                    "has_proxy": true,
                    "has_analysis": true,
                    "has_transcripts": true
                }
            ],
            "deleted": [
                {
                    "id": 2,
                    "path": "/path/that/no/longer/exists.mp4",
                    "has_proxy": true,
                    "has_analysis": false,
                    "has_transcripts": false
                }
            ],
            "new": [
                {
                    "path": "/new/file.mp4",
                    "size_bytes": 123456,
                    "filename": "file.mp4"
                }
            ],
            "ambiguous": []
        }
    }
    """

@file_management.route('/api/files/rescan/apply', methods=['POST'])
def apply_rescan_changes():
    """
    Apply changes detected by rescan.

    Request body:
    {
        "directory_path": "/path/to/scan",
        "actions": {
            "update_moved": true,
            "delete_missing": true,
            "import_new": true,
            "handle_ambiguous": "skip"
        },
        "selected_files": {
            "moved": [1, 3, 5],       # File IDs to update
            "deleted": [2],            # File IDs to delete
            "new": ["/path/to/new.mp4"] # Paths to import
        }
    }

    Response:
    {
        "success": true,
        "results": {
            "updated": 3,
            "deleted": 1,
            "imported": 1,
            "errors": []
        }
    }
    """
```

---

### Phase 4: Frontend UI

#### 4.1 Rescan Modal/Panel
**File**: `app/templates/file_management.html`

Add a "Rescan Folder" button in the action bar that opens a modal:

```
+--------------------------------------------------+
|  Rescan Directory                           [X]  |
+--------------------------------------------------+
|  Directory: [________________________] [Browse]  |
|                                                  |
|  [ ] Recursive scan                              |
|                                                  |
|  [Scan Now]                                      |
+--------------------------------------------------+
```

#### 4.2 Rescan Results Panel
After scanning, show results:

```
+--------------------------------------------------+
|  Rescan Results                                  |
+--------------------------------------------------+
|  Summary:                                        |
|    Files on disk: 150                            |
|    Files in database: 145                        |
|    Unchanged: 140                                |
|    Moved: 3 (analysis will be preserved)         |
|    Deleted from disk: 2                          |
|    New files: 7                                  |
|                                                  |
+--------------------------------------------------+
|  Moved Files (3)                          [v]    |
|  +----------------------------------------------+|
|  | [x] video1.mp4                               ||
|  |     Old: /videos/2023/January/               ||
|  |     New: /videos/2023-Q1/January/            ||
|  |     Proxy: Yes | Analysis: Yes | Transcript: Yes ||
|  +----------------------------------------------+|
|  | [x] video2.mp4                               ||
|  |     Old: /videos/2023/February/              ||
|  |     New: /videos/2023-Q1/February/           ||
|  +----------------------------------------------+|
+--------------------------------------------------+
|  Deleted from Disk (2)                    [v]    |
|  +----------------------------------------------+|
|  | [x] old_video.mp4                            ||
|  |     Path: /videos/deleted/                   ||
|  |     WARNING: Removing will delete proxy +    ||
|  |              analysis data                   ||
|  +----------------------------------------------+|
+--------------------------------------------------+
|  New Files (7)                            [v]    |
|  +----------------------------------------------+|
|  | [x] new_video1.mp4 (1.2 GB)                  ||
|  | [x] new_video2.mp4 (850 MB)                  ||
|  | ... (5 more)                                 ||
|  +----------------------------------------------+|
+--------------------------------------------------+
|                                                  |
|  [Apply Selected Changes]    [Cancel]            |
+--------------------------------------------------+
```

#### 4.3 JavaScript Functions
**File**: `app/static/js/file_management.js`

```javascript
async function openRescanModal() {
    // Show modal for directory selection
}

async function performRescan(directoryPath, recursive) {
    const response = await fetch('/api/files/rescan', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            directory_path: directoryPath,
            recursive: recursive
        })
    });
    return response.json();
}

async function applyRescanChanges(directoryPath, selectedChanges) {
    const response = await fetch('/api/files/rescan/apply', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            directory_path: directoryPath,
            actions: {
                update_moved: true,
                delete_missing: true,
                import_new: true
            },
            selected_files: selectedChanges
        })
    });
    return response.json();
}

function renderRescanResults(results) {
    // Build UI for moved, deleted, new files
    // Allow user to select which changes to apply
}
```

---

### Phase 5: Edge Cases & Error Handling

#### 5.1 Ambiguous Matches
When multiple database files match one disk file (or vice versa):
- Flag as "ambiguous" in results
- Show all candidates to user
- Options: Skip, Delete all matches, Use first match

#### 5.2 Proxy Files
- Proxies have `source_file_id` linking to source
- When source moves, proxy path may need updating too
- When source is deleted, proxy is automatically deleted (CASCADE)

#### 5.3 Permission Errors
- Handle inaccessible directories gracefully
- Log and report files that couldn't be read
- Continue processing accessible files

#### 5.4 Large Directories
- Add progress reporting for directories with many files
- Consider pagination for results
- Batch database updates (100 files per transaction)

#### 5.5 Concurrent Modifications
- Lock or warn if files are currently being processed
- Check for active analysis jobs before deletion

---

## Implementation Order

### Week 1: Foundation
1. [ ] Add database helper methods (`database.py`)
2. [ ] Create `RescanService` class
3. [ ] Implement `scan_directory()` method
4. [ ] Implement `reconcile()` method (smart matching)

### Week 2: API & Testing
5. [ ] Add `/api/files/rescan` endpoint
6. [ ] Add `/api/files/rescan/apply` endpoint
7. [ ] Implement `apply_changes()` method
8. [ ] Write unit tests for fingerprint matching
9. [ ] Test with renamed folder scenarios

### Week 3: Frontend
10. [ ] Add "Rescan Folder" button to file management UI
11. [ ] Create rescan modal with directory input
12. [ ] Build results display component
13. [ ] Implement selection and apply functionality

### Week 4: Polish & Edge Cases
14. [ ] Add progress indicators for large scans
15. [ ] Handle ambiguous match UI
16. [ ] Add rescan history tracking (optional)
17. [ ] Performance testing with 1000+ files
18. [ ] Documentation and user guide

---

## Alternative: Simple Mode Implementation

If the smart fingerprint matching proves too complex, a simpler approach:

### Simple Rescan Flow
1. User selects directory to rescan
2. System identifies all DB files from that directory
3. For each DB file:
   - If file exists at `local_path`: Keep
   - If file doesn't exist: Mark for deletion
4. Scan directory for all video/image files
5. For each disk file:
   - If not in DB: Mark for import
6. Apply: Delete missing, import new
7. User must reprocess any files that were in renamed folders

### Pros
- Much simpler implementation
- No ambiguity issues
- Predictable behavior

### Cons
- Loses all analysis data for files in renamed folders
- User must rerun proxies, transcriptions, analysis

---

## File Changes Summary

| File | Changes |
|------|---------|
| `app/database.py` | Add fingerprint methods, bulk operations |
| `app/services/rescan_service.py` | NEW - Core rescan logic |
| `app/routes/file_management.py` | Add rescan endpoints |
| `app/templates/file_management.html` | Add rescan modal/UI |
| `app/static/js/file_management.js` | Add rescan functions |

---

## Testing Scenarios

1. **Basic Rename**: Rename single folder, verify files are matched and paths updated
2. **Nested Rename**: Rename parent folder affecting multiple subdirectories
3. **Deleted Files**: Remove files from disk, verify DB cleanup
4. **New Files**: Add files to existing directory, verify import
5. **Mixed Changes**: Combination of moved, deleted, and new files
6. **Duplicate Filenames**: Same filename in different folders
7. **Large Directory**: 1000+ files performance test
8. **Proxy Handling**: Verify proxies are updated with source files
9. **Analysis Preservation**: Confirm analysis jobs remain linked after path update

---

## Success Criteria

1. Files in renamed folders are matched by fingerprint with >95% accuracy
2. Path updates preserve all existing analysis data (proxies, transcripts, nova jobs)
3. Truly deleted files are cleanly removed with cascade cleanup
4. New files are imported and ready for processing
5. UI clearly shows impact of changes before applying
6. Performance: <5 seconds for directories with 500 files
