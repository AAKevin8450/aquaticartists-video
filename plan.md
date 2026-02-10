# Batch Processing Background Poller Implementation Plan

## Problem Statement

Currently, batch results are only fetched when individual job status is polled via the frontend. This creates several issues:
- Jobs can complete undetected if no one polls them
- Results sit unfetched in S3 indefinitely
- S3 proxy files accumulate, increasing storage costs
- No automatic cleanup trigger after successful completion

## Goals

1. **Automatic polling**: Background task continuously checks pending Bedrock batch jobs
2. **Automatic result fetching**: When a job completes, immediately fetch and store results
3. **Automatic cleanup**: After successful result loading, delete the S3 proxy files and batch folders
4. **Resilience**: Handle app restarts, failures, and edge cases gracefully

---

## Phase 1: Background Poller Service

### 1.1 Create New Service File

**File**: `app/services/batch_poller_service.py`

**Purpose**: Background service that polls pending Bedrock batch jobs and processes completed ones.

**Key Components**:

```python
class BatchPollerService:
    """Background service for polling Bedrock batch jobs."""

    def __init__(self, app):
        self.app = app
        self.running = False
        self.thread = None
        self.poll_interval = 60  # seconds between poll cycles
        self.batch_check_interval = 30  # seconds between checking same batch

    def start(self):
        """Start the background poller thread."""

    def stop(self):
        """Stop the background poller gracefully."""

    def _poll_loop(self):
        """Main polling loop - runs in background thread."""

    def _get_pending_batch_jobs(self) -> List[dict]:
        """Query database for jobs needing status check."""

    def _check_and_process_job(self, batch_job: dict) -> bool:
        """Check single job status, fetch results if complete."""

    def _fetch_and_store_results(self, batch_job: dict) -> bool:
        """Fetch results from S3 and update database."""

    def _cleanup_batch_files(self, batch_job: dict) -> bool:
        """Delete S3 proxy files after successful result storage."""
```

### 1.2 Polling Logic

**Query for pending jobs**:
```sql
SELECT * FROM bedrock_batch_jobs
WHERE status IN ('SUBMITTED', 'IN_PROGRESS')
  AND (last_checked_at IS NULL
       OR last_checked_at < datetime('now', '-30 seconds'))
ORDER BY submitted_at ASC
```

**Status check flow**:
1. Call Bedrock `describe_model_invocation_job()` API
2. Map Bedrock status to internal status:
   - `Submitted` / `Validating` / `Scheduled` → `IN_PROGRESS`
   - `InProgress` → `IN_PROGRESS`
   - `Completed` → Trigger result fetching
   - `Failed` / `Stopped` / `Expired` → Mark as `FAILED`
3. Update `last_checked_at` timestamp
4. If completed, proceed to result fetching

### 1.3 Integration with Flask App

**File**: `app/__init__.py` (or new `app/background.py`)

**Startup**:
```python
from app.services.batch_poller_service import BatchPollerService

batch_poller = None

def create_app():
    app = Flask(__name__)
    # ... existing setup ...

    # Start background poller (only in main process, not reloader)
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        global batch_poller
        batch_poller = BatchPollerService(app)
        batch_poller.start()

        # Register shutdown handler
        import atexit
        atexit.register(batch_poller.stop)

    return app
```

---

## Phase 2: Automatic Result Fetching

### 2.1 Reuse Existing Result Fetching Logic

**Location**: `app/services/nova_service.py:679-925` (`fetch_batch_results()`)

The existing `fetch_batch_results()` function is well-implemented and handles:
- Reading `.jsonl.out` files from S3
- Parsing batch output records
- Extracting token usage and costs
- Handling combined analysis responses

**Integration**: Call this from the poller service when a job completes.

### 2.2 Result Processing Flow

```
Job Status = COMPLETED
    ↓
Fetch nova_job_ids from bedrock_batch_jobs
    ↓
For each nova_job_id:
    ├─ Call fetch_batch_results(file_id, nova_job_id, ...)
    ├─ Parse .jsonl.out from output_s3_prefix
    ├─ Update nova_jobs with results
    ├─ Compile results for analysis_jobs
    └─ Update analysis_jobs.status = 'COMPLETED'
    ↓
Mark bedrock_batch_jobs.status = 'COMPLETED'
Mark bedrock_batch_jobs.completed_at = NOW
```

### 2.3 Error Handling

**Retry logic** (consistent with existing implementation):
- Max 3 retries with exponential backoff (2s, 4s, 8s)
- If all retries fail, mark status as `RESULT_FETCH_FAILED`
- Log detailed error for debugging
- Do NOT proceed to cleanup on failure

**Partial failure handling**:
- Track which nova_jobs succeeded vs failed
- Only proceed to cleanup if ALL jobs in batch succeeded
- Store error details in database for debugging

---

## Phase 3: Automatic S3 Cleanup

### 3.1 Cleanup Trigger

**When to cleanup**: After ALL conditions are met:
1. Bedrock job status = `COMPLETED`
2. All nova_jobs in batch have results fetched successfully
3. All analysis_jobs updated with compiled results
4. No `RESULT_FETCH_FAILED` status in linked jobs

### 3.2 Cleanup Implementation

**Reuse existing service**: `app/services/batch_cleanup_service.py`

The existing `BatchS3Manager.cleanup_batch_folder()` handles:
- Deleting input folder: `nova_batch/job_{timestamp}_{index}/`
- Deleting output folder: `nova/batch/output/nova_batch/job_{timestamp}_{index}/`
- Tracking bytes freed

**Integration in poller**:
```python
def _cleanup_batch_files(self, batch_job: dict) -> bool:
    """Delete S3 batch files after successful result storage."""
    s3_folder = batch_job['s3_folder']
    output_prefix = batch_job['output_s3_prefix']

    # Use existing cleanup function
    from app.services.batch_s3_manager import BatchS3Manager
    manager = BatchS3Manager(s3_service)

    # Cleanup input folder (proxy files + manifest)
    input_result = manager.cleanup_batch_folder(s3_folder)

    # Cleanup output folder (Bedrock results)
    output_result = manager.cleanup_batch_folder(output_prefix)

    # Mark cleanup complete in database
    db.mark_bedrock_batch_cleanup_completed(batch_job['batch_job_arn'])

    return True
```

### 3.3 Cleanup Tracking

**Database update**: Set `cleanup_completed_at = NOW` after successful cleanup

**Query for reporting**:
```sql
SELECT
    COUNT(*) as completed_jobs,
    SUM(CASE WHEN cleanup_completed_at IS NOT NULL THEN 1 ELSE 0 END) as cleaned_jobs
FROM bedrock_batch_jobs
WHERE status = 'COMPLETED'
```

---

## Phase 4: Database Schema Additions

### 4.1 New Fields for Tracking

**Table**: `bedrock_batch_jobs`

Add columns:
```sql
ALTER TABLE bedrock_batch_jobs ADD COLUMN
    results_fetched_at TIMESTAMP;  -- When results were successfully fetched

ALTER TABLE bedrock_batch_jobs ADD COLUMN
    results_fetch_attempts INTEGER DEFAULT 0;  -- Retry counter

ALTER TABLE bedrock_batch_jobs ADD COLUMN
    last_error TEXT;  -- Store error message for debugging
```

### 4.2 New Database Methods

**File**: `app/database/batch_jobs.py`

Add methods:
```python
def get_pending_batch_jobs_for_polling(self, check_interval_seconds: int = 30) -> List[dict]:
    """Get batch jobs that need status checking."""

def mark_results_fetched(self, batch_job_arn: str):
    """Mark that results have been successfully fetched."""

def increment_fetch_attempts(self, batch_job_arn: str, error: str = None):
    """Increment retry counter and store error."""

def get_batch_jobs_pending_cleanup(self) -> List[dict]:
    """Get completed jobs that haven't been cleaned up."""
```

---

## Phase 5: Configuration & Controls

### 5.1 Environment Variables

Add to `.env`:
```bash
# Batch poller configuration
BATCH_POLLER_ENABLED=true           # Enable/disable background poller
BATCH_POLLER_INTERVAL=60            # Seconds between poll cycles
BATCH_CHECK_INTERVAL=30             # Seconds before rechecking same job
BATCH_AUTO_CLEANUP=true             # Enable automatic S3 cleanup
BATCH_RESULT_FETCH_MAX_RETRIES=3    # Max retries for result fetching
```

### 5.2 Admin API Endpoints

**File**: `app/routes/nova_analysis.py` or new `app/routes/batch_admin.py`

Add endpoints:
```python
@bp.route('/api/batch/poller/status', methods=['GET'])
def get_poller_status():
    """Get background poller status and stats."""

@bp.route('/api/batch/poller/start', methods=['POST'])
def start_poller():
    """Manually start the poller."""

@bp.route('/api/batch/poller/stop', methods=['POST'])
def stop_poller():
    """Manually stop the poller."""

@bp.route('/api/batch/process-completed', methods=['POST'])
def process_completed_batches():
    """Manually trigger processing of completed batches."""
```

### 5.3 Logging

Add comprehensive logging:
```python
logger = logging.getLogger('batch_poller')

# Log levels:
# INFO: Job status changes, successful completions
# WARNING: Retry attempts, partial failures
# ERROR: Failed jobs, cleanup errors
# DEBUG: Poll cycle details, API calls
```

---

## Phase 6: UI Updates

### 6.1 Reports Page Enhancement

**File**: `app/templates/reports.html`, `app/static/js/reports.js`

Add "Batch Poller Status" section:
- Current poller status (running/stopped)
- Jobs pending processing
- Jobs completed today
- Last poll timestamp
- Start/Stop buttons (admin only)

### 6.2 Batch Status Indicators

Update batch job display to show:
- Auto-processing indicator (poller will handle)
- Cleanup status (pending/completed)
- Last checked timestamp

---

## Phase 7: Edge Cases & Error Handling

### 7.1 App Restart Recovery

**On startup**:
1. Query for jobs with status `IN_PROGRESS` or `SUBMITTED`
2. These are either:
   - Still running in Bedrock (continue polling)
   - Completed while app was down (fetch results)
   - Failed while app was down (mark as failed)
3. Check each job's Bedrock status immediately
4. Resume normal polling

### 7.2 Bedrock API Errors

**Transient errors** (retry):
- `ThrottlingException`
- `ServiceUnavailableException`
- Network timeouts

**Permanent errors** (fail job):
- `ResourceNotFoundException` (job doesn't exist)
- `AccessDeniedException` (permissions issue)
- `ValidationException` (invalid parameters)

### 7.3 S3 Cleanup Failures

**If cleanup fails**:
- Log error but don't fail the job
- Leave `cleanup_completed_at` as NULL
- Can retry via manual cleanup endpoint
- Doesn't affect job completion status

### 7.4 Concurrent Access

**Thread safety**:
- Use database transactions for status updates
- Check status before processing (avoid race conditions)
- Use `SELECT ... FOR UPDATE` pattern where needed

---

## Implementation Order

### Step 1: Database Schema (1 task)
- Add new columns to `bedrock_batch_jobs`
- Add new database methods

### Step 2: Poller Service Core (3 tasks)
- Create `BatchPollerService` class
- Implement `_get_pending_batch_jobs()`
- Implement `_check_and_process_job()`

### Step 3: Result Fetching Integration (2 tasks)
- Implement `_fetch_and_store_results()`
- Add retry logic and error handling

### Step 4: Cleanup Integration (2 tasks)
- Implement `_cleanup_batch_files()`
- Add cleanup tracking

### Step 5: Flask Integration (2 tasks)
- Add startup/shutdown hooks
- Add environment variable configuration

### Step 6: Admin API (2 tasks)
- Add poller status endpoint
- Add manual trigger endpoints

### Step 7: UI Updates (2 tasks)
- Add poller status to reports page
- Add batch status indicators

### Step 8: Testing & Documentation (2 tasks)
- Test with real batch jobs
- Update CLAUDE.md with new architecture

---

## File Changes Summary

| File | Changes |
|------|---------|
| `app/services/batch_poller_service.py` | **NEW** - Background poller service |
| `app/database/batch_jobs.py` | Add new methods for polling queries |
| `app/__init__.py` | Add poller startup/shutdown |
| `app/routes/nova_analysis.py` | Add admin endpoints |
| `app/templates/reports.html` | Add poller status section |
| `app/static/js/reports.js` | Add poller status UI logic |
| `CLAUDE.md` | Document new architecture |
| `.env.example` | Add poller configuration variables |

---

## Success Criteria

1. **Automatic polling**: Background thread checks pending jobs every 60s
2. **Automatic results**: Completed jobs have results fetched within 2 minutes
3. **Automatic cleanup**: S3 files deleted within 5 minutes of successful completion
4. **Zero data loss**: Results properly stored even if app restarts
5. **Visibility**: Admin can monitor poller status via API/UI
6. **Graceful shutdown**: Poller stops cleanly on app shutdown
7. **Error recovery**: Failed fetches retry automatically with backoff
