CREATE TABLE IF NOT EXISTS sprints (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    goal VARCHAR(1000) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'planned',
    workflow_template_id UUID REFERENCES workflow_templates(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER NOT NULL DEFAULT 1,
    CONSTRAINT sprints_date_order CHECK (end_date >= start_date),
    CONSTRAINT sprints_status_valid CHECK (status IN ('planned', 'active', 'paused', 'closed', 'archived'))
);

CREATE TABLE IF NOT EXISTS sprint_stories (
    id UUID PRIMARY KEY,
    sprint_id UUID NOT NULL REFERENCES sprints(id) ON DELETE CASCADE,
    story_id UUID NOT NULL REFERENCES user_stories(id),
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    planned_estimated_time NUMERIC(10,2) NOT NULL,
    planned_priority VARCHAR(20) NOT NULL,
    completed_at TIMESTAMPTZ,
    close_outcome VARCHAR(30),
    CONSTRAINT sprint_stories_unique_story UNIQUE (sprint_id, story_id),
    CONSTRAINT sprint_stories_estimate_positive CHECK (planned_estimated_time >= 0.01),
    CONSTRAINT sprint_stories_outcome_valid CHECK (close_outcome IS NULL OR close_outcome IN ('backlog', 'future_sprint', 'obsolete'))
);

CREATE INDEX IF NOT EXISTS idx_sprints_project_dates ON sprints(project_id, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_sprints_project_status ON sprints(project_id, status);
CREATE INDEX IF NOT EXISTS idx_sprint_stories_sprint ON sprint_stories(sprint_id);
CREATE INDEX IF NOT EXISTS idx_sprint_stories_story ON sprint_stories(story_id);
