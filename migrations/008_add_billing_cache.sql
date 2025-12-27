-- Migration 008: Add billing cache tables for AWS Cost and Usage Report data
-- This migration adds tables to cache aggregated billing data from AWS CUR

-- Billing cache table for aggregated cost data by service and date
CREATE TABLE IF NOT EXISTS billing_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_code TEXT NOT NULL,           -- AWS service code (e.g., "AmazonS3", "AmazonBedrock")
    service_name TEXT NOT NULL,           -- Human-readable service name
    usage_date DATE NOT NULL,             -- Date in YYYY-MM-DD format
    cost_usd REAL NOT NULL,              -- Cost in USD
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast service + date range queries
CREATE INDEX IF NOT EXISTS idx_billing_cache_service
ON billing_cache(service_code, usage_date);

-- Index for date-based queries
CREATE INDEX IF NOT EXISTS idx_billing_cache_date
ON billing_cache(usage_date DESC);

-- Unique constraint to prevent duplicate entries
CREATE UNIQUE INDEX IF NOT EXISTS ux_billing_cache_unique
ON billing_cache(service_code, usage_date);

-- Billing sync log table to track CUR data syncs
CREATE TABLE IF NOT EXISTS billing_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_started_at TIMESTAMP NOT NULL,
    sync_completed_at TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'IN_PROGRESS',  -- IN_PROGRESS, COMPLETED, FAILED
    records_processed INTEGER DEFAULT 0,
    date_range_start DATE NOT NULL,
    date_range_end DATE NOT NULL,
    error_message TEXT
);

-- Index for finding recent syncs
CREATE INDEX IF NOT EXISTS idx_billing_sync_log_status
ON billing_sync_log(status, sync_started_at DESC);
