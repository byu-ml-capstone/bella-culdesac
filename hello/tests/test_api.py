import json
from unittest.mock import MagicMock, patch

import psycopg
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Basic routes — no external dependencies
# ---------------------------------------------------------------------------


def test_hello_default():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json() == {"hello": "Hello, world"}


def test_hello_spanish():
    r = client.get("/", params={"lang": "es"})
    assert r.status_code == 200
    assert r.json() == {"hello": "Hola, mundo"}


def test_hello_unknown_lang_falls_back_to_default():
    r = client.get("/", params={"lang": "xx"})
    assert r.status_code == 200
    assert r.json() == {"hello": "Hello, world"}


def test_languages_lists_all_supported():
    r = client.get("/languages")
    assert r.status_code == 200
    body = r.json()
    assert "en" in body["supported"]
    assert "es" in body["supported"]


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body


# ---------------------------------------------------------------------------
# /time — mocks the network call to the sidecar
# ---------------------------------------------------------------------------


def test_time_endpoint_wraps_response_from_time_sidecar():
    # The /time endpoint calls http://time:8001/now, which only resolves
    # when docker compose is running. Mock the underlying urlopen so
    # tests don't need the sidecar container up.
    fake_body = json.dumps({"utc": "2026-08-20T12:34:56+00:00"}).encode()
    fake_response = MagicMock()
    fake_response.read.return_value = fake_body
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with patch("main.urllib.request.urlopen", return_value=fake_response):
        r = client.get("/time")

    assert r.status_code == 200
    assert r.json() == {"from_time_service": {"utc": "2026-08-20T12:34:56+00:00"}}


# ---------------------------------------------------------------------------
# /notes — mocks at the DAO boundary. This is the payoff of extracting
# NotesDAO: tests describe what the ROUTE does with DAO results, without
# entangling psycopg's cursor / context-manager mocking noise.
# ---------------------------------------------------------------------------


def test_notes_list_returns_dao_output():
    fake_rows = [
        {"id": 1, "body": "first", "created_at": "2026-08-20T12:00:00+00:00"},
        {"id": 2, "body": "second", "created_at": "2026-08-20T12:01:00+00:00"},
    ]
    with patch.object(main.notes_dao, "list_all", return_value=fake_rows):
        r = client.get("/notes")
    assert r.status_code == 200
    assert r.json() == fake_rows


def test_notes_create_returns_dao_output():
    fake_row = {
        "id": 42,
        "body": "hello persistence",
        "created_at": "2026-08-20T12:00:00+00:00",
    }
    with patch.object(main.notes_dao, "insert", return_value=fake_row) as m:
        r = client.post("/notes", json={"body": "hello persistence"})
    assert r.status_code == 201
    assert r.json() == fake_row
    m.assert_called_once_with("hello persistence")


def test_notes_list_returns_503_when_db_unreachable():
    with patch.object(
        main.notes_dao, "list_all", side_effect=psycopg.OperationalError("boom")
    ):
        r = client.get("/notes")
    assert r.status_code == 503
    assert "db unreachable" in r.json()["detail"]


# ---------------------------------------------------------------------------
# /admin/reset — env-gated destructive endpoint
# ---------------------------------------------------------------------------


def test_admin_reset_forbidden_when_disabled():
    with patch.object(main, "ADMIN_RESET_ENABLED", False):
        r = client.post("/admin/reset")
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"]


def test_admin_reset_calls_dao_when_enabled():
    with patch.object(main, "ADMIN_RESET_ENABLED", True), patch.object(
        main.notes_dao, "reset"
    ) as m:
        r = client.post("/admin/reset")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    m.assert_called_once_with()


def test_admin_reset_returns_503_when_db_unreachable():
    with patch.object(main, "ADMIN_RESET_ENABLED", True), patch.object(
        main.notes_dao, "reset", side_effect=psycopg.OperationalError("boom")
    ):
        r = client.post("/admin/reset")
    assert r.status_code == 503
