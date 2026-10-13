CREATE TABLE IF NOT EXISTS idea_comments (
    id UUID PRIMARY KEY,
    idea_id UUID NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES team_members(id),
    body VARCHAR(2000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT idea_comments_body_nonblank CHECK (length(trim(body)) > 0)
);

CREATE TABLE IF NOT EXISTS sprint_report_comments (
    id UUID PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES sprint_reports(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES team_members(id),
    body VARCHAR(2000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT sprint_report_comments_body_nonblank CHECK (length(trim(body)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_idea_comments_idea ON idea_comments(idea_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sprint_report_comments_report ON sprint_report_comments(report_id, created_at);
