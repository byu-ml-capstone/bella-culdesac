CREATE TABLE IF NOT EXISTS invitations (
    id UUID PRIMARY KEY,
    email VARCHAR(320) NOT NULL,
    name VARCHAR(120) NOT NULL,
    role VARCHAR(30) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    CONSTRAINT invitations_role_valid CHECK (role IN ('Team Lead', 'Team Member', 'Faculty Advisor')),
    CONSTRAINT invitations_status_valid CHECK (status IN ('pending', 'accepted', 'expired', 'revoked'))
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id UUID PRIMARY KEY,
    member_id UUID NOT NULL REFERENCES team_members(id),
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_invitation_email ON invitations (lower(email)) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_password_reset_member_expiry ON password_reset_tokens(member_id, expires_at);
