<objective>
Analyze the entire codebase to create a comprehensive reorganization plan that:
1. Identifies large program files that should be split into smaller, purpose-specific modules
2. Maps all functions and their relationships to detect duplications
3. Proposes a logical, task-based file organization structure
4. Documents a refactoring plan with clear migration steps

The output is a detailed plan document only - NO code changes should be made.
</objective>

<context>
This is a Flask web application for AWS Video & Image Analysis. The codebase may have grown organically and now requires reorganization for better maintainability.

Key areas to examine:
- `app/services/` - Service layer modules
- `app/routes/` - Flask route handlers
- `app/` - Core application files
- `static/js/` - Frontend JavaScript files
- `scripts/` - Utility scripts

Read the project's CLAUDE.md for full architecture context.
</context>

<research>
Thoroughly analyze the codebase structure using these steps:

1. **File Size Analysis**
   - Identify all Python and JavaScript files
   - Calculate line counts for each file
   - Flag files exceeding 300 lines as candidates for splitting

2. **Function Inventory**
   - Extract all function definitions from each file
   - Document function purposes and parameters
   - Map function call relationships (what calls what)

3. **Duplication Detection**
   - Identify functions with similar names across files
   - Find code blocks that perform similar operations
   - Detect copy-paste patterns or near-duplicate logic
   - Flag helper functions that exist in multiple places

4. **Dependency Mapping**
   - Track imports between modules
   - Identify circular dependencies
   - Map external library usage patterns

5. **Logical Grouping Analysis**
   - Identify natural task-based boundaries within large files
   - Group related functions by domain (e.g., validation, formatting, API calls)
   - Consider single-responsibility principle for proposed splits
</research>

<analysis_requirements>
For each large file identified, provide:
- Current line count and function count
- Why it's too large (multiple responsibilities, mixed concerns)
- Proposed split into N smaller files with names and purposes
- Which functions go to which new file
- Impact on imports/dependencies

For duplications found, provide:
- Location of each duplicate (file:line)
- Recommended single location for the canonical version
- Files that should import instead of duplicating

Deeply consider:
- Backward compatibility of import paths
- Test file impacts
- Circular dependency risks from proposed changes
</analysis_requirements>

<output>
Create a comprehensive plan document saved as:
`./program_retooling.md`

Structure the document with:

## Executive Summary
Brief overview of findings and recommendations

## Current State Analysis
### File Size Metrics
| File | Lines | Functions | Status |
|------|-------|-----------|--------|

### Duplication Report
List all detected duplications with locations

## Proposed Reorganization

### Phase 1: Service Layer Refactoring
For each service file needing changes:
- Current structure
- Proposed new files
- Function migration map

### Phase 2: Route Handler Cleanup
Similar structure for routes

### Phase 3: Frontend JavaScript
Similar structure for JS files

### Phase 4: Utility Consolidation
Plan for centralizing common utilities

## Dependency Impact Analysis
- Import changes required
- Potential circular dependency resolutions

## Migration Steps
Numbered, sequential steps for implementing the reorganization

## Risk Assessment
- What could break
- Testing requirements
- Rollback considerations
</output>

<constraints>
- DO NOT modify any code files
- DO NOT create any new Python/JavaScript files
- ONLY create the program_retooling.md plan document
- Include specific line numbers and function names from actual analysis
- Base all recommendations on actual codebase examination, not assumptions
</constraints>

<verification>
Before completing, verify:
- All files over 300 lines have been analyzed
- All duplicate functions have been identified with file:line references
- Every proposed new file has a clear single purpose
- Migration steps are ordered correctly (dependencies first)
- The plan is actionable without ambiguity
</verification>

<success_criteria>
- program_retooling.md exists with all required sections
- Every large file has a concrete split proposal
- Zero duplications remain unaddressed in the plan
- A developer could follow the plan without additional clarification
</success_criteria>
