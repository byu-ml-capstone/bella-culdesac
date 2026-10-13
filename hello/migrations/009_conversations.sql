CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY,
    scope VARCHAR(20) NOT NULL,
    project_id UUID REFERENCES projects(id),
    title VARCHAR(200) NOT NULL,
    body VARCHAR(4000) NOT NULL,
    created_by UUID NOT NULL REFERENCES team_members(id),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT conversations_scope_valid CHECK (scope IN ('team', 'project')),
    CONSTRAINT conversations_status_valid CHECK (status IN ('active', 'archived')),
    CONSTRAINT conversations_project_scope_valid CHECK ((scope = 'team' AND project_id IS NULL) OR (scope = 'project' AND project_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS conversation_comments (
    id UUID PRIMARY KEY,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES team_members(id),
    body VARCHAR(2000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT conversation_comments_body_nonblank CHECK (length(trim(body)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_conversations_scope_status ON conversations(scope, status, created_at);
CREATE INDEX IF NOT EXISTS idx_conversations_project ON conversations(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_comments_conversation ON conversation_comments(conversation_id, created_at);
