# Cul-de-sac deployment scaffold

Cul-de-sac is a FastAPI engineering workflow application deployed using the class platform’s Docker Compose and Coolify setup.

## Services

| Service | Public | Purpose |
|---|---:|---|
| `hello` | yes | FastAPI application on internal port 8000 |
| `db` | no | PostgreSQL 16 with persistent storage |

The `hello` service is the only public service. It references `${SERVICE_FQDN_HELLO}` so Coolify/Traefik can route the configured domain to it. PostgreSQL is available only through the Compose network at `db:5432`.

## Local development

Requirements: Docker Desktop and Bash-compatible shell for `smoke-test.sh`.

```bash
export SERVICE_FQDN_HELLO=http://localhost:8000
docker compose up -d --build
curl http://localhost:8000/health
```

The local override binds port 8000 and enables the destructive reset endpoint. The deployed Compose file never binds a host port.

## First Team Lead

After PostgreSQL is healthy, create the first account once:

```bash
docker compose exec \
  -e BOOTSTRAP_ADMIN_NAME="Team Lead" \
  -e BOOTSTRAP_ADMIN_EMAIL="lead@example.com" \
  -e BOOTSTRAP_ADMIN_USERNAME="lead" \
  -e BOOTSTRAP_ADMIN_PASSWORD="change-me-1!" \
  hello python -m bootstrap_admin
```

Use a real temporary password locally and remove the variables after the command succeeds. The command refuses to create a second active Team Lead.

## Tests and smoke test

```bash
cd hello
pip install -r requirements.txt
pytest tests/ -v
cd ..
SMOKE_USERNAME=lead SMOKE_PASSWORD='change-me-1!' ./smoke-test.sh
```

The smoke test checks health, authentication, project/story/sprint creation, sprint association, and database-backed reads. It supports local mode with no argument and deployed-URL mode with one URL argument.

The standard test command is database-independent. To run the PostgreSQL-backed role and permission test locally in Docker:

```bash
docker compose exec -e RUN_DB_TESTS=1 hello pytest tests/ -v
```

## Migrations and reset

Numbered SQL files in `hello/migrations/` are applied by the application during startup. Each successful filename is recorded in `_migrations`.

`POST /admin/reset` is local-only, requires Team Lead authentication, and is enabled by `ALLOW_ADMIN_RESET=true`. It clears application data and attachment files, reapplies migrations, and recreates protected workflow seed data.

## Deployment

The existing GitHub Actions workflow tests pushes and pull requests, then deploys `staging` and `main` through Coolify webhooks. Keep `terraform/` and deployment secrets outside source control. After changing service routing or domains, reattach the Coolify domain to `hello` in both environments and redeploy so Traefik refreshes its routing labels.

More detailed instructions are in [`docs/backend-development.md`](docs/backend-development.md), [`docs/deployment.md`](docs/deployment.md), and [`docs/operations.md`](docs/operations.md).
