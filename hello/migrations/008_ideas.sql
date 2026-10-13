CREATE TABLE IF NOT EXISTS ideas (
    id UUID PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description VARCHAR(2000),
    scope VARCHAR(20) NOT NULL,
    project_id UUID REFERENCES projects(id),
    status VARCHAR(20) NOT NULL DEFAULT 'parked',
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    promoted_project_id UUID REFERENCES projects(id),
    created_by UUID NOT NULL REFERENCES team_members(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT ideas_scope_valid CHECK (scope IN ('team', 'project')),
    CONSTRAINT ideas_status_valid CHECK (status IN ('parked', 'promoted', 'converted', 'archived')),
    CONSTRAINT ideas_project_scope_valid CHECK ((scope = 'team' AND project_id IS NULL) OR (scope = 'project' AND project_id IS NOT NULL))
);

ALTER TABLE user_stories ADD COLUMN IF NOT EXISTS source_idea_id UUID REFERENCES ideas(id);
CREATE INDEX IF NOT EXISTS idx_ideas_scope_status ON ideas(scope, status);
CREATE INDEX IF NOT EXISTS idx_ideas_project ON ideas(project_id);
