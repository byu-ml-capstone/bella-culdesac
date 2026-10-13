CREATE TABLE IF NOT EXISTS sprint_reports (
    id UUID PRIMARY KEY,
    sprint_id UUID NOT NULL UNIQUE REFERENCES sprints(id),
    content JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    provider VARCHAR(80) NOT NULL,
    model VARCHAR(120) NOT NULL,
    input_hash VARCHAR(64) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT sprint_reports_status_valid CHECK (status IN ('draft', 'reviewed', 'finalized'))
);

CREATE INDEX IF NOT EXISTS idx_sprint_reports_status ON sprint_reports(status);
