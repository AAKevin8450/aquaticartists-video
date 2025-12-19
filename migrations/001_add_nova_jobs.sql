-- Migration: Add Nova Jobs table for AWS Nova video analysis
-- Created: 2025-12-18
-- Description: Creates nova_jobs table to store Nova analysis results and metadata

-- Create nova_jobs table
CREATE TABLE IF NOT EXISTS nova_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_job_id INTEGER NOT NULL,  -- FK to analysis_jobs table (for correlation with Rekognition jobs)

    -- Nova-specific configuration
    model VARCHAR(20) NOT NULL,  -- 'micro', 'lite', 'pro', 'premier'
    analysis_types TEXT NOT NULL,  -- JSON array: ["summary", "chapters", "elements"]
    user_options TEXT,  -- JSON object with user preferences (e.g., {"summary_depth": "standard", "language": "auto"})

    -- Chunking metadata (for Phase 2 - long video support)
    is_chunked BOOLEAN DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    chunk_duration INTEGER,  -- Chunk size in seconds (if chunked)
    overlap_duration INTEGER,  -- Overlap in seconds (if chunked)

    -- Results (stored as JSON)
    summary_result TEXT,  -- JSON object with summary data
    chapters_result TEXT,  -- JSON array of chapters
    elements_result TEXT,  -- JSON object with equipment/objects/topics

    -- Performance metrics
    tokens_input INTEGER,
    tokens_output INTEGER,
    tokens_total INTEGER,
    processing_time_seconds FLOAT,
    cost_usd FLOAT,

    -- Status tracking
    status VARCHAR(20) DEFAULT 'SUBMITTED',  -- SUBMITTED, IN_PROGRESS, COMPLETED, FAILED
    error_message TEXT,
    progress_percent INTEGER DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Foreign key
    FOREIGN KEY (analysis_job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_nova_jobs_analysis_job_id ON nova_jobs(analysis_job_id);
CREATE INDEX IF NOT EXISTS idx_nova_jobs_status ON nova_jobs(status);
CREATE INDEX IF NOT EXISTS idx_nova_jobs_model ON nova_jobs(model);
CREATE INDEX IF NOT EXISTS idx_nova_jobs_created_at ON nova_jobs(created_at DESC);

-- Add service column to existing analysis_jobs table (optional, for quick filtering)
-- This allows tracking which services were used for a job: 'rekognition', 'nova', or 'rekognition,nova'
-- Note: May fail if column already exists, which is fine (idempotent)
ALTER TABLE analysis_jobs ADD COLUMN services_used TEXT DEFAULT 'rekognition';

-- Migration completed successfully
-- Next steps:
-- 1. Run this migration using: sqlite3 data/app.db < migrations/001_add_nova_jobs.sql
-- 2. Add CRUD functions to app/database.py
-- 3. Test database operations
