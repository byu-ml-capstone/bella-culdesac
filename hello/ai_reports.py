from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

import httpx
from pydantic import BaseModel, Field

from config import settings
from models import Sprint


class ReportStory(BaseModel):
    story_id: str
    title: str
    status: str
    estimated_hours: Decimal


class ReportContent(BaseModel):
    sprint_goal: str
    completed_work: list[ReportStory] = []
    next_sprint_goals: list[str] = []
    blockers: list[str] = []
    faculty_notes: list[str] = []


def report_source(sprint: Sprint, additional_context: str | None) -> dict:
    return {
        "sprint": {
            "id": str(sprint.id),
            "goal": sprint.goal,
            "start_date": sprint.start_date.isoformat(),
            "end_date": sprint.end_date.isoformat(),
            "status": sprint.status,
        },
        "project": {"id": str(sprint.project_id), "name": sprint.project.name},
        "stories": [
            {
                "id": str(link.story.id),
                "title": link.story.title,
                "status": link.story.status,
                "estimated_hours": str(link.planned_estimated_time),
                "completion_percent": str(link.story.completion_percent),
            }
            for link in sprint.stories
        ],
        "additional_context": additional_context or "",
    }


def source_hash(source: dict) -> str:
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()


def mock_report(source: dict) -> ReportContent:
    stories = source["stories"]
    completed = [ReportStory(story_id=s["id"], title=s["title"], status=s["status"], estimated_hours=Decimal(s["estimated_hours"])) for s in stories if s["status"] == "Complete"]
    incomplete = [s["title"] for s in stories if s["status"] not in {"Complete", "Obsolete"}]
    blockers = [f"Story remains {s['status']}: {s['title']}" for s in stories if s["status"] == "Paused"]
    return ReportContent(
        sprint_goal=source["sprint"]["goal"],
        completed_work=completed,
        next_sprint_goals=incomplete,
        blockers=blockers,
        faculty_notes=["Draft generated from the selected sprint data; review before finalizing."],
    )


def provider_report(source: dict) -> ReportContent:
    if settings.ai_provider == "mock":
        return mock_report(source)
    prompt = "Return JSON only matching this schema: sprint_goal:string, completed_work:[{story_id,title,status,estimated_hours}], next_sprint_goals:[string], blockers:[string], faculty_notes:[string]. Use only the supplied source data.\nSOURCE:\n" + json.dumps(source, sort_keys=True)
    request = {"model": settings.litellm_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    try:
        with httpx.Client(timeout=settings.ai_timeout_seconds) as client:
            response = client.post(f"{settings.litellm_base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {settings.litellm_api_key}"}, json=request)
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
        return ReportContent.model_validate_json(raw)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("AI report provider returned an invalid or unavailable response") from exc
