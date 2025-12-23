# Multi-Select Analysis Testing Guide

## Overview
This document describes the multi-select analysis feature that allows users to select and run multiple analysis types simultaneously for both video and image files.

## Changes Made

### Frontend Changes

#### 1. Video Analysis (app/templates/video_analysis.html)
- **Radio buttons → Checkboxes**: Changed from single-select radio buttons to multi-select checkboxes
- **Select All / Deselect All buttons**: Added convenience buttons in the card header
- **Updated validation**: Ensures at least one analysis type is selected before submission
- **Conditional display**: Face Search collection selector appears when face_search is checked
- **Multi-type payload**: JavaScript now collects all checked analysis types into an array

#### 2. Image Analysis (app/templates/image_analysis.html)
- **Radio buttons → Checkboxes**: Changed from single-select radio buttons to multi-select checkboxes
- **Select All / Deselect All buttons**: Added convenience buttons in the card header
- **Updated validation**: Ensures at least one analysis type is selected before submission
- **Conditional display**:
  - Face Search collection selector appears when face_search is checked
  - Target image selector appears when face_comparison is checked
- **Multi-type payload**: JavaScript now collects all checked analysis types into an array
- **Enhanced results display**: Results are organized by analysis type with formatted headers

### Backend Changes

#### 1. New Unified API Routes (app/routes/analysis.py)
Created a new blueprint with two endpoints:

**POST /api/analysis/video/start**
- Accepts `analysis_types` array instead of single `analysis_type`
- Creates separate Rekognition jobs for each selected analysis type
- Returns array of `job_ids` and `job_db_ids`
- Handles errors gracefully - if some jobs fail, successful ones still proceed
- Special handling for face_search (requires collection_id)

**POST /api/analysis/image/analyze**
- Accepts `analysis_types` array instead of single `analysis_type`
- Performs all analyses synchronously
- Returns aggregated results organized by analysis type
- Handles errors gracefully - failed analyses are reported in `failed` array
- Special handling for:
  - face_search (requires collection_id, uses face_collection_service)
  - face_comparison (requires target_file_id)

#### 2. Models Update (app/models.py)
- Added `IMAGE_FACE_SEARCH = 'image_face_search'` to AnalysisType class

#### 3. App Registration (app/__init__.py)
- Registered the new `analysis` blueprint

## Analysis Type Mappings

### Video Analysis Types
| Frontend Value | Backend Analysis Type | Service Method |
|---------------|----------------------|----------------|
| label_detection | VIDEO_LABELS | start_label_detection |
| face_detection | VIDEO_FACES | start_face_detection |
| celebrity_recognition | VIDEO_CELEBRITIES | start_celebrity_recognition |
| content_moderation | VIDEO_MODERATION | start_content_moderation |
| text_detection | VIDEO_TEXT | start_text_detection |
| person_tracking | VIDEO_PERSONS | start_person_tracking |
| face_search | VIDEO_FACE_SEARCH | start_face_search |
| shot_segmentation | VIDEO_SEGMENTS | start_segment_detection |

### Image Analysis Types
| Frontend Value | Backend Analysis Type | Service Method |
|---------------|----------------------|----------------|
| label_detection | IMAGE_LABELS | detect_labels |
| face_detection | IMAGE_FACES | detect_faces |
| celebrity_recognition | IMAGE_CELEBRITIES | recognize_celebrities |
| content_moderation | IMAGE_MODERATION | detect_moderation_labels |
| text_detection | IMAGE_TEXT | detect_text |
| ppe_detection | IMAGE_PPE | detect_protective_equipment |
| face_search | IMAGE_FACE_SEARCH | search_faces_by_image |
| face_comparison | IMAGE_FACE_COMPARE | compare_faces |

## Testing Checklist

### Video Analysis Testing

1. **Basic Multi-Select**
   - [ ] Select 2-3 analysis types (e.g., label_detection, face_detection, text_detection)
   - [ ] Click "Analyze" button
   - [ ] Verify success message shows correct count (e.g., "3 job(s) submitted")
   - [ ] Navigate to History page
   - [ ] Verify 3 separate jobs were created

2. **Select All / Deselect All**
   - [ ] Click "Select All" button
   - [ ] Verify all 8 checkboxes are checked
   - [ ] Click "Deselect All" button
   - [ ] Verify all checkboxes are unchecked

3. **Validation**
   - [ ] Deselect all checkboxes
   - [ ] Click "Analyze" button
   - [ ] Verify warning: "Please select at least one analysis type"

4. **Face Search Special Handling**
   - [ ] Select face_search checkbox
   - [ ] Verify collection selector card appears
   - [ ] Try to submit without selecting a collection
   - [ ] Verify warning: "Please select a face collection for Face Search"
   - [ ] Select a collection and submit
   - [ ] Verify job created successfully

5. **Mixed Selection with Face Search**
   - [ ] Select label_detection + face_search
   - [ ] Select a collection
   - [ ] Submit and verify 2 jobs created

### Image Analysis Testing

1. **Basic Multi-Select**
   - [ ] Select 2-3 analysis types (e.g., label_detection, face_detection, text_detection)
   - [ ] Click "Analyze Image" button
   - [ ] Verify success message shows correct count (e.g., "3 analysis type(s) completed")
   - [ ] Verify results are displayed organized by analysis type
   - [ ] Each result should have a formatted header (e.g., "Label Detection")

2. **Select All / Deselect All**
   - [ ] Click "Select All" button
   - [ ] Verify all 8 checkboxes are checked
   - [ ] Click "Deselect All" button
   - [ ] Verify all checkboxes are unchecked

3. **Validation**
   - [ ] Deselect all checkboxes
   - [ ] Click "Analyze Image" button
   - [ ] Verify warning: "Please select at least one analysis type"

4. **Face Search Special Handling**
   - [ ] Select face_search checkbox only
   - [ ] Verify collection selector card appears
   - [ ] Try to submit without selecting a collection
   - [ ] Verify warning: "Please select a face collection for Face Search"
   - [ ] Select a collection and submit
   - [ ] Verify results displayed

5. **Face Comparison Special Handling**
   - [ ] Select face_comparison checkbox only
   - [ ] Verify target image selector card appears
   - [ ] Try to submit without selecting a target image
   - [ ] Verify warning: "Please select a target image for Face Comparison"
   - [ ] Select a target image and submit
   - [ ] Verify results displayed

6. **Mixed Selection with Special Types**
   - [ ] Select label_detection + face_search + face_comparison
   - [ ] Select collection for face_search
   - [ ] Select target image for face_comparison
   - [ ] Submit and verify all 3 results displayed
   - [ ] Verify results are properly organized

7. **Results Display**
   - [ ] Run analysis with 3+ types
   - [ ] Verify each result section has:
     - Formatted analysis type header
     - JSON results in formatted code block
     - Proper spacing between sections

### Error Handling Testing

1. **Partial Failures (if possible to simulate)**
   - [ ] Select multiple analysis types where one might fail
   - [ ] Verify successful analyses still complete
   - [ ] Verify failed analyses are reported in response

2. **Network Errors**
   - [ ] Test with network interruption (if applicable)
   - [ ] Verify appropriate error messages

## API Endpoints

### Video Analysis
```
POST /api/analysis/video/start
Content-Type: application/json

{
  "file_id": 123,
  "analysis_types": ["label_detection", "face_detection", "text_detection"],
  "collection_id": "my-collection"  // Required only if "face_search" is in analysis_types
}

Response (Success):
{
  "job_ids": ["job-id-1", "job-id-2", "job-id-3"],
  "job_db_ids": [1, 2, 3],
  "status": "SUBMITTED",
  "count": 3,
  "message": "3 video analysis job(s) started successfully"
}

Response (Partial Success):
{
  "job_ids": ["job-id-1", "job-id-2"],
  "job_db_ids": [1, 2],
  "status": "SUBMITTED",
  "count": 2,
  "message": "2 video analysis job(s) started successfully (1 failed)",
  "failed": [
    {
      "analysis_type": "person_tracking",
      "error": "AccessDeniedException: ..."
    }
  ]
}
```

### Image Analysis
```
POST /api/analysis/image/analyze
Content-Type: application/json

{
  "file_id": 123,
  "analysis_types": ["label_detection", "face_detection", "text_detection"],
  "collection_id": "my-collection",  // Required only if "face_search" is in analysis_types
  "target_file_id": 456  // Required only if "face_comparison" is in analysis_types
}

Response (Success):
{
  "job_id": "uuid",
  "job_db_id": 1,
  "status": "SUCCEEDED",
  "count": 3,
  "results": {
    "label_detection": { /* analysis results */ },
    "face_detection": { /* analysis results */ },
    "text_detection": { /* analysis results */ }
  }
}

Response (Partial Success):
{
  "job_id": "uuid",
  "job_db_id": 1,
  "status": "SUCCEEDED",
  "count": 2,
  "results": {
    "label_detection": { /* analysis results */ },
    "face_detection": { /* analysis results */ }
  },
  "failed": [
    {
      "analysis_type": "celebrity_recognition",
      "error": "No faces detected"
    }
  ]
}
```

## Files Modified

### Templates
- `E:\coding\video\app\templates\video_analysis.html`
- `E:\coding\video\app\templates\image_analysis.html`

### Routes
- `E:\coding\video\app\routes\analysis.py` (NEW)
- `E:\coding\video\app\__init__.py`

### Models
- `E:\coding\video\app\models.py`

## Known Limitations

1. **Person Tracking**: May return AccessDeniedException due to AWS account-level restrictions (documented in CLAUDE.md)

2. **Face Search**: Requires pre-existing face collections with indexed faces

3. **Face Comparison**: Requires at least 2 uploaded images

## Troubleshooting

### Checkboxes not appearing
- Hard refresh browser (Ctrl+F5)
- Check browser console for JavaScript errors

### "Select All" not working
- Verify JavaScript is enabled
- Check console for errors

### API returns 404
- Verify Flask app restarted after code changes
- Check that analysis blueprint is registered

### Jobs not appearing in history
- Check database permissions
- Verify job creation didn't fail (check logs)

### Face search fails
- Verify collection exists and has indexed faces
- Check IAM permissions for SearchFacesByImage
