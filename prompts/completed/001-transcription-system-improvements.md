<objective>
Thoroughly redesign and improve the transcription system with the following major changes:
1. Multi-model transcript storage - Allow same video to have transcripts from different Whisper models
2. Clean database schema - Delete existing database, create fresh schema with only necessary fields
3. Improved batch progress UI - Solid progress bar when complete, enhanced statistics display
4. Searchable/filterable transcripts list - Add filtering and search capabilities

This is a substantial refactoring task. Use a detailed todo list to track all changes systematically.
</objective>

<context>
This is a Flask-based video analysis application with local transcription using faster-whisper.

Key files to examine:
@app/database.py - Database schema and CRUD operations
@app/services/transcription_service.py - Transcription service logic
@app/routes/transcription.py - API endpoints
@app/templates/transcription.html - Frontend UI

Current setup:
- SQLite database at data/app.db
- Single transcript per video (identified by file path + size + modified time)
- Basic progress bar during batch processing
- Simple transcript list without search/filter
</context>

<requirements>
## Database Schema Redesign

### Multi-Model Support
- Change unique constraint from (file_path, file_size, modified_time) to include model_name
- Allow storing multiple transcripts for the same video file when processed with different models
- New unique constraint: (file_path, file_size, modified_time, model_name)

### Clean Schema Fields (ONLY include these - remove any legacy fields):
```
id: INTEGER PRIMARY KEY
file_path: TEXT NOT NULL
file_name: TEXT NOT NULL (extracted from path for display/search)
file_size: INTEGER NOT NULL
modified_time: REAL NOT NULL
model_name: TEXT NOT NULL (tiny, base, small, medium, large-v2, large-v3)
language: TEXT (detected or specified language code)
transcript_text: TEXT (full transcript)
segments: TEXT (JSON array of segments with timestamps)
word_timestamps: TEXT (JSON array of word-level timestamps if available)
confidence_score: REAL (average confidence)
processing_time: REAL (seconds to process)
status: TEXT NOT NULL (PENDING, IN_PROGRESS, COMPLETED, FAILED)
error_message: TEXT (if FAILED)
created_at: TEXT NOT NULL (ISO timestamp)
completed_at: TEXT (ISO timestamp when finished)
```

### Database Migration
- Delete existing data/app.db file completely
- Create fresh database with new schema
- Update all database functions to match new schema

## Progress Bar Improvements

### Solid Bar When Complete
- When batch processing reaches 100%, change progress bar style to solid (not striped/animated)
- Remove Bootstrap animation classes when complete
- Use bg-success for completed state

### Enhanced Statistics Display
Add a statistics card/section showing:
1. **Average Video Size**: Calculate from processed videos (display in human-readable format: MB/GB)
2. **Average Processing Time**: Average time per video in seconds/minutes
3. **Estimated Time Remaining**: (average_time_per_video * remaining_count) - display as "X min Y sec" or "X hr Y min"
4. **Videos Processed**: X of Y completed
5. **Success Rate**: Percentage of successful transcriptions in current batch

Statistics should update in real-time as batch progresses.

## Transcript List Improvements

### Search Functionality
- Add search input field above transcript list
- Search across: file_name, file_path, transcript_text
- Debounced search (300ms delay) to avoid excessive API calls
- Clear search button

### Filter Options
- Filter by model_name (dropdown with all available models)
- Filter by status (dropdown: All, Completed, Failed, Pending)
- Filter by language (dropdown populated from existing transcripts)
- Date range filter (from/to date pickers)
- Combine filters with AND logic

### Enhanced List Display
- Show model_name badge for each transcript
- Show file_name prominently (instead of full path)
- Truncate long paths with tooltip showing full path
- Sort options: Date (newest/oldest), File name (A-Z/Z-A), Size, Processing time

### API Changes
Update `/transcription/api/transcripts` endpoint to support:
- `?search=<query>` - Full-text search
- `?model=<model_name>` - Filter by model
- `?status=<status>` - Filter by status
- `?language=<code>` - Filter by language
- `?from_date=<iso_date>` - Filter from date
- `?to_date=<iso_date>` - Filter to date
- `?sort_by=<field>` - Sort field
- `?sort_order=asc|desc` - Sort direction
- `?page=<n>&per_page=<n>` - Pagination (keep existing)
</requirements>

<implementation>
## Step-by-Step Implementation Order

### Phase 1: Database Schema
1. Create new schema in app/database.py with clean fields
2. Add database deletion/recreation function
3. Update all CRUD functions for new schema
4. Test database operations

### Phase 2: Service Layer Updates
1. Update transcription_service.py to use new schema
2. Ensure model_name is properly stored
3. Update deduplication logic to account for model

### Phase 3: API Endpoints
1. Update all transcription routes for new schema
2. Add search/filter parameters to list endpoint
3. Implement efficient SQL queries with filtering

### Phase 4: Frontend UI
1. Update progress bar styling and completion state
2. Add statistics display section
3. Add search input and filter dropdowns
4. Update transcript list rendering
5. Wire up JavaScript event handlers

## Code Quality Guidelines
- Use parameterized SQL queries (prevent SQL injection)
- Add appropriate database indexes for search/filter performance
- Debounce frontend search to avoid excessive requests
- Handle edge cases (empty results, no transcripts yet, etc.)
- Maintain existing functionality while adding new features
</implementation>

<output>
Modify these files:
- `./app/database.py` - New schema, updated CRUD operations
- `./app/services/transcription_service.py` - Service updates for new schema
- `./app/routes/transcription.py` - API endpoint updates with filtering
- `./app/templates/transcription.html` - UI improvements

Delete and recreate:
- `./data/app.db` - Fresh database with new schema
</output>

<verification>
Before declaring complete, verify:
1. Database schema has correct fields and constraints (no legacy fields)
2. Same video can be transcribed with different models (creates separate records)
3. Progress bar becomes solid green at 100% completion
4. Statistics show average size, processing time, and ETA
5. Search filters transcripts by text content
6. Model filter shows only transcripts from selected model
7. Status filter works correctly
8. All existing transcription functionality still works
9. No SQL injection vulnerabilities in search/filter
</verification>

<success_criteria>
- Fresh database with only specified fields
- Multi-model support working (test by transcribing same file with 2 different models)
- Progress bar visual improvement at completion
- Real-time statistics displayed during batch processing
- Functional search across transcript content
- All filter options working and combinable
- Clean, efficient API queries
- Responsive UI updates
</success_criteria>
