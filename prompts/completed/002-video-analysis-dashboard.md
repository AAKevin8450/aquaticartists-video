<objective>
Create a detailed video analysis dashboard that transforms raw AWS Rekognition JSON results into a visually rich, insightful interface. The dashboard should display top detected items, timeframes, scenes, video statistics, charts, and graphs using a modern UI design.

This dashboard will be accessed by clicking a "View" button next to completed video analysis jobs in the history page. The existing "View" button that shows raw JSON in a modal should be renamed to "JSON" to differentiate the two viewing options.
</objective>

<context>
This is an existing Flask web application for AWS video/image analysis. Key files:
- @app/templates/history.html - History page with job listing and "View" button (currently shows raw JSON modal)
- @app/routes/history.py - API endpoints for job details and results
- @app/services/rekognition_video.py - Service that handles AWS Rekognition API calls
- @app/templates/base.html - Base template with Bootstrap 5 and navigation
- @app/static/css/style.css - Application styling
- @app/static/js/utils.js - Shared JavaScript utilities

The application uses:
- Flask with Jinja2 templates
- Bootstrap 5 for UI components
- Bootstrap Icons for iconography
- jQuery is NOT used (vanilla JavaScript with ES6 modules)
- SQLite database for job/results storage

Current "View" button behavior:
- Opens a Bootstrap modal with raw JSON in a <pre> tag
- Displays job metadata (job_id, status, timestamps)
- Modal has download options (Excel and JSON)

AWS Rekognition video analysis types supported:
1. **Label Detection** - Objects, activities, scenes with confidence scores and timestamps
2. **Face Detection** - Faces with attributes (age, gender, emotions, landmarks)
3. **Celebrity Recognition** - Famous people with confidence and metadata
4. **Content Moderation** - Inappropriate content flags with categories
5. **Text Detection** - OCR text with bounding boxes and timestamps
6. **Person Tracking** - Person path tracking across frames
7. **Face Search** - Matches against face collection with similarity scores
8. **Shot/Segment Detection** - Scene boundaries with technical/shot types
</context>

<research>
Before implementing, research the existing codebase to understand:

1. **Results Data Structure**: Examine actual JSON results stored in the database for each analysis type:
   - Read @app/database.py to understand how results are stored/retrieved
   - Review @app/utils/excel_exporter.py to see how results are currently parsed
   - Check sample results structure for each of the 8 analysis types

2. **Video Metadata**: Understand what video metadata is available:
   - Duration, codec, frame rate, resolution
   - How VideoMetadata is returned from Rekognition

3. **Existing UI Patterns**: Review current templates for consistent styling:
   - Card layouts, tables, modals
   - Color schemes and badge styling
   - Chart libraries already included (if any)

4. **Routing Patterns**: Examine how pages are rendered:
   - @app/routes/main.py for template rendering patterns
   - How to create a new dashboard page vs modal approach
</research>

<requirements>
## Core Dashboard Features

### 1. Dashboard Layout
- Full-page dashboard (new template: `app/templates/dashboard.html`)
- Accessible via "View" button → navigates to `/dashboard/<job_id>`
- Rename existing modal "View" to "JSON" (shows raw JSON in modal)
- Modern, clean design consistent with Bootstrap 5 theme
- Responsive layout (mobile-friendly)

### 2. Video Overview Section
- Video metadata card (duration, resolution, format, file size)
- Analysis summary (total items detected, processing time)
- Thumbnail or video player embed (if available)
- Quick stats with key metrics prominently displayed

### 3. Top Detected Items (Analysis-Type Specific)
Display the most relevant "top N" items based on analysis type:

| Analysis Type | Top Items Display |
|--------------|-------------------|
| Label Detection | Top 10 labels by confidence, grouped by category |
| Face Detection | Face count, age distribution, dominant emotions |
| Celebrity Recognition | Recognized celebrities with photos/links |
| Content Moderation | Flagged categories with severity levels |
| Text Detection | All detected text, grouped by timestamp |
| Person Tracking | Number of unique persons tracked |
| Face Search | Top matches with similarity percentages |
| Shot Segmentation | Scene breakdown with thumbnails/timestamps |

### 4. Timeline/Timeframe Visualization
- Interactive timeline showing when detections occur
- Timestamp markers for each detection type
- Ability to see what was detected at any point in the video
- Color-coded by detection type or confidence level

### 5. Charts and Graphs
Include appropriate visualizations based on analysis type:

**Chart Types to Implement:**
- **Bar Charts**: Top labels, emotion distribution, age groups
- **Pie/Donut Charts**: Category distribution, confidence ranges
- **Line Charts**: Detection frequency over video duration
- **Timeline Charts**: Scene/shot changes over time
- **Heatmaps**: Detection density across video frames

**Chart Library**: Use Chart.js (include via CDN) for interactive charts

### 6. Detailed Data Tables
- Sortable, filterable tables for detailed results
- Pagination for large result sets
- Export functionality (inherit existing Excel/JSON export)
- Search/filter within results

### 7. Scene/Segment Viewer (for Shot Segmentation)
- Visual scene breakdown with timestamp ranges
- Shot type indicators (technical cue, shot type)
- Duration of each segment

### 8. Navigation & Actions
- Back to History button
- Download options (Excel, JSON) - reuse existing functionality
- Share/link to dashboard (job_id in URL)
- Refresh/re-analyze option

## UI/UX Requirements

### Design Principles
- Information hierarchy: Most important metrics at top
- Progressive disclosure: Summary first, details on demand
- Consistent card-based layout
- Whitespace and readable typography
- Meaningful colors (green=good, red=warning, blue=info)

### Responsive Behavior
- Desktop: Multi-column grid layout
- Tablet: 2-column layout
- Mobile: Single column with collapsible sections

### Loading States
- Skeleton loaders while data loads
- Progress indicators for chart rendering
- Error states with helpful messages
</requirements>

<implementation>
## Files to Create/Modify

### New Files
1. `app/templates/dashboard.html` - Full dashboard template
2. `app/static/js/dashboard.js` - Dashboard JavaScript logic
3. `app/static/css/dashboard.css` - Dashboard-specific styles (optional, may use inline or style.css)
4. `app/routes/dashboard.py` - Dashboard route blueprint

### Modified Files
1. `app/templates/history.html` - Change "View" to "JSON", add new "View" button for dashboard
2. `app/__init__.py` - Register dashboard blueprint
3. `app/routes/history.py` - Add endpoint for dashboard data (if needed beyond existing)

## Technical Approach

### Backend
- Create `/dashboard/<job_id>` route that renders dashboard template
- Reuse existing `/api/history/<job_id>` for fetching job data
- Add helper functions to pre-process data for different chart types

### Frontend
- Fetch job data via existing API
- Process data client-side based on analysis type
- Render appropriate charts using Chart.js
- Build responsive layout with Bootstrap 5 grid

### Data Processing
For each analysis type, create specific data transformers:
- `processLabelData(results)` - Extract top labels, categories, timeline
- `processFaceData(results)` - Aggregate face attributes, emotions
- `processCelebrityData(results)` - Format celebrity info with images
- `processModerationData(results)` - Categorize flagged content
- `processTextData(results)` - Group text by timestamp
- `processPersonData(results)` - Track unique persons
- `processFaceSearchData(results)` - Format match results
- `processSegmentData(results)` - Format scene timeline
</implementation>

<output>
Create/modify files with relative paths:
- `./app/templates/dashboard.html` - Main dashboard template
- `./app/static/js/dashboard.js` - Dashboard functionality
- `./app/routes/dashboard.py` - Dashboard routes
- `./app/templates/history.html` - Update buttons (View → JSON, add Dashboard)
- `./app/__init__.py` - Register blueprint

Include Chart.js via CDN in the dashboard template for visualizations.
</output>

<verification>
Before declaring complete, verify:
1. Dashboard loads correctly for each of the 8 analysis types
2. Charts render properly with real data
3. Responsive layout works on mobile/tablet
4. "JSON" button still shows raw JSON modal
5. New "View" button navigates to dashboard page
6. All existing functionality remains intact
7. No JavaScript errors in browser console
8. Dashboard handles empty/missing data gracefully
</verification>

<success_criteria>
- Users can view a rich visual dashboard for any completed video analysis job
- Dashboard shows analysis-type-specific insights (not just raw JSON)
- At least 3 chart types are implemented (bar, pie/donut, timeline)
- Top detected items are prominently displayed
- Timeline visualization shows when detections occur in video
- UI is modern, responsive, and consistent with existing app styling
- Both "View" (dashboard) and "JSON" (raw modal) options are available
</success_criteria>
