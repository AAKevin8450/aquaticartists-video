-- Migration: Enhanced File Tracking with Media Metadata
-- Created: 2025-12-19
-- Description: Adds media metadata fields to files table and links transcripts to files

-- ============================================================================
-- ENHANCE FILES TABLE WITH MEDIA METADATA
-- ============================================================================

-- Add proxy relationship fields
ALTER TABLE files ADD COLUMN is_proxy BOOLEAN DEFAULT 0;
ALTER TABLE files ADD COLUMN source_file_id INTEGER REFERENCES files(id) ON DELETE CASCADE;

-- Add local storage path
ALTER TABLE files ADD COLUMN local_path TEXT;

-- Add media metadata fields
ALTER TABLE files ADD COLUMN resolution_width INTEGER;
ALTER TABLE files ADD COLUMN resolution_height INTEGER;
ALTER TABLE files ADD COLUMN frame_rate REAL;
ALTER TABLE files ADD COLUMN codec_video TEXT;
ALTER TABLE files ADD COLUMN codec_audio TEXT;
ALTER TABLE files ADD COLUMN duration_seconds REAL;
ALTER TABLE files ADD COLUMN bitrate INTEGER;

-- ============================================================================
-- LINK TRANSCRIPTS TO FILES TABLE
-- ============================================================================

-- Add file_id to transcripts table (nullable for backward compatibility)
ALTER TABLE transcripts ADD COLUMN file_id INTEGER REFERENCES files(id) ON DELETE CASCADE;

-- ============================================================================
-- CREATE INDEXES FOR PERFORMANCE
-- ============================================================================

-- Index for finding proxy files by source
CREATE INDEX IF NOT EXISTS idx_files_source_file_id ON files(source_file_id);

-- Index for finding files by type and proxy status
CREATE INDEX IF NOT EXISTS idx_files_is_proxy ON files(is_proxy);

-- Index for finding transcripts by file
CREATE INDEX IF NOT EXISTS idx_transcripts_file_id ON transcripts(file_id);

-- Index for media queries (resolution, codec, etc.)
CREATE INDEX IF NOT EXISTS idx_files_resolution ON files(resolution_width, resolution_height);
CREATE INDEX IF NOT EXISTS idx_files_duration ON files(duration_seconds);

-- ============================================================================
-- DATA MIGRATION: Update existing records
-- ============================================================================

-- Update existing files that have proxy metadata in JSON to new schema
UPDATE files
SET
    is_proxy = 0,
    local_path = json_extract(metadata, '$.local_path'),
    duration_seconds = CAST(json_extract(metadata, '$.duration_seconds') AS REAL)
WHERE json_extract(metadata, '$.local_path') IS NOT NULL;

-- ============================================================================
-- MIGRATION COMPLETED
-- ============================================================================

-- Migration completed successfully
-- Next steps:
-- 1. Run this migration using Python script or SQLite command
-- 2. Update app/database.py with new CRUD functions
-- 3. Update upload.py to populate new fields
-- 4. Test file tracking with media metadata
