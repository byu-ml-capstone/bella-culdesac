# hello-world-app

Minimal FastAPI starter for the ML Capstone class deployment lab. Use this to walk through the Coolify setup + push-to-deploy pipeline without getting entangled in ML plumbing.

## Layout

Repo root = orchestration + docs. Each subdirectory = one service (self-contained code + Dockerfile + deps).

```
hello-world-app/
├── docker-compose.yaml           # production compose (Coolify reads this)
├── docker-compose.override.yml   # local-dev only (host port bind); ignored by Coolify
├── smoke-test.sh                 # docker compose up + smoke-test everything; also `./smoke-test.sh URL` to test a deployed instance
├── README.md
├── .gitignore                    # Python/Docker noise + terraform secrets and state
├── .github/workflows/ci.yml      # 3-job pipeline: test → deploy-staging → deploy-prod
│
├── hello/                        # PUBLIC service — Traefik-routed
│   ├── main.py                   #   FastAPI wiring + endpoints (thin)
│   ├── greetings.py              #   content + logic (split out from main.py on purpose)
│   ├── notes_dao.py              #   NotesDAO — all SQL and migration runner live here
│   ├── migrations/               #   *.sql files — applied on app startup in filename order
│   │   └── 001_create_notes.sql  #   initial schema; add 002_*.sql etc. as you evolve it
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── conftest.py               #   makes hello/ the pytest rootdir
│   └── tests/test_api.py         #   twelve tests; DAO-boundary + sidecar mocks
│
├── time/                         # INTERNAL sidecar — no external routing
│   ├── main.py                   #   FastAPI returning UTC time on /now
│   ├── requirements.txt
│   └── Dockerfile
│
└── terraform/                    # NOT a service — provisions the Coolify side
    ├── main.tf                   #   the resources: project, 2 envs, 2 apps, 3 GitHub secrets
    ├── variables.tf              #   every input, what it means, which have class defaults
    ├── outputs.tf                #   URLs + UUIDs printed after `apply`
    ├── terraform.tfvars.example  #   copy to terraform.tfvars and fill in 4 values
    ├── .terraform.lock.hcl       #   pins provider versions + checksums — committed on purpose
    ├── .gitignore                #   keeps terraform.tfvars (real tokens) and *.tfstate out of git
    └── README.md                 #   the deeper walkthrough, incl. why domains stay manual
```

`hello/` is the only public service. `time/` is a lightweight sidecar demo. There's no `db/` subdirectory — the Postgres sidecar in `docker-compose.yaml` uses the stock `postgres:16-alpine` image directly. Postgres is a generic storage service; the app owns its schema and materializes it at startup via a FastAPI lifespan hook in `hello/main.py`. That's the modern Django/Rails/Alembic convention: db container = dumb storage, app codebase = schema source of truth. Add more sidecars the same way: their own subdirectory (if they need one) or just an `image:` line in compose, `expose:` for the port, no `${SERVICE_FQDN_*}` so Coolify keeps them internal-only.

`terraform/` is the odd one out — it isn't a service and nothing in it ships inside a container. It describes the Coolify and GitHub resources your app needs *around* it: the Project, the two Environments, the two Applications, and the three Actions secrets. You can ignore it entirely and click through the Coolify UI instead; see [Provisioning with Terraform](#provisioning-with-terraform) below.

## Architecture

```
Browser / curl
      │  http://<domain>                          (via Coolify Traefik in prod, or host:8000 locally)
      ▼
┌────────────────────┐      http://time:8001/now      ┌────────────────────┐
│   hello (FastAPI)  │ ────────────────────────────▶  │   time (FastAPI)   │
│   port 8000        │      Docker DNS by service     │   port 8001        │
│   PUBLIC           │      name — internal only      │   INTERNAL         │
└──────────┬─────────┘                                └────────────────────┘
           │  postgres://appuser:apppass@db:5432/appdb
           ▼
┌────────────────────┐
│   db (postgres)    │      persistent volume: db-data
│   port 5432        │      → survives docker compose down
│   INTERNAL         │      → wiped only by `docker compose down -v`
└────────────────────┘
```

Only `hello` gets a public URL. `time` and `db` are reachable only from other services on the Compose network. Coolify isolates volumes per-Application, so staging and prod each get their own `db-data` — they never share data.

### The three services

| Service | Built from | Port | Public? | What it is |
|---|---|---|---|---|
| `hello` | `./hello` (FastAPI) | 8000 | **yes** | The app. Serves every endpoint below, calls `time`, reads and writes `db`. |
| `time` | `./time` (FastAPI) | 8001 | no | A sidecar standing in for the kind of helper service you'd add for real work — a background worker, a local model server. Returns the current UTC time. |
| `db` | `postgres:16-alpine` | 5432 | no | Postgres. Data lives on the named volume `db-data`. |

**How they find each other.** Compose gives every service a DNS name matching its key, so `hello` reaches the sidecar at `http://time:8001` and the database at `db:5432`. No IP addresses, no port juggling — that's why `time` and `db` declare `expose:` rather than `ports:`, making them reachable *only* from inside the Compose network.

**Why `hello` uses `expose:` too.** The cluster server is shared, so binding a host port would collide with every other student. Coolify's Traefik routes to the container directly. Locally, `docker-compose.override.yml` adds the `ports:` mapping that puts it on `localhost:8000`.

**How `hello` gets its public URL.** Referencing `${SERVICE_FQDN_HELLO}` in the compose file is what tells Coolify to generate a domain and wire up Traefik. Don't declare that variable — just reference it. The name follows the service (`hello` → `SERVICE_FQDN_HELLO`).

**Startup order.** `hello` declares `depends_on` with `condition: service_healthy` for both `time` and `db`, so it won't start until Postgres is accepting connections and the sidecar answers. That's what makes a cold `docker compose up` reliable instead of a race.

**Environment variables** (all set in `docker-compose.yaml`):

| Variable | Service | Purpose |
|---|---|---|
| `DATABASE_URL` | `hello` | `postgresql://appuser:apppass@db:5432/appdb` |
| `APP_URL` | `hello` | Set to `${SERVICE_FQDN_HELLO}` — the reference that triggers Coolify's routing |
| `ALLOW_ADMIN_RESET` | `hello` | Gates `POST /admin/reset`. Set only in `docker-compose.override.yml`, so the destructive endpoint is local-only by default |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `db` | `appuser` / `apppass` / `appdb` |

## Endpoints

Every example below is runnable. Locally the base URL is `http://localhost:8000`; deployed it's your Coolify domain. Set it once:

```bash
BASE=http://localhost:8000
# BASE=http://<your-repo>-staging.ml-capstone.cs.byu.edu    # deployed staging (VPN)
```

### `GET /` — greeting

```bash
curl -s $BASE/
# {"hello":"Hello, world"}

curl -s "$BASE/?lang=es"
# {"hello":"Hola, mundo"}
```

Takes an optional `?lang=` of `en`, `es`, `fr`, `de`, or `ja`. An unsupported code falls back to English rather than erroring.

### `GET /languages` — what `?lang=` accepts

```bash
curl -s $BASE/languages
# {"supported":["de","en","es","fr","ja"]}
```

### `GET /health` — liveness + version

```bash
curl -s $BASE/health
# {"ok":true,"version":"0.1.1"}
```

**This endpoint gates your deploys.** Coolify polls it after starting a new container: 200 and the new version takes over, non-200 and the old container keeps serving. Bump `APP_VERSION` in `hello/greetings.py` and you can watch a deploy land by curling this.

### `GET /time` — proxied from the sidecar

```bash
curl -s $BASE/time
# {"from_time_service":{"utc":"2026-09-23T22:18:04.336421+00:00"}}
```

`hello` calls `http://time:8001/now` over the Compose network. If this works, service-to-service networking works.

### `GET /notes` — read the database

```bash
curl -s $BASE/notes
# []                      (empty until you POST one)
# [{"id":1,"body":"first note","created_at":"2026-09-23T22:18:04.470242+00:00"}]
```

### `POST /notes` — write to the database

```bash
curl -s -X POST $BASE/notes \
  -H 'Content-Type: application/json' \
  -d '{"body":"first note"}'
# {"id":1,"body":"first note","created_at":"2026-09-23T22:18:04.470242+00:00"}
```

Returns **201 Created**. `body` is required — omitting it gives FastAPI's validation error:

```bash
curl -s -X POST $BASE/notes -H 'Content-Type: application/json' -d '{}'
# HTTP 422
# {"detail":[{"type":"missing","loc":["body","body"],"msg":"Field required","input":{}}]}
```

Rows survive `docker compose down` and every redeploy, because they live on the `db-data` volume — that is the point of this endpoint existing.

### `POST /admin/reset` — drop and recreate the table

```bash
curl -s -X POST $BASE/admin/reset
# {"ok":true,...}                                                      (local, env var set)
# {"detail":"admin reset disabled; set ALLOW_ADMIN_RESET=true to enable"}   -> HTTP 403
```

**Destructive — it drops the `notes` table and every row in it.** Gated behind `ALLOW_ADMIN_RESET=true`, which only `docker-compose.override.yml` sets, so it is local-only unless you deliberately add the variable in Coolify. Useful for resetting state while working on migrations; not something to leave enabled on a deployed app.

## Smoke test

```bash
./smoke-test.sh                                             # local: builds + starts + tests
./smoke-test.sh http://your-app.ml-capstone.cs.byu.edu      # remote: tests a deployed instance
```

Or run without Docker:

```bash
cd hello
pip install -r requirements.txt
uvicorn main:app --reload
```

Then `curl http://127.0.0.1:8000/` and `curl http://127.0.0.1:8000/health`.

## Unit tests

```bash
pip install fastapi 'uvicorn[standard]' pydantic httpx pytest
pytest tests/ -v
```

## Deploy

This app is deploy-ready for the ml-capstone cluster. Steps:

1. Fork or copy this directory into your team's GitHub repo.
2. Follow **`student-guide.md` → Part B → Setup: Create your repo, then sign in and create your Coolify Applications** (in the top-level of `ml-capstone-platform`) to wire up the Coolify Applications + GitHub secrets.
3. Push to `staging` branch → GitHub Actions runs unit tests → fires the Coolify staging webhook → your app is live at `http://<your-repo>-staging.ml-capstone.cs.byu.edu`.
4. Merge `staging` → `main` → same flow to prod at `http://<your-repo>.ml-capstone.cs.byu.edu`.

> **`http://`, not `https://`.** The CS wildcard certificate covers one level under `cs.byu.edu`, and these hostnames are two levels deep, so student apps are routed on the HTTP entrypoint only. An `https://` request gets `503 no available server` rather than a certificate warning. Traffic is encrypted at the VPN layer.
>
> The hostname comes from your **repository name**, not your team name.

Bump `APP_VERSION` in `greetings.py` on each meaningful change so you can eyeball `/health` after a deploy and confirm it's the new build.

## Provisioning with Terraform

`terraform/` creates everything on the Coolify side in one command: the Project, both Environments, both Applications (with auto-deploy off, since GitHub Actions drives deploys), and all three GitHub Actions secrets. It's the alternative to clicking through Steps 4–9 of the student guide.

### What you need first

1. **Terraform 1.5+** — `brew install hashicorp/tap/terraform`, `winget install -e --id Hashicorp.Terraform`, or [the Linux packages](https://developer.terraform.io/terraform/install).
2. **A Coolify API token.** Switch to *your own team* in Coolify's team switcher first — the token is scoped to whichever team is active, and that decides where your Applications get created. Then Coolify wordmark → **Keys & Tokens → API Tokens → + New Token**, permissions **`write`** and **`deploy`**. Copy it immediately; it's shown once. (There's no `root` option outside the instructor's Root Team, and you don't need one.)
3. **A GitHub token** with `repo` scope — `gh auth token` if you have the GitHub CLI.
4. **Your Coolify server UUID.** Every team has its own server record — all named `ml-capstone`, all pointing at the same machine, each with a different UUID — so there's no shared value:

   ```bash
   curl -H "Authorization: Bearer <your-coolify-token>" \
     https://ml-capstone-admin.cs.byu.edu/api/v1/servers
   ```

   Exactly one comes back. Copy its `uuid`.

### Run it

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars        # fill in the four values above

terraform init                  # downloads providers, verifies against the lock file
terraform plan                  # READ THIS before applying
terraform apply                 # type: yes
```

`plan` should end with **`Plan: 7 to add, 0 to change, 0 to destroy`**. Reading it before applying is most of the point of using Terraform at all — you get to see exactly what will happen while it's still free to change your mind.

The outputs give you both URLs and the Application UUIDs.

### What it created

| Resource | Where to see it |
|---|---|
| `coolify_project` | Coolify → your team → Projects |
| `coolify_environment` ×2 | inside that project: `production` and `staging` |
| `coolify_application` ×2 | one per environment, tracking `main` and `staging` |
| `github_actions_secret` ×3 | GitHub → repo → Settings → Secrets and variables → Actions |

### The one manual step

**Terraform cannot set your domains.** Coolify's API won't accept per-service domains on a Docker Compose application, so for each of the two Applications: **Access → gear icon on "1 configured domain"** (or the **Domains** tab) → under service `hello`, set `http://<your-repo>-staging.ml-capstone.cs.byu.edu` (or the prod equivalent) → **Save**. Delete the auto-generated `sslip.io` placeholder and the `www.` variant.

Do this **before** your first deploy. Traefik bakes its routing labels into a container when it starts, so a domain added afterwards leaves your URL returning `404 page not found` until you hit **Redeploy**.

### Files

| File | What it's for |
|---|---|
| `main.tf` | The resources themselves — read this one to see what maps to what in the UI |
| `variables.tf` | Every input, what it means, and which have class defaults |
| `outputs.tf` | What gets printed after `apply` |
| `terraform.tfvars.example` | Copy to `terraform.tfvars` and fill in |
| `.terraform.lock.hcl` | Pins exact provider versions + checksums. **Committed on purpose** so everyone gets identical providers |
| `.gitignore` | Keeps `terraform.tfvars` (real tokens) and `*.tfstate` out of git |

`terraform.tfvars` holds two live credentials. It's gitignored — never commit it.

### Tearing it down

```bash
terraform destroy
```

Removes the Project, both Applications, and the three GitHub secrets. Your repo and its code are untouched. See [`terraform/README.md`](terraform/README.md) for the deeper walkthrough, including why the domain step resists automation.
