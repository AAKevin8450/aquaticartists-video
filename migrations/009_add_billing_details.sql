-- Migration 009: Add detailed billing breakdown
-- Adds operation-level detail to billing cache for granular cost analysis

-- Create detailed billing cache table
CREATE TABLE IF NOT EXISTS billing_cache_details (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_code TEXT NOT NULL,           -- AWS service code (e.g., "AmazonBedrock")
    operation TEXT NOT NULL,              -- Operation name (e.g., "Bedrock.ModelInvocation.Lite")
    usage_type TEXT NOT NULL,             -- Usage type (e.g., "Tokens", "Requests", "GB-Mo")
    usage_date DATE NOT NULL,             -- Date in YYYY-MM-DD format
    usage_amount REAL NOT NULL,           -- Quantity of usage (e.g., 1234567.0 tokens)
    cost_usd REAL NOT NULL,               -- Cost in USD
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for efficient service-date queries
CREATE INDEX IF NOT EXISTS idx_billing_details_service_date
ON billing_cache_details(service_code, usage_date);

-- Index for operation-level queries
CREATE INDEX IF NOT EXISTS idx_billing_details_operation
ON billing_cache_details(service_code, operation, usage_date);

-- Unique constraint prevents duplicate entries for same service-operation-usage_type-date
CREATE UNIQUE INDEX IF NOT EXISTS ux_billing_details_unique
ON billing_cache_details(service_code, operation, usage_type, usage_date);
