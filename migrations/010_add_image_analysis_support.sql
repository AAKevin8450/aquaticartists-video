-- Add content_type to distinguish video vs image analysis
ALTER TABLE nova_jobs ADD COLUMN content_type VARCHAR(10) DEFAULT 'video';

-- Add description_result for image descriptions
ALTER TABLE nova_jobs ADD COLUMN description_result TEXT;

-- Create index for content_type queries
CREATE INDEX idx_nova_jobs_content_type ON nova_jobs(content_type);

-- Update existing records to have content_type='video'
UPDATE nova_jobs SET content_type = 'video' WHERE content_type IS NULL;
