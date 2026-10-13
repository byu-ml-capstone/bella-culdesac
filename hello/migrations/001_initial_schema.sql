CREATE TABLE IF NOT EXISTS team_members (
    id UUID PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    email VARCHAR(320) NOT NULL UNIQUE,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(30) NOT NULL DEFAULT 'Team Member',
    membership_status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY,
    member_id UUID NOT NULL REFERENCES team_members(id),
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS workflow_templates (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    statuses JSONB NOT NULL,
    protected BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description VARCHAR(1000),
    vision VARCHAR(1000),
    scope VARCHAR(1000),
    tentative_outline VARCHAR(1000),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    start_date DATE NOT NULL,
    due_date DATE NOT NULL,
    workflow_template_id UUID REFERENCES workflow_templates(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT projects_date_order CHECK (due_date >= start_date)
);

CREATE TABLE IF NOT EXISTS user_stories (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    title VARCHAR(200) NOT NULL,
    description VARCHAR(1000),
    status VARCHAR(80) NOT NULL DEFAULT 'Backlog',
    story_type VARCHAR(30) NOT NULL DEFAULT 'User story',
    due_date DATE NOT NULL,
    start_date DATE NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'Medium',
    estimated_time NUMERIC(10,2) NOT NULL DEFAULT 1.00,
    completion_percent NUMERIC(5,2) NOT NULL DEFAULT 0.00,
    github_repo_url VARCHAR(500),
    notes VARCHAR(1000),
    parent_id UUID REFERENCES user_stories(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT stories_estimate_positive CHECK (estimated_time >= 0.01),
    CONSTRAINT stories_completion_range CHECK (completion_percent >= 0 AND completion_percent <= 100),
    CONSTRAINT stories_date_order CHECK (due_date >= start_date),
    CONSTRAINT stories_priority_valid CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    CONSTRAINT stories_type_valid CHECK (story_type IN ('Bug fix', 'User story', 'Spike story', 'Enabler story'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_member_expiry ON sessions(member_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_projects_dates ON projects(start_date, due_date);
CREATE INDEX IF NOT EXISTS idx_stories_project_status ON user_stories(project_id, status);

INSERT INTO workflow_templates (id, name, statuses, protected)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Standard Sprint',
    '["Backlog", "In Progress", "In Review", "Paused", "Complete", "Obsolete"]'::jsonb,
    TRUE
)
ON CONFLICT (name) DO NOTHING;
