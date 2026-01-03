-- Migration 011: Remove face_collections table (legacy feature never implemented)
-- Date: 2026-01-03

-- Drop the index first
DROP INDEX IF EXISTS idx_collections_created_at;

-- Drop the table
DROP TABLE IF EXISTS face_collections;
