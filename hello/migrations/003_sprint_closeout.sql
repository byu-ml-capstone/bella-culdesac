CREATE TABLE IF NOT EXISTS story_comments (
    id UUID PRIMARY KEY,
    story_id UUID NOT NULL REFERENCES user_stories(id),
    author_id UUID NOT NULL REFERENCES team_members(id),
    body VARCHAR(2000) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT story_comments_body_nonblank CHECK (length(trim(body)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_story_comments_story ON story_comments(story_id, created_at);
