from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from auth import password_hash
from database import SessionLocal, database_ready
from main import app
from models import AppSession, Project, TeamMember


@pytest.fixture
def role_members():
    if os.getenv("RUN_DB_TESTS") != "1":
        pytest.skip("set RUN_DB_TESTS=1 to run PostgreSQL integration tests")
    if not database_ready():
        pytest.skip("PostgreSQL is not available")

    suffix = uuid.uuid4().hex[:10]
    password = "integration-password-1!"
    members = [
        TeamMember(name="Integration Member", email=f"member-{suffix}@example.com", username=f"member_{suffix}", password_hash=password_hash.hash(password), role="Team Member"),
        TeamMember(name="Integration Faculty", email=f"faculty-{suffix}@example.com", username=f"faculty_{suffix}", password_hash=password_hash.hash(password), role="Faculty Advisor"),
    ]
    with SessionLocal() as db:
        db.add_all(members)
        db.commit()
        for member in members:
            db.refresh(member)
    yield members, password

    with SessionLocal() as db:
        member_ids = [member.id for member in members]
        project_ids = list(db.scalars(select(Project.id).where(Project.name == f"Integration Project {suffix}")))
        if project_ids:
            db.execute(delete(Project).where(Project.id.in_(project_ids)))
        db.execute(delete(AppSession).where(AppSession.member_id.in_(member_ids)))
        db.execute(delete(TeamMember).where(TeamMember.id.in_(member_ids)))
        db.commit()


def login(client: TestClient, member: TeamMember, password: str) -> None:
    response = client.post("/auth/login", json={"username": member.username, "password": password})
    assert response.status_code == 200


def test_roles_and_project_permissions(role_members):
    members, password = role_members
    member, faculty = members
    with TestClient(app) as client:
        login(client, faculty, password)
        listed = client.get("/api/v1/projects?page=1&page_size=10")
        assert listed.status_code == 200
        assert listed.json()["page"] == 1
        assert listed.json()["page_size"] == 10
        assert isinstance(listed.json()["items"], list)
        denied = client.post("/api/v1/projects", json={"name": "Faculty Project", "due_date": "2030-12-31"})
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "FORBIDDEN"

        client.post("/auth/logout")
        login(client, member, password)
        created = client.post("/api/v1/projects", json={"name": f"Integration Project {member.username.split('_', 1)[1]}", "due_date": "2030-12-31"})
        assert created.status_code == 201
        assert created.json()["workflow_statuses"]
        project = created.json()
        updated = client.patch(f"/api/v1/projects/{project['id']}", json={"description": "Updated in integration test", "version": project["version"]})
        assert updated.status_code == 200
        assert updated.json()["description"] == "Updated in integration test"
        completed = client.post(f"/api/v1/projects/{project['id']}/complete")
        assert completed.status_code == 200
        assert completed.json()["status"] == "complete"
        archived = client.post(f"/api/v1/projects/{project['id']}/archive")
        assert archived.status_code == 200
        assert archived.json()["status"] == "archived"


def test_role_guards_and_story_lifecycle(role_members):
    members, password = role_members
    member, faculty = members
    project_name = f"Lifecycle Project {member.username.split('_', 1)[1]}"
    with TestClient(app) as client:
        login(client, member, password)
        project = client.post("/api/v1/projects", json={"name": project_name, "due_date": "2030-12-31"}).json()
        project_id = project["id"]

        members_response = client.get("/api/v1/team/members")
        assert members_response.status_code == 200
        assert all("password_hash" not in item for item in members_response.json()["items"])

        future_story = client.post(
            f"/api/v1/projects/{project_id}/stories",
            json={"title": "Future story", "start_date": "2030-01-01", "due_date": "2030-01-31", "assignee_ids": [str(member.id)]},
        )
        assert future_story.status_code == 201
        assert future_story.json()["status"] == "In Progress"
        assert future_story.json()["assignee_ids"] == [str(member.id)]
        future_story_id = future_story.json()["id"]

        invalid_assignee = client.post(
            f"/api/v1/projects/{project_id}/stories",
            json={"title": "Invalid assignment", "start_date": "2030-01-01", "due_date": "2030-01-31", "assignee_ids": [str(uuid.uuid4())]},
        )
        assert invalid_assignee.status_code == 422
        assert invalid_assignee.json()["error"]["code"] == "VALIDATION_ERROR"

        rejected_upload = client.post(
            f"/api/v1/stories/{future_story_id}/attachments",
            files={"file": ("payload.exe", b"not an image", "application/x-msdownload")},
        )
        assert rejected_upload.status_code == 422
        assert rejected_upload.json()["error"]["code"] == "VALIDATION_ERROR"

        sprint = client.post(
            f"/api/v1/projects/{project_id}/sprints",
            json={"goal": "Future sprint", "start_date": "2030-02-01", "end_date": "2030-02-14"},
        )
        assert sprint.status_code == 201
        sprint_id = sprint.json()["id"]
        assert client.post(f"/api/v1/sprints/{sprint_id}/stories", json={"story_id": future_story_id}).status_code == 201

        client.post("/auth/logout")
        login(client, faculty, password)
        assert client.post(
            f"/api/v1/projects/{project_id}/sprints",
            json={"goal": "Faculty cannot plan", "start_date": "2030-03-01", "end_date": "2030-03-07"},
        ).status_code == 403
        assert client.patch(
            f"/api/v1/stories/{future_story_id}/status",
            json={"status": "In Progress"},
        ).status_code == 403

        client.post("/auth/logout")
        login(client, member, password)
        assert client.delete(f"/api/v1/stories/{future_story_id}").status_code == 204
        assert client.delete(f"/api/v1/sprints/{sprint_id}").status_code == 204

        obsolete_story = client.post(
            f"/api/v1/projects/{project_id}/stories",
            json={"title": "Restorable story", "start_date": "2030-04-01", "due_date": "2030-04-30"},
        ).json()
        story_id = obsolete_story["id"]
        marked = client.patch(
            f"/api/v1/stories/{story_id}/status",
            json={"status": "Obsolete", "reason_comment": "No longer needed"},
        )
        assert marked.status_code == 200
        restored = client.post(f"/api/v1/stories/{story_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["status"] == "Backlog"
        assert restored.json()["completion_percent"] == "0.00"
        assert client.delete(f"/api/v1/stories/{story_id}").status_code == 204
