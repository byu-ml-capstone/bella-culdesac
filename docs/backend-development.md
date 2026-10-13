# Backend development

## Local setup

From `bella-culdesac`:

```powershell
$env:SERVICE_FQDN_HELLO = "http://localhost:8000"
docker compose up -d --build
```

The public FastAPI service is `hello`; PostgreSQL is the internal `db` service. The local override maps `hello` to port 8000 and enables the local-only reset endpoint.

Create the first local Team Lead once:

```powershell
docker compose exec `
  -e 'BOOTSTRAP_ADMIN_NAME=Team Lead' `
  -e 'BOOTSTRAP_ADMIN_EMAIL=lead@example.com' `
  -e 'BOOTSTRAP_ADMIN_USERNAME=lead' `
  -e 'BOOTSTRAP_ADMIN_PASSWORD=change-me-1!' `
  hello python -m bootstrap_admin
```

## IDE tests

The IDE may use `hello/.venv`:

```powershell
cd hello
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest tests/ -v
```

The Docker test is the authoritative environment when PostgreSQL behavior is involved:

```powershell
docker compose exec hello pytest tests/ -v
```

## Application conventions

- API routes use `/api/v1`.
- `/health` is readiness-aware and `/version` does not require PostgreSQL.
- Schema changes are numbered SQL files in `hello/migrations/` and run at startup.
- Do not edit an applied migration; add the next numbered migration.
- The application connects to PostgreSQL through the Compose hostname `db`.
- Never commit `.env` files, passwords, tokens, or `terraform.tfvars`.
