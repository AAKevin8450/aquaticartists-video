-- Migration: Add chunk progress tracking fields to nova_jobs
-- Created: 2025-12-18
-- Description: Adds fields for real-time chunk progress tracking (Phase 2)

-- Add chunk progress tracking fields
ALTER TABLE nova_jobs ADD COLUMN current_chunk INTEGER DEFAULT 0;
ALTER TABLE nova_jobs ADD COLUMN chunk_status_message TEXT;

-- Migration completed successfully
-- Next steps:
-- 1. Run this migration using: sqlite3 data/app.db < migrations/002_add_chunk_progress.sql
-- 2. Update database.py CRUD functions to handle new fields
-- 3. Update nova_analysis.py status endpoint to return chunk progress
