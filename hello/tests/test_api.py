from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from main import app
from main import rate_limit_events, enforce_rate_limit
from schemas import ProjectCreate, StoryCreate

client = TestClient(app)


def test_version_is_available_without_database():
    response = client.get("/version")
    assert response.status_code == 200
    assert "version" in response.json()


def test_board_ui_contract_exposes_story_controls_and_explanations():
    response = client.get("/")
    assert response.status_code == 200
    page = response.text
    for marker in (
        'data-side="story-panel"',
        'id="story-assignees"',
        'id="story-status"',
        'data-view="board"',
        'add-stage-story',
        'data-tip=',
        'Backlog',
        'In Progress',
    ):
        assert marker in page


def test_project_creation_schema_requires_due_date():
    project = ProjectCreate(name="Cul-de-sac", due_date=date(2026, 12, 1))
    assert project.start_date is None


def test_story_defaults_match_product_specification():
    story = StoryCreate(title="Implement project setup", due_date=date(2026, 12, 1))
    assert story.priority == "Medium"
    assert story.story_type == "User story"
    assert story.estimated_time == Decimal("1.00")
    assert story.completion_percent == Decimal("0.00")
    assert story.status == "In Progress"
    assert story.assignee_ids == []


def test_unauthenticated_api_errors_use_common_envelope():
    response = client.get("/api/v1/projects", headers={"X-Request-ID": "test-request-1"})
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHENTICATED"
    assert body["request_id"] == "test-request-1"


def test_invalid_login_payload_uses_validation_envelope():
    response = client.post("/auth/login", json={"username": "", "password": "x"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_rate_limiter_returns_retry_after_after_limit():
    key = "test-rate-limit"
    rate_limit_events.pop(key, None)
    enforce_rate_limit(key, maximum=2, window_seconds=60)
    enforce_rate_limit(key, maximum=2, window_seconds=60)
    try:
        enforce_rate_limit(key, maximum=2, window_seconds=60)
    except Exception as exc:
        assert exc.status_code == 429
        assert exc.headers["Retry-After"] == "60"
    else:
        raise AssertionError("expected rate limiter to reject the third request")
    rate_limit_events.pop(key, None)


def test_collection_routes_publish_paginated_contracts():
    schema = app.openapi()["paths"]
    for path in ("/api/v1/projects", "/api/v1/team/members", "/api/v1/workflow-templates", "/api/v1/stories/{story_id}/comments"):
        response = schema[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert response["$ref"].endswith("Page")
