ALTER TABLE story_comments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS attachments (
    id UUID PRIMARY KEY,
    story_id UUID NOT NULL REFERENCES user_stories(id),
    file_name VARCHAR(255) NOT NULL,
    content_type VARCHAR(120) NOT NULL,
    size_bytes BIGINT NOT NULL,
    storage_key VARCHAR(255) NOT NULL UNIQUE,
    uploaded_by UUID NOT NULL REFERENCES team_members(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT attachments_size_valid CHECK (size_bytes > 0 AND size_bytes <= 31457280)
);

CREATE INDEX IF NOT EXISTS idx_attachments_story ON attachments(story_id, created_at);
