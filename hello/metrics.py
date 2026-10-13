from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from models import Project, Sprint, SprintStory, UserStory

PRIORITY_WEIGHTS = {
    "Low": Decimal("1"),
    "Medium": Decimal("2"),
    "High": Decimal("3"),
    "Critical": Decimal("4"),
}


def percentage(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def story_completion(story: UserStory) -> Decimal:
    if story.status == "Complete" and story.completion_percent == 0:
        return Decimal("100")
    return Decimal(story.completion_percent)


def project_completion(project: Project) -> Decimal:
    weighted_total = Decimal("0")
    weighted_completed = Decimal("0")
    for story in project.stories:
        weight = Decimal(story.estimated_time) * PRIORITY_WEIGHTS.get(story.priority, Decimal("1"))
        weighted_total += weight
        weighted_completed += weight * story_completion(story) / Decimal("100")
    if weighted_total == 0:
        return Decimal("0.00")
    return percentage(weighted_completed / weighted_total * Decimal("100"))


def story_risk(story: UserStory, current_date: date) -> tuple[bool, bool]:
    excluded = story.status in {"Complete", "Obsolete"}
    overdue = not excluded and current_date > story.due_date
    at_risk = not excluded and current_date <= story.due_date <= current_date + timedelta(days=2)
    return overdue, at_risk


def project_metrics(project: Project, current_date: date) -> dict:
    overdue = 0
    at_risk = 0
    for story in project.stories:
        is_overdue, is_at_risk = story_risk(story, current_date)
        overdue += int(is_overdue)
        at_risk += int(is_at_risk)
    midpoint = project.start_date + (project.due_date - project.start_date) / 2
    completion = project_completion(project)
    return {
        "project_id": project.id,
        "completion_percent": completion,
        "overdue_story_count": overdue,
        "at_risk_story_count": at_risk,
        "midpoint_at_risk": current_date >= midpoint and completion < Decimal("50.00"),
    }


def sprint_metrics(sprint: Sprint, current_date: date) -> dict:
    associations = list(sprint.stories)
    planned_hours = sum((Decimal(item.planned_estimated_time) for item in associations), Decimal("0.00"))
    if sprint.status == "closed":
        completed = [item for item in associations if item.completed_at is not None]
    else:
        completed = [item for item in associations if item.story.status == "Complete"]
    completed_hours = sum((Decimal(item.planned_estimated_time) for item in completed), Decimal("0.00"))
    return {
        "sprint_id": sprint.id,
        "status": sprint.status,
        "planned_story_count": len(associations),
        "completed_story_count": len(completed),
        "planned_estimated_hours": planned_hours.quantize(Decimal("0.01")),
        "completed_estimated_hours": completed_hours.quantize(Decimal("0.01")),
        "velocity_eligible": sprint.status not in {"paused", "archived"},
        "risk": sprint.status not in {"paused", "closed", "archived"} and current_date > sprint.end_date and len(completed) < len(associations),
    }
