import json
import logging
import os
import urllib.error
import urllib.request
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from greetings import APP_VERSION, GREETINGS, get_greeting
from notes_dao import NotesDAO

log = logging.getLogger("uvicorn.error")

# URL of the internal `time` sidecar defined in docker-compose.yaml. `time`
# is the Compose service name — Docker's built-in DNS on the compose network
# resolves it to the sidecar container. Only THIS app is Traefik-routed and
# public; `time` is internal-only.
TIME_SERVICE_URL = "http://time:8001"

# Postgres connection string, injected via docker-compose.yaml. Same
# service-name-as-DNS pattern — `db` resolves to the postgres sidecar
# container on the Compose network. Never publicly reachable.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://appuser:apppass@db:5432/appdb"
)

# All Postgres access goes through the DAO. Routes below stay thin — they
# handle HTTP framing (status codes, error mapping) and delegate the
# actual SQL to NotesDAO methods.
notes_dao = NotesDAO(DATABASE_URL)

# Env-gated admin reset endpoint. Off by default — students opt in via
# ALLOW_ADMIN_RESET=true in the environment (docker-compose.override.yml
# sets it for local; in Coolify you'd add it to the Application's env
# vars, use /admin/reset, then remove it).
ADMIN_RESET_ENABLED = os.environ.get("ALLOW_ADMIN_RESET", "").lower() in (
    "1",
    "true",
    "yes",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup: apply any pending schema migrations.

    Reads hello/migrations/*.sql, runs each file whose name isn't
    already recorded in the `_migrations` tracking table, records
    the newly-applied ones. Same code runs on staging AND production
    on every deploy, so schema stays in sync across environments
    automatically.

    See hello/notes_dao.py apply_migrations() for the implementation.

    OperationalError (db not reachable) is swallowed so /health can
    still respond during a partial outage; /notes will surface 503
    on request.
    """
    try:
        notes_dao.apply_migrations()
    except psycopg.OperationalError as e:
        log.warning("startup: db unreachable, skipping migrations: %s", e)
    yield


app = FastAPI(title="hello-world-app", version=APP_VERSION, lifespan=lifespan)


class HealthResponse(BaseModel):
    ok: bool
    version: str


class NoteIn(BaseModel):
    body: str


@app.get("/")
def hello(lang: str = "en"):
    return {"hello": get_greeting(lang)}


@app.get("/languages")
def languages():
    return {"supported": sorted(GREETINGS.keys())}


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(ok=True, version=APP_VERSION)


@app.get("/time")
def current_time():
    """Fetch the current UTC time from the internal `time` sidecar."""
    try:
        with urllib.request.urlopen(f"{TIME_SERVICE_URL}/now", timeout=3) as resp:
            body = json.loads(resp.read())
        return {"from_time_service": body}
    except urllib.error.URLError as e:
        return {"error": "time service unreachable", "detail": str(e)}


@app.get("/notes")
def list_notes():
    try:
        return notes_dao.list_all()
    except psycopg.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}") from e


@app.post("/notes", status_code=201)
def create_note(note: NoteIn):
    try:
        return notes_dao.insert(note.body)
    except psycopg.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}") from e


@app.post("/admin/reset")
def admin_reset():
    """Drop and recreate the notes table. Destructive.

    Env-gated by ALLOW_ADMIN_RESET so you can't hit this by accident
    on a production Application. To use in Coolify: add
    ALLOW_ADMIN_RESET=true to the Application's Environment Variables,
    redeploy, POST here, then remove the env var. In local dev
    docker-compose.override.yml enables it by default.
    """
    if not ADMIN_RESET_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="admin reset disabled; set ALLOW_ADMIN_RESET=true to enable",
        )
    try:
        notes_dao.reset()
    except psycopg.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"db unreachable: {e}") from e
    return {"ok": True, "message": "notes table dropped and recreated (empty)"}
