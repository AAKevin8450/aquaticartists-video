-- Migration: Add batch processing fields to nova_jobs
-- Created: 2025-12-19

ALTER TABLE nova_jobs ADD COLUMN batch_mode BOOLEAN DEFAULT 0;
ALTER TABLE nova_jobs ADD COLUMN batch_job_arn TEXT;
ALTER TABLE nova_jobs ADD COLUMN batch_status TEXT;
ALTER TABLE nova_jobs ADD COLUMN batch_input_s3_key TEXT;
ALTER TABLE nova_jobs ADD COLUMN batch_output_s3_prefix TEXT;

CREATE INDEX IF NOT EXISTS idx_nova_jobs_batch_status ON nova_jobs(batch_status);
