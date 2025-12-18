<objective>
Enable users to select and run multiple analysis types simultaneously on video and image files, instead of being limited to only one analysis type at a time. This improves efficiency by allowing users to request only the specific analyses they need in a single submission, rather than running all analyses or submitting multiple separate jobs.
</objective>

<context>
This is an AWS Video & Image Analysis application using Flask, Amazon Rekognition, and S3. Currently, both video_analysis.html and image_analysis.html use radio buttons that only allow selecting ONE analysis type. Users have requested the ability to select multiple analysis types (e.g., label_detection + face_detection + text_detection) in a single submission to avoid the overhead of running all 8 analysis types when they only need 2-3 specific ones.

Current implementation:
- Video analysis: 8 analysis types (label_detection, face_detection, celebrity_recognition, content_moderation, text_detection, person_tracking, face_search, shot_segmentation)
- Image analysis: 8 analysis types (label_detection, face_detection, celebrity_recognition, content_moderation, text_detection, ppe_detection, face_search, face_comparison)
- Radio buttons currently enforce single selection only

Review these files to understand the current implementation:
- @app/templates/video_analysis.html (lines 45-125: radio button implementation)
- @app/templates/image_analysis.html (lines 45-124: radio button implementation)
- @app/routes/analysis.py (API endpoints for starting analyses)
</context>

<requirements>
1. **Frontend Changes:**
   - Replace radio buttons with checkboxes for analysis type selection
   - Allow users to select 1 or more analysis types (minimum 1 required)
   - Add "Select All" / "Deselect All" convenience buttons
   - Update validation to ensure at least one analysis type is selected
   - Maintain the conditional display logic (e.g., show collection selector when face_search is selected)

2. **Backend Changes:**
   - Modify API endpoints to accept an array of analysis types instead of a single string
   - Create separate analysis jobs for each selected analysis type
   - Return an array of job IDs for video analysis
   - Return aggregated results for image analysis (since it's synchronous)
   - Handle errors gracefully (if one analysis fails, others should still proceed)

3. **UX Improvements:**
   - Display clear feedback showing how many analysis types are queued
   - For video: redirect to history page with indication of multiple jobs submitted
   - For image: display results organized by analysis type
   - Update info cards to explain multi-select capability

4. **Maintain Existing Functionality:**
   - Special handling for face_search (requires collection_id)
   - Special handling for face_comparison (requires target_file_id)
   - Validation for required parameters based on selected analysis types
</requirements>

<implementation>
**Frontend approach:**
1. Change `<input type="radio">` to `<input type="checkbox">` in both templates
2. Update JavaScript to collect all checked analysis types into an array
3. Add helper buttons for Select All / Deselect All
4. Enhance validation to check for at least one selection
5. Update the payload sent to backend from single `analysis_type` to `analysis_types` array

**Backend approach:**
1. Update `/api/analysis/video/start` to accept `analysis_types` (array) instead of `analysis_type` (string)
2. Loop through each analysis type and create a separate job using existing service methods
3. Update `/api/analysis/image/analyze` similarly for images
4. Return structured response with job IDs or aggregated results

**Why checkboxes matter:** Radio buttons enforce mutually-exclusive selection by design, while checkboxes allow multi-select. This fundamental UI pattern change directly enables the desired functionality.

**Why separate jobs for video:** Amazon Rekognition's video analysis API requires starting individual jobs for each analysis type, so creating separate jobs aligns with the AWS service architecture.

**Avoid these patterns:**
- Don't try to batch multiple video analysis types into a single Rekognition job (API doesn't support this)
- Don't remove the single-select validation entirely (must require at least 1 selection)
- Don't break the existing conditional logic for face_search and face_comparison
</implementation>

<output>
Modify these existing files (DO NOT create new files):
- `./app/templates/video_analysis.html` - Convert radio buttons to checkboxes, add Select All/Deselect All buttons
- `./app/templates/image_analysis.html` - Same checkbox conversion
- `./app/routes/analysis.py` - Update API endpoints to handle arrays of analysis types
- Update any related service methods if needed

Before making changes, read CLAUDE.md for project conventions.
</output>

<verification>
Before declaring complete, verify:
1. **Frontend validation works:**
   - Cannot submit with zero analysis types selected
   - Can select multiple checkboxes simultaneously
   - Select All / Deselect All buttons function correctly

2. **Backend correctly processes arrays:**
   - Video analysis creates multiple jobs (one per selected type)
   - Image analysis returns results for all selected types
   - API returns appropriate success/error messages

3. **Special cases still work:**
   - face_search still shows collection selector when checked
   - face_comparison still shows target image selector when checked
   - These special parameters are validated when their respective analysis types are selected

4. **Test manually:**
   - Select 2-3 analysis types for a video, verify multiple jobs created in history
   - Select 2-3 analysis types for an image, verify all results returned
   - Try Select All, verify all 8 types are checked
   - Deselect all and try submitting, verify validation prevents submission
</verification>

<success_criteria>
- Users can select 1-8 analysis types using checkboxes
- Video analysis creates multiple separate jobs (visible in history)
- Image analysis returns aggregated results for all selected types
- Validation prevents submission with no selections
- Conditional UI elements (collection/target image selectors) still work correctly
- Select All / Deselect All convenience features work as expected
</success_criteria>
