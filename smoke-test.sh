#!/usr/bin/env bash
# smoke-test.sh — hit every important endpoint and report what came back.
#
# Two modes:
#
#   Local (no argument):
#     ./smoke-test.sh
#     -> builds + starts the full compose stack (hello + time + db),
#        waits for /health on localhost:8000, curls the endpoints,
#        leaves everything running so you can keep poking at it.
#
#   Remote (argument = base URL):
#     ./smoke-test.sh http://<your-app>.ml-capstone.cs.byu.edu
#     -> skips docker compose entirely; curls the endpoints against
#        the given URL. Useful for smoke-testing a Coolify deploy
#        (staging or prod) from your laptop after a push.
#
# Both modes hit / /health /time /notes (GET + POST). The POST
# inserts a test row into the database. Clean up afterwards with
# `curl -X POST <base>/admin/reset` (needs ALLOW_ADMIN_RESET=true).

set -euo pipefail
cd "$(dirname "$0")"

if [ $# -eq 0 ]; then
    MODE=local
    BASE_URL="http://localhost:8000"
else
    MODE=remote
    # Strip a trailing slash so /health etc. don't become //health.
    BASE_URL="${1%/}"
fi

if [ "$MODE" = "local" ]; then
    # Stub SERVICE_FQDN_HELLO for the compose interpolation in
    # docker-compose.yaml. In production Coolify populates this.
    export SERVICE_FQDN_HELLO="$BASE_URL"

    echo "=== local mode: building + starting hello, time, db (docker compose) ==="
    docker compose down --remove-orphans >/dev/null 2>&1 || true
    docker compose up -d --build
else
    echo "=== remote mode: smoke-testing $BASE_URL ==="
fi

# Wait for /health. In local mode the compose build + startup takes a beat;
# in remote mode this catches "did the deploy actually finish yet".
echo -n "waiting for /health "
for _ in $(seq 1 60); do
    if curl -sSf "$BASE_URL/health" >/dev/null 2>&1; then
        echo " ready"
        break
    fi
    echo -n "."
    sleep 1
done

echo
echo "=== GET / ==="
curl -sS "$BASE_URL/"
echo
echo "=== GET /health ==="
curl -sS "$BASE_URL/health"
echo
echo "=== GET /time (proves hello -> time sidecar comms) ==="
curl -sS "$BASE_URL/time"
echo
echo "=== POST /notes (proves hello -> db round-trip; data now persists) ==="
curl -sS -X POST "$BASE_URL/notes" \
    -H 'Content-Type: application/json' \
    -d '{"body":"smoke-test note from smoke-test.sh"}'
echo
echo "=== GET /notes (reads back everything in the notes table) ==="
curl -sS "$BASE_URL/notes"
echo
echo

if [ "$MODE" = "local" ]; then
    echo "All three services are running:"
    echo "  hello → http://localhost:8000 (public API — Traefik-routed in prod)"
    echo "  time  → internal only         (reachable from hello at http://time:8001)"
    echo "  db    → internal Postgres     (reachable from hello at postgres://...@db:5432)"
    echo
    echo "Proof of persistence: POST another /notes row, run 'docker compose down',"
    echo "then 'docker compose up -d' — GET /notes shows every row you inserted."
    echo "Only 'docker compose down -v' (the -v drops volumes) wipes the data."
    echo
    echo "Hit more endpoints, tail logs (docker compose logs -f),"
    echo "or stop everything with:  docker compose down"
else
    echo "Remote smoke test complete: $BASE_URL"
    echo
    echo "The POST above inserted a test row into the deployed database."
    echo "Clean up with:  curl -X POST $BASE_URL/admin/reset"
    echo "(needs ALLOW_ADMIN_RESET=true in the Coolify Application's env vars)"
fi
