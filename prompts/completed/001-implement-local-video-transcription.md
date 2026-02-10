<objective>
Implement a complete local video transcription system for this Flask-based video analysis application. This feature will scan local video files, extract speech as text transcripts using local Python libraries (no cloud APIs), and store transcripts in the SQLite database.

**Why this matters**: The user has ~10TB of videos to process, so efficiency, batch processing, and incremental progress are critical. This must run entirely locally without sending video data to AWS.

**End goal**: A working transcription pipeline that integrates with the existing Flask UI, supports batch processing of local directories, skips already-processed videos by default, and stores searchable transcripts in the database.
</objective>

<context>
**Existing Project Structure**:
- Flask application on port 5700
- SQLite database at `data/app.db` with existing models in `app/models.py` and database operations in `app/database.py`
- Services pattern: `app/services/` contains business logic
- Routes pattern: `app/routes/` contains Flask blueprints
- Templates: `app/templates/` with Bootstrap 5 styling
- Virtual environment: `.venv` (already configured)

**Key Files to Reference**:
@app/models.py - Existing dataclass patterns for File, AnalysisJob
@app/database.py - Database class with connection management and CRUD patterns
@app/services/rekognition_video.py - Example service pattern for async video processing
@app/routes/video_analysis.py - Example route pattern
@app/templates/base.html - Base template with navigation
@app/templates/history.html - Example of job status tracking UI
@CLAUDE.md - Project conventions and architecture details

**Performance Context**:
- 10TB of videos requires efficient processing
- Must support resumable batch operations
- Should utilize GPU acceleration when available
- Need to track progress and support interruption/resumption
</context>

<research>
Before implementing, thoroughly explore and understand:

1. **Existing Patterns**: Read the existing service and route files to match the established code patterns
2. **Database Schema**: Understand the current schema and how to extend it appropriately
3. **UI Patterns**: Review existing templates to maintain consistent styling and UX
4. **Current Dependencies**: Check `requirements.txt` for existing packages
</research>

<technology_selection>
**Speech Recognition Engine - Use faster-whisper (December 2025 SOTA)**:
- `faster-whisper` - CTranslate2-based Whisper implementation, 4x faster than OpenAI Whisper with lower memory usage
- Supports GPU acceleration via CUDA
- Multiple model sizes: tiny, base, small, medium, large-v2, large-v3
- Runs completely offline after model download
- Recommended model: `large-v3` for accuracy, `medium` for balance, `small` for speed

**Audio Extraction**:
- `ffmpeg-python` - Python bindings for FFmpeg (required for audio extraction from video)
- FFmpeg must be installed on the system (document this requirement)

**Efficiency Optimizations**:
- Process audio in chunks to manage memory
- Use batch processing with configurable concurrency
- Implement file hashing to detect duplicate videos
- Store intermediate progress to enable resume after interruption

**Installation Requirements**:
```bash
pip install faster-whisper ffmpeg-python
```

**System Requirements**:
- FFmpeg installed and in PATH
- NVIDIA GPU with CUDA for acceleration (optional but recommended)
- cuDNN installed for GPU support (optional)
</technology_selection>

<requirements>
## Database Schema Extension

Create a new `transcripts` table with the following structure:
```sql
CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,  -- Absolute path to video file
    file_hash TEXT NOT NULL,          -- SHA-256 hash for duplicate detection
    file_size_bytes INTEGER NOT NULL,
    duration_seconds FLOAT,
    language TEXT,                    -- Detected or specified language
    model_used TEXT NOT NULL,         -- Whisper model used (e.g., 'large-v3')
    transcript_text TEXT,             -- Full transcript as plain text
    transcript_segments JSON,         -- Timestamped segments [{start, end, text}]
    word_timestamps JSON,             -- Word-level timestamps if available
    confidence_score FLOAT,           -- Average confidence across segments
    processing_time_seconds FLOAT,    -- How long transcription took
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING, PROCESSING, COMPLETED, FAILED, SKIPPED
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    metadata JSON                     -- Additional metadata (audio channels, sample rate, etc.)
);

CREATE INDEX IF NOT EXISTS idx_transcripts_status ON transcripts(status);
CREATE INDEX IF NOT EXISTS idx_transcripts_file_hash ON transcripts(file_hash);
CREATE INDEX IF NOT EXISTS idx_transcripts_file_path ON transcripts(file_path);
```

## Transcript Model

Create `@dataclass` model following existing patterns in `app/models.py`:
- `Transcript` dataclass with all fields matching the database schema
- Include `to_dict()` and `from_dict()` class methods
- Add constants for status values (PENDING, PROCESSING, COMPLETED, FAILED, SKIPPED)

## Transcription Service

Create `app/services/transcription_service.py` with:

1. **TranscriptionService class**:
   - `__init__(model_name='large-v3', device='auto', compute_type='auto')` - Initialize faster-whisper model
   - `transcribe_file(video_path, language=None, force=False)` - Transcribe single video file
   - `scan_directory(directory_path, extensions=['.mp4', '.mov', '.avi', '.mkv'], recursive=True)` - Find video files
   - `batch_transcribe(directory_path, force=False, max_workers=1, callback=None)` - Process directory of videos
   - `get_file_hash(file_path)` - Calculate SHA-256 hash for duplicate detection
   - `extract_audio(video_path, output_path=None)` - Extract audio using FFmpeg
   - `is_already_transcribed(file_path_or_hash)` - Check if video was already processed
   - `get_transcription_status(file_path)` - Get status of transcription job
   - `cancel_batch_job(job_id)` - Allow cancellation of batch processing

2. **Progress Tracking**:
   - Create `TranscriptionJob` model for tracking batch job progress
   - Store current file being processed, total files, completed count
   - Enable resumption of interrupted batch jobs

3. **Efficiency Features**:
   - Skip files that already have COMPLETED status (unless force=True)
   - Support concurrent processing with configurable worker count
   - Implement memory-efficient chunked processing for large files
   - Cache model in memory to avoid reloading between files

## Flask Routes

Create `app/routes/transcription.py` blueprint with:

1. **API Endpoints**:
   - `GET /api/transcription/scan` - Scan directory and return list of videos with their transcription status
   - `POST /api/transcription/start` - Start batch transcription job
     - Parameters: `directory`, `force_reprocess`, `model_size`, `language`
   - `GET /api/transcription/status/<job_id>` - Get batch job progress
   - `POST /api/transcription/cancel/<job_id>` - Cancel running batch job
   - `GET /api/transcription/transcript/<transcript_id>` - Get single transcript
   - `GET /api/transcription/transcripts` - List all transcripts with pagination
   - `DELETE /api/transcription/transcript/<transcript_id>` - Delete transcript
   - `POST /api/transcription/transcribe-single` - Transcribe a single file immediately

2. **Status Codes**:
   - Return appropriate HTTP status codes (200, 201, 400, 404, 500)
   - Include helpful error messages in JSON responses

## Web UI Template

Create `app/templates/transcription.html` with:

1. **Directory Scanner Section**:
   - Text input for directory path with "Browse" functionality note (manual path entry)
   - Button to scan directory
   - Display list of found videos with status indicators (Pending, Completed, Failed)
   - Checkboxes to select which videos to process
   - "Select All" / "Deselect All" buttons

2. **Transcription Controls**:
   - Model size dropdown (tiny, base, small, medium, large-v2, large-v3)
   - Language selector (auto-detect, or specific language codes)
   - "Force Reprocess" checkbox to override skip behavior
   - "Start Transcription" button

3. **Progress Display**:
   - Overall batch progress bar (X of Y files)
   - Current file name being processed
   - Estimated time remaining
   - Cancel button for running jobs
   - Auto-refresh every 5 seconds while job is running

4. **Results Table**:
   - List of completed transcripts
   - Columns: Filename, Duration, Language, Confidence, Status, Actions
   - View transcript button (opens modal with full text)
   - Download transcript as .txt or .srt (subtitle format)
   - Delete button

5. **Styling**:
   - Match existing Bootstrap 5 styling from other templates
   - Use consistent card layouts, buttons, and color scheme
   - Responsive design for various screen sizes

## Navigation Integration

Update `app/templates/base.html`:
- Add "Transcription" link to the navigation menu
- Place it appropriately among existing navigation items

## Configuration Options

Add to `app/config.py` or environment variables:
- `WHISPER_MODEL_SIZE` - Default model size (default: 'large-v3')
- `WHISPER_DEVICE` - Device to use: 'cuda', 'cpu', or 'auto' (default: 'auto')
- `WHISPER_COMPUTE_TYPE` - Compute type: 'float16', 'int8', etc. (default: 'auto')
- `TRANSCRIPTION_MAX_WORKERS` - Max concurrent transcription workers (default: 1)
- `TRANSCRIPTION_SUPPORTED_EXTENSIONS` - List of supported video extensions

## Error Handling

Implement robust error handling:
- Catch FFmpeg errors (codec issues, corrupt files)
- Handle out-of-memory errors gracefully
- Log all errors with file path and stack trace
- Mark failed files with error message in database
- Don't stop batch processing on single file failure
</requirements>

<implementation_steps>
Follow these steps in order:

1. **Install Dependencies**:
   - Add `faster-whisper` and `ffmpeg-python` to requirements.txt
   - Document FFmpeg system requirement in CLAUDE.md

2. **Extend Database Schema**:
   - Add transcript table creation to `app/database.py` in `_init_db()` method
   - Add transcript CRUD methods following existing patterns

3. **Create Transcript Model**:
   - Add `Transcript` dataclass to `app/models.py`
   - Add status constants

4. **Create Transcription Service**:
   - Create `app/services/transcription_service.py`
   - Implement all methods with proper error handling
   - Add logging for debugging and progress tracking

5. **Create Flask Routes**:
   - Create `app/routes/transcription.py` blueprint
   - Register blueprint in `app/__init__.py`

6. **Create UI Template**:
   - Create `app/templates/transcription.html`
   - Update `app/templates/base.html` navigation

7. **Test End-to-End**:
   - Test with a small video file first
   - Verify database records are created correctly
   - Confirm skip logic works for already-processed files
   - Test force reprocess option
   - Verify progress tracking and cancellation

8. **Update Documentation**:
   - Update CLAUDE.md with new feature documentation
   - Document system requirements (FFmpeg, optional CUDA)
</implementation_steps>

<constraints>
**Critical Requirements**:
- ALL processing must be local - no data sent to AWS or any external APIs
- Must work on Windows (the development environment is Windows)
- FFmpeg path handling must work with Windows paths
- Use existing database patterns - don't introduce new database libraries
- Match existing code style (4-space indentation, type hints, docstrings)

**Performance Requirements**:
- Model should be loaded once and reused across files
- Implement proper cleanup of temporary audio files
- Don't load entire video into memory - use streaming where possible
- Support processing interruption and resumption

**Avoid**:
- Don't use OpenAI's original whisper library (slower than faster-whisper)
- Don't use cloud-based transcription APIs
- Don't create separate databases - use the existing SQLite database
- Don't break existing functionality
</constraints>

<output>
Files to create or modify:

**New Files**:
- `app/services/transcription_service.py` - Core transcription logic
- `app/routes/transcription.py` - Flask blueprint with API endpoints
- `app/templates/transcription.html` - Web UI for transcription feature

**Modified Files**:
- `app/models.py` - Add Transcript dataclass
- `app/database.py` - Add transcripts table and CRUD methods
- `app/templates/base.html` - Add navigation link
- `app/__init__.py` - Register transcription blueprint
- `requirements.txt` - Add new dependencies
- `CLAUDE.md` - Document new feature and requirements
</output>

<verification>
Before declaring the implementation complete, verify:

1. **Dependencies**:
   - [ ] faster-whisper and ffmpeg-python are in requirements.txt
   - [ ] Can import both packages without errors

2. **Database**:
   - [ ] Transcripts table is created on app startup
   - [ ] Can create, read, update, delete transcript records

3. **Service**:
   - [ ] Can extract audio from a test video file
   - [ ] Can transcribe audio and get text output
   - [ ] Skip logic works for already-processed files
   - [ ] Force reprocess overrides skip behavior

4. **API**:
   - [ ] All endpoints return appropriate JSON responses
   - [ ] Error responses include helpful messages

5. **UI**:
   - [ ] Transcription page loads without errors
   - [ ] Navigation link appears in header
   - [ ] Can scan a directory and see video list
   - [ ] Progress updates display correctly

6. **Integration**:
   - [ ] App starts without errors after changes
   - [ ] Existing functionality still works
</verification>

<success_criteria>
The implementation is successful when:

1. A user can navigate to the Transcription page from the main navigation
2. The user can enter a directory path and scan for video files
3. Found videos display with their current transcription status
4. The user can select videos and start batch transcription
5. Progress is displayed in real-time during processing
6. Completed transcripts are stored in the database with timestamps
7. Already-transcribed videos are skipped by default
8. The "Force Reprocess" option re-transcribes existing videos
9. Users can view, download, and delete transcripts
10. The application handles errors gracefully without crashing
11. Processing can be cancelled mid-batch
12. All operations work entirely offline without AWS/cloud dependencies
</success_criteria>
