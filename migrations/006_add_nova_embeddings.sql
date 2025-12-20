-- Migration: Add Nova embeddings tables (sqlite-vec)
-- Created: 2025-12-19
-- Description: Creates vector storage and metadata tables for Nova embeddings.

-- NOTE: sqlite-vec extension must be loaded before creating the vec0 virtual table.
-- Example (sqlite3 shell):
-- .load /path/to/vec0

CREATE TABLE IF NOT EXISTS nova_embedding_metadata (
    rowid INTEGER PRIMARY KEY,
    source_type TEXT NOT NULL,  -- 'nova_analysis' or 'transcript'
    source_id INTEGER NOT NULL,
    file_id INTEGER,
    model_name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_nova_embedding_source
ON nova_embedding_metadata(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_nova_embedding_file
ON nova_embedding_metadata(file_id);

CREATE INDEX IF NOT EXISTS idx_nova_embedding_model
ON nova_embedding_metadata(model_name);

CREATE UNIQUE INDEX IF NOT EXISTS ux_nova_embedding_unique
ON nova_embedding_metadata(source_type, source_id, model_name, content_hash);

-- Create vector storage (requires sqlite-vec)
-- Default dimension: 1024
CREATE VIRTUAL TABLE IF NOT EXISTS nova_embeddings USING vec0(
    embedding float[1024]
);
