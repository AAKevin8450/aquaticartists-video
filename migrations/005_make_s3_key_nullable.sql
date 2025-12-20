-- Migration: Make s3_key Nullable for Local-Only Files
-- Created: 2025-12-19
-- Description: Allows files to exist without S3 storage (e.g., local proxy files, transcribed videos)
--              Files are identified by file ID, not S3 keys

-- ============================================================================
-- MAKE S3_KEY NULLABLE IN FILES TABLE
-- ============================================================================

-- SQLite doesn't support ALTER COLUMN, so we need to recreate the table

-- Step 1: Create new table with nullable s3_key
CREATE TABLE files_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    s3_key TEXT UNIQUE,  -- Changed from NOT NULL to nullable
    file_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSON,
    is_proxy BOOLEAN DEFAULT 0,
    source_file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    local_path TEXT,
    resolution_width INTEGER,
    resolution_height INTEGER,
    frame_rate REAL,
    codec_video TEXT,
    codec_audio TEXT,
    duration_seconds REAL,
    bitrate INTEGER
);

-- Step 2: Copy all data from old table to new table
INSERT INTO files_new (
    id, filename, s3_key, file_type, size_bytes, content_type,
    uploaded_at, metadata, is_proxy, source_file_id, local_path,
    resolution_width, resolution_height, frame_rate,
    codec_video, codec_audio, duration_seconds, bitrate
)
SELECT
    id, filename, s3_key, file_type, size_bytes, content_type,
    uploaded_at, metadata, is_proxy, source_file_id, local_path,
    resolution_width, resolution_height, frame_rate,
    codec_video, codec_audio, duration_seconds, bitrate
FROM files;

-- Step 3: Drop old table
DROP TABLE files;

-- Step 4: Rename new table to original name
ALTER TABLE files_new RENAME TO files;

-- ============================================================================
-- RECREATE INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type);
CREATE INDEX IF NOT EXISTS idx_files_uploaded_at ON files(uploaded_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_size_bytes ON files(size_bytes DESC);
CREATE INDEX IF NOT EXISTS idx_files_source_file_id ON files(source_file_id);
CREATE INDEX IF NOT EXISTS idx_files_is_proxy ON files(is_proxy);
CREATE INDEX IF NOT EXISTS idx_files_resolution ON files(resolution_width, resolution_height);
CREATE INDEX IF NOT EXISTS idx_files_duration ON files(duration_seconds);

-- Note: s3_key UNIQUE constraint is preserved in the new table definition
-- but now allows NULL values (multiple NULLs are allowed in UNIQUE columns in SQLite)

-- ============================================================================
-- MIGRATION COMPLETED
-- ============================================================================

-- Migration completed successfully
-- Files can now exist without S3 keys
-- All existing records preserved with their S3 keys intact
