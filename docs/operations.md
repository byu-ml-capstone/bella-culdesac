# Operations

## Migrations and health

Migrations run during application startup and are recorded in PostgreSQL table `_migrations`. A failed migration prevents the application from becoming ready. Inspect `docker compose logs hello` when startup remains unhealthy.

`/health` returns readiness only after migrations and a database query succeed. `/version` reports the configured application version without requiring the database.

## Resetting local data

With the local override enabled, an authenticated Team Lead may call:

```bash
curl -X POST http://localhost:8000/admin/reset
```

This permanently clears local database records and application-managed attachment files, then reapplies migrations and protected seed data. It is disabled by default and must remain disabled in staging and production.

## Backups and restore

Back up PostgreSQL and the attachment volume together; a database dump does not contain uploaded files. A basic database backup is:

```bash
docker compose exec -T db pg_dump -U appuser appdb > backup.sql
```

Restore only into the intended environment after stopping application writes. Restore attachment files separately from the attachment-volume backup, then start the stack and verify `/health` and a representative authenticated read.

## Bootstrap and secrets

The first Team Lead is created with `python -m bootstrap_admin`. Pass bootstrap values only for that command, verify login, and remove them from the shell/history where practical. Never log or commit passwords, session secrets, AI keys, reset tokens, or invitation tokens.

## Troubleshooting

- `hello` unhealthy: inspect startup logs and confirm PostgreSQL is healthy.
- `db` unhealthy: inspect PostgreSQL logs and verify its environment variables.
- Coolify returns 404: reattach the domain to `hello` and redeploy.
- Smoke authentication fails: verify the Team Lead exists and the supplied credentials match.
- A migration fails: fix the migration or add a corrective migration; do not mark it applied manually.
