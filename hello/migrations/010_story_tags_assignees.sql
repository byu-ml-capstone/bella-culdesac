ALTER TABLE user_stories ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS story_assignees (
    story_id UUID NOT NULL REFERENCES user_stories(id) ON DELETE CASCADE,
    member_id UUID NOT NULL REFERENCES team_members(id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (story_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_story_assignees_member ON story_assignees(member_id);
