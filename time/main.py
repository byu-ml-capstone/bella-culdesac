"""Minimal internal FastAPI service that returns the current UTC time.

This service is a stand-in for the kind of sidecar you'd add for real work:
a database, a cache, a background worker, a local ML model server. The point
is to show the multi-service pattern — `app` (the public API) reaches this
service by its Compose service name (`time`) over the internal Docker
network. Only `app` is Traefik-routed; this service is internal-only.
"""

from datetime import datetime, timezone
from fastapi import FastAPI

app = FastAPI(title="time-service", version="0.1.0")


@app.get("/")
def root():
    return {"service": "time", "hint": "GET /now for the current UTC time"}


@app.get("/now")
def now():
    return {"utc": datetime.now(timezone.utc).isoformat()}


@app.get("/health")
def health():
    return {"ok": True}
