-- Migration 001 — initial schema.
--
-- Runs on the first startup against a fresh database. Subsequent
-- startups skip this file because its name is recorded in the
-- _migrations tracking table (see hello/notes_dao.py apply_migrations()).
--
-- `IF NOT EXISTS` makes the file safe to re-apply against an existing
-- database, which matters when adopting migrations partway through a
-- project's life: the notes table might already exist from an earlier
-- ensure_schema()-style setup.

CREATE TABLE IF NOT EXISTS notes (
    id         SERIAL       PRIMARY KEY,
    body       TEXT         NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
