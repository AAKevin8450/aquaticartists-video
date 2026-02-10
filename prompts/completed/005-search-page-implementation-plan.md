<objective>
Create a comprehensive implementation plan for a unified Search page that allows users to search across all data in the application: files, analysis results, and transcripts.

This is a PLANNING TASK ONLY - do not make any code changes. The deliverable is a detailed implementation plan document.
</objective>

<context>
This is a Flask-based AWS Video & Image Analysis Application with:
- SQLite database (data/app.db)
- Multiple data types: files, Rekognition analysis jobs, Nova analysis, transcripts
- Existing templates using Bootstrap 5
- Navigation in base.html template

The Search page will be a new top-level navigation item, providing unified search across all stored data.
</context>

<research>
Thoroughly analyze the codebase to understand all searchable data. Examine:

1. **Database Schema** - Read and document all tables and their searchable fields:
   @app/database.py - All table definitions and existing query patterns

2. **Data Models** - Understand what data is stored:
   - Files table: file metadata, S3 paths, statuses
   - Analysis jobs: Rekognition results (8 types), Nova results (3 types)
   - Transcripts: transcript text, segments, word timestamps
   - Face collections: collection data and indexed faces

3. **Existing Search Patterns** - Review current search implementations:
   @app/routes/file_management.py - File search/filter logic
   @app/routes/transcription.py - Transcript search functionality
   @app/templates/file_management.html - Frontend search UI patterns

4. **API Patterns** - Understand existing REST API conventions:
   - Pagination patterns
   - Response formats
   - Error handling

5. **UI Patterns** - Review existing templates for consistency:
   @app/templates/base.html - Navigation structure
   @app/templates/file_management.html - Search UI components
   @app/static/js/file_management.js - Frontend search logic
</research>

<analysis_requirements>
After researching the codebase, document:

1. **Data Inventory**
   - List ALL searchable data types with their fields
   - Identify which fields should be full-text searchable
   - Note any JSON fields that contain searchable content (e.g., Rekognition results, transcript segments)

2. **Search Scope Options**
   - What should users be able to search? (file names, transcript text, detected labels, celebrity names, OCR text, etc.)
   - What filters should be available? (date range, file type, analysis type, status)
   - Should search be unified or have category tabs?

3. **Technical Considerations**
   - SQLite full-text search (FTS5) vs LIKE queries
   - Performance implications for large datasets (10,000+ files)
   - JSON field searching strategies
   - Indexing requirements

4. **UI/UX Design**
   - Where in navigation (between which items?)
   - Search input design (single box vs advanced filters)
   - Results display (unified list vs categorized sections)
   - Result actions (view, edit, navigate to source)
</analysis_requirements>

<deliverables>
Create a detailed implementation plan saved to: `./planning/search-page-plan.md`

The plan should include:

## 1. Executive Summary
- Purpose and scope of the Search feature
- Key benefits to users

## 2. Data Analysis
- Complete inventory of searchable data
- Field-by-field breakdown of what can be searched
- Data relationships and how results link together

## 3. Technical Architecture
- Database changes required (new tables, indexes, FTS)
- API endpoint design (routes, parameters, responses)
- Frontend component structure

## 4. Implementation Phases
Break into logical phases with clear deliverables:
- Phase 1: Basic search infrastructure
- Phase 2: Core search functionality
- Phase 3: Advanced features
- Phase 4: Performance optimization

## 5. UI/UX Specification
- Wireframe description of the Search page layout
- Navigation placement
- Search input and filter controls
- Results display format for each data type
- Mobile responsiveness considerations

## 6. API Specification
- Endpoint definitions with request/response examples
- Query parameter documentation
- Pagination specification

## 7. Database Changes
- New indexes required
- FTS table specifications if applicable
- Migration plan

## 8. File Changes Summary
- List of all files that will need to be created or modified
- Brief description of changes per file

## 9. Testing Strategy
- Test cases for search functionality
- Performance benchmarks to target
- Edge cases to handle

## 10. Considerations & Trade-offs
- Alternative approaches considered
- Performance vs complexity trade-offs
- Future enhancement possibilities
</deliverables>

<constraints>
- Do NOT make any code changes - this is planning only
- Plan must be compatible with existing SQLite database
- Must maintain consistency with existing UI patterns (Bootstrap 5)
- Should leverage existing JavaScript patterns from file_management.js
- Performance target: Search results in <500ms for 10,000+ records
</constraints>

<verification>
Before completing, verify the plan includes:
- [ ] Complete inventory of all searchable data types
- [ ] Clear database schema changes documented
- [ ] API endpoints fully specified
- [ ] UI wireframe/description provided
- [ ] Implementation phases with clear deliverables
- [ ] Performance considerations addressed
- [ ] All affected files listed
</verification>

<success_criteria>
The plan is complete when:
1. Someone could implement the Search page using only this plan
2. All data types in the application are accounted for
3. Technical approach is clearly defined with specific implementation details
4. No ambiguity about what needs to be built
</success_criteria>

<output>
Save the complete plan to: `./planning/search-page-plan.md`

If the planning directory doesn't exist, create it first.
</output>
