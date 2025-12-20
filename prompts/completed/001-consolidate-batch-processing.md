<objective>
Eliminate code duplication by refactoring individual and batch processing functions to use shared common logic. Currently, individual file processing and batch processing have separate implementations that duplicate logic, making the codebase harder to maintain and more prone to bugs. This refactoring will create a single source of truth for each processing task, ensuring consistency and reducing maintenance burden.
</objective>

<context>
This Flask application provides video/image analysis using AWS services (Rekognition, Bedrock Nova) and local transcription (faster-whisper). Currently, there are parallel implementations for:

1. **Nova Analysis** (app/services/nova_service.py, app/routes/nova_analysis.py)
   - Individual: Single video analysis
   - Batch: Multiple videos processed together

2. **Transcription** (app/services/transcription_service.py, app/routes/transcription.py)
   - Individual: Single file transcription
   - Batch: Directory scanning and batch processing

3. **Rekognition** (app/services/rekognition_video.py, app/services/rekognition_image.py)
   - Individual: Single video/image analysis
   - Batch: Multiple files processed together

The duplication causes:
- Inconsistent error handling between individual and batch modes
- Bug fixes applied to one path but not the other
- Difficulty maintaining feature parity
- Increased testing surface area

Read CLAUDE.md for project architecture, conventions, and development guidelines.
</context>

<requirements>
1. **Analyze existing code patterns**: Carefully examine all individual and batch processing functions across Nova, transcription, and Rekognition services
2. **Identify common logic**: Extract shared processing logic that appears in both individual and batch implementations
3. **Create core processing functions**: Design single-responsibility functions that handle the actual processing work
4. **Refactor callers**: Update both individual and batch functions to call the new common functions
5. **Maintain API compatibility**: Ensure existing API endpoints continue to work without changes
6. **Preserve error handling**: Keep existing error handling behavior or improve it consistently
7. **Update tests**: Ensure any existing tests still pass after refactoring

Focus areas (in priority order):
- Nova analysis processing (most complex, highest value)
- Transcription processing (second priority)
- Rekognition processing (if time permits)
</requirements>

<implementation>
**Step 1: Audit Current Implementation**

Thoroughly analyze the following files to understand the duplication:
- @app/services/nova_service.py
- @app/routes/nova_analysis.py
- @app/services/transcription_service.py
- @app/routes/transcription.py
- @app/services/rekognition_video.py
- @app/services/rekognition_image.py

For each service, identify:
- What logic is duplicated between individual and batch functions?
- What parameters differ between individual and batch processing?
- How are results aggregated in batch mode?
- How do error handling strategies differ?

**Step 2: Design Common Processing Functions**

Create core processing functions following this pattern:

```python
def _process_single_item(item_path, processing_params, **kwargs):
    """
    Core processing function that handles a single item.

    This function contains the actual processing logic and is called by both
    individual and batch processing functions.

    Args:
        item_path: Path to the item being processed
        processing_params: Processing configuration (model, options, etc.)
        **kwargs: Additional processing-specific parameters

    Returns:
        dict: Processing result with status, data, and any errors

    Raises:
        ProcessingError: If processing fails critically
    """
    # Core processing logic here
    pass

def process_individual(item_path, processing_params):
    """Individual processing wrapper - calls _process_single_item"""
    return _process_single_item(item_path, processing_params)

def process_batch(item_paths, processing_params, progress_callback=None):
    """
    Batch processing wrapper - iterates items and calls _process_single_item

    Args:
        item_paths: List of paths to process
        processing_params: Shared processing configuration
        progress_callback: Optional callback for progress updates

    Returns:
        dict: Batch results with success/failure counts and individual results
    """
    results = []
    for i, item_path in enumerate(item_paths):
        try:
            result = _process_single_item(item_path, processing_params)
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, len(item_paths), result)
        except Exception as e:
            # Handle errors consistently
            results.append({"path": item_path, "status": "error", "error": str(e)})

    return {
        "total": len(item_paths),
        "successful": sum(1 for r in results if r.get("status") == "success"),
        "failed": sum(1 for r in results if r.get("status") == "error"),
        "results": results
    }
```

**Step 3: Refactor Service Files**

For each service (Nova, transcription, Rekognition):

1. Create the `_process_single_item()` function with core logic
2. Extract common validation, parameter parsing, and result formatting
3. Update individual processing functions to call the core function
4. Update batch processing functions to iterate and call the core function
5. Ensure error handling is consistent across both paths

**What to extract into common functions:**
- File validation and metadata extraction
- AWS service client initialization
- Parameter normalization and validation
- Result parsing and formatting
- Database operations (save results, update status)
- S3 operations (upload/download if needed)

**What to keep separate:**
- Batch-specific progress tracking and callbacks
- Batch result aggregation logic
- API endpoint parameter parsing (routes layer)

**Why this matters:**
- Single source of truth means bugs only need fixing once
- Consistent behavior between individual and batch modes
- Easier to add new features (add once, works everywhere)
- Reduced testing burden (test core function thoroughly)

**Step 4: Update Route Handlers**

Ensure API endpoints in routes files continue to work:
- Routes should remain thin, only handling HTTP concerns
- Move business logic from routes into service layer
- Keep endpoint signatures and response formats unchanged

**Step 5: Add Inline Documentation**

Add clear docstrings explaining:
- Why the function exists (single source of truth)
- What it does (core processing logic)
- How it's used (called by both individual and batch)
- Parameters and return values

</implementation>

<verification>
Before declaring complete, verify your refactoring:

1. **Code Review Checklist:**
   - [ ] All individual processing functions call common core functions
   - [ ] All batch processing functions call the same common core functions
   - [ ] No logic duplication remains between individual and batch paths
   - [ ] Error handling is consistent across both paths
   - [ ] Database operations use shared functions

2. **Functional Testing:**
   - [ ] Test individual Nova analysis - should work as before
   - [ ] Test batch Nova analysis - should work as before
   - [ ] Test individual transcription - should work as before
   - [ ] Test batch transcription - should work as before
   - [ ] Test error cases in both individual and batch modes

3. **API Compatibility:**
   - [ ] All existing API endpoints still return expected response formats
   - [ ] Error responses match previous behavior
   - [ ] Progress callbacks work in batch mode

4. **Code Quality:**
   - [ ] No commented-out code left behind
   - [ ] Clear docstrings on all new common functions
   - [ ] Consistent naming conventions followed
   - [ ] No backwards-compatibility hacks (see CLAUDE.md guidelines)

If you find any issues during verification, fix them before declaring complete.
</verification>

<output>
Modify the following files with refactored code:
- `./app/services/nova_service.py` - Consolidate Nova processing
- `./app/routes/nova_analysis.py` - Update to use common functions
- `./app/services/transcription_service.py` - Consolidate transcription processing
- `./app/routes/transcription.py` - Update to use common functions
- `./app/services/rekognition_video.py` - Consolidate Rekognition video processing (if applicable)
- `./app/services/rekognition_image.py` - Consolidate Rekognition image processing (if applicable)

Do NOT create new files unless absolutely necessary - prefer editing existing files per CLAUDE.md guidelines.
</output>

<success_criteria>
Success means:
1. ✓ Zero code duplication between individual and batch processing paths
2. ✓ All processing logic consolidated into single core functions
3. ✓ Both individual and batch API endpoints work correctly
4. ✓ Error handling is consistent across all processing modes
5. ✓ Existing tests pass (if any exist)
6. ✓ Code is more maintainable with clear separation of concerns
7. ✓ No functional regressions - everything works as before, just better organized
</success_criteria>
