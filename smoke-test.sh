#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ "$#" -eq 0 ]; then
    BASE_URL="http://localhost:8000"
    export SERVICE_FQDN_HELLO="$BASE_URL"
    docker compose down --remove-orphans >/dev/null 2>&1 || true
    docker compose up -d --build
else
    BASE_URL="${1%/}"
fi

SMOKE_USERNAME="${SMOKE_USERNAME:?Set SMOKE_USERNAME to a Team Lead account}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:?Set SMOKE_PASSWORD to the Team Lead password}"

echo "Waiting for $BASE_URL/health"
for _ in $(seq 1 60); do
    if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

curl -fsS "$BASE_URL/version"
echo
curl -fsS "$BASE_URL/health"
echo

COOKIE_JAR="${TMPDIR:-/tmp}/culdesac-smoke-cookies.txt"
trap 'rm -f "$COOKIE_JAR"' EXIT

curl -fsS -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
    -X POST "$BASE_URL/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"$SMOKE_USERNAME\",\"password\":\"$SMOKE_PASSWORD\"}" >/dev/null

PROJECT_NAME="smoke-test-$(date +%s)"
PROJECT_RESPONSE=$(curl -fsS -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
    -X POST "$BASE_URL/api/v1/projects" \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"$PROJECT_NAME\",\"due_date\":\"2030-12-31\"}")
PROJECT_ID=$(printf '%s' "$PROJECT_RESPONSE" | grep -oE '"id":"[^"]+"' | head -1 | cut -d'"' -f4)
[ -n "$PROJECT_ID" ]

STORY_RESPONSE=$(curl -fsS -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
    -X POST "$BASE_URL/api/v1/projects/$PROJECT_ID/stories" \
    -H 'Content-Type: application/json' \
    -d '{"title":"Smoke test story","due_date":"2030-12-30"}')
STORY_ID=$(printf '%s' "$STORY_RESPONSE" | grep -oE '"id":"[^"]+"' | head -1 | cut -d'"' -f4)
[ -n "$STORY_ID" ]

SPRINT_RESPONSE=$(curl -fsS -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
    -X POST "$BASE_URL/api/v1/projects/$PROJECT_ID/sprints" \
    -H 'Content-Type: application/json' \
    -d '{"goal":"Smoke test sprint","start_date":"2030-01-01","end_date":"2030-01-14"}')
SPRINT_ID=$(printf '%s' "$SPRINT_RESPONSE" | grep -oE '"id":"[^"]+"' | head -1 | cut -d'"' -f4)
[ -n "$SPRINT_ID" ]

curl -fsS -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
    -X POST "$BASE_URL/api/v1/sprints/$SPRINT_ID/stories" \
    -H 'Content-Type: application/json' \
    -d "{\"story_id\":\"$STORY_ID\"}" >/dev/null

curl -fsS -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE_URL/api/v1/sprints/$SPRINT_ID" | grep -q "$STORY_ID"
echo "database-backed project, story, and sprint write/read passed"
