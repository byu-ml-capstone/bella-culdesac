from __future__ import annotations

import logging
import json
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import SESSION_COOKIE, create_session, current_member, password_hash, require_editor, require_team_lead
from config import settings
from database import database_ready, get_db, hash_token, initialize_database, reset_database, utc_now
from ai_reports import ReportContent, provider_report, report_source, source_hash
from metrics import project_metrics, sprint_metrics
from models import (
    AppSession,
    Attachment,
    Conversation,
    ConversationComment,
    Invitation,
    Idea,
    IdeaComment,
    PasswordResetToken,
    Project,
    Sprint,
    SprintStory,
    StoryComment,
    StoryAssignee,
    TeamMember,
    UserStory,
    WorkflowTemplate,
    SprintReport,
    SprintReportComment,
)
from schemas import (
    HealthResponse,
    LoginRequest,
    MemberResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
    StoryCreate,
    StoryResponse,
    StoryUpdate,
    SprintCreate,
    SprintCloseRequest,
    SprintResponse,
    SprintStoryCreate,
    SprintStoryResponse,
    SprintUpdate,
    BoardViewResponse,
    StoryStatusUpdate,
    WorkflowResponse,
    WorkflowUpdate,
    AttachmentResponse,
    CommentCreate,
    CommentResponse,
    CommentUpdate,
    ProjectMetricsResponse,
    SprintMetricsResponse,
    ChangePasswordRequest,
    InvitationAccept,
    InvitationCreate,
    InvitationCreateResponse,
    InvitationResponse,
    MemberUpdate,
    PasswordRecoveryRequest,
    PasswordResetLinkResponse,
    PasswordResetRequest,
    IdeaConversion,
    IdeaCreate,
    IdeaPromotion,
    IdeaResponse,
    IdeaCommentResponse,
    IdeaUpdate,
    ConversationCommentCreate,
    ConversationCommentResponse,
    ConversationCreate,
    ConversationResponse,
    ConversationUpdate,
    WorkflowTemplateCreate,
    WorkflowTemplateResponse,
    WorkflowTemplateUpdate,
    ConversationPage,
    CommentPage,
    AttachmentPage,
    IdeaPage,
    IdeaCommentPage,
    InvitationPage,
    MemberPage,
    ProjectPage,
    SprintPage,
    SprintReportPage,
    SprintReportCommentPage,
    StoryPage,
    WorkflowTemplatePage,
    ReportDraftRequest,
    SprintReportResponse,
    SprintReportUpdate,
    SprintReportCommentResponse,
    VersionResponse,
)

log = logging.getLogger("culdesac")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
startup_ready = False
PROTECTED_STATUSES = {"Backlog", "Paused", "Obsolete"}
failed_logins: dict[str, list[float]] = {}
rate_limit_events: dict[str, list[float]] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global startup_ready
    initialize_database()
    startup_ready = True
    yield
    startup_ready = False


app = FastAPI(title="Cul-de-sac API", version=settings.app_version, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


def error_code(status_code: int) -> str:
    return {400: "INVALID_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 422: "VALIDATION_ERROR", 429: "RATE_LIMITED", 503: "DEPENDENCY_UNAVAILABLE"}.get(status_code, "REQUEST_FAILED")


def request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or str(uuid.uuid4())


def enforce_rate_limit(key: str, maximum: int, window_seconds: int) -> None:
    now = time.time()
    events = [stamp for stamp in rate_limit_events.get(key, []) if now - stamp < window_seconds]
    if len(events) >= maximum:
        rate_limit_events[key] = events
        raise HTTPException(
            status_code=429,
            detail="too many requests; try again later",
            headers={"Retry-After": str(window_seconds)},
        )
    events.append(now)
    rate_limit_events[key] = events


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    rid = request_id(request)
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        body = exc.detail
        body.setdefault("request_id", rid)
    else:
        body = {"error": {"code": error_code(exc.status_code), "message": str(exc.detail), "details": {}}, "request_id": rid}
    headers = dict(exc.headers or {})
    headers["X-Request-ID"] = rid
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    rid = request_id(request)
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed.", "details": exc.errors()}, "request_id": rid}, headers={"X-Request-ID": rid})


@app.get("/", include_in_schema=False)
def web_app():
    return FileResponse("static/index.html")


def today() -> date:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(settings.app_timezone)).date()


def project_statuses(project: Project, db: Session) -> list[str]:
    if project.workflow_statuses:
        return list(project.workflow_statuses)
    if project.workflow_template_id:
        template = db.get(WorkflowTemplate, project.workflow_template_id)
        if template:
            return list(template.statuses)
    return ["Backlog", "In Progress", "In Review", "Paused", "Complete", "Obsolete"]


def validate_assignee_ids(assignee_ids: list[UUID], db: Session) -> list[TeamMember]:
    if len(set(assignee_ids)) != len(assignee_ids):
        raise HTTPException(status_code=422, detail="assignee_ids must be unique")
    members = [db.get(TeamMember, member_id) for member_id in assignee_ids]
    if any(not member or member.membership_status != "active" for member in members):
        raise HTTPException(status_code=422, detail="all assignees must be active team members")
    return members


def set_story_assignees(story: UserStory, assignee_ids: list[UUID], db: Session) -> None:
    validate_assignee_ids(assignee_ids, db)
    story.assignee_links.clear()
    story.assignee_links.extend(StoryAssignee(story_id=story.id, member_id=member_id) for member_id in assignee_ids)


def validate_template_statuses(statuses: list[str]) -> list[str]:
    cleaned = [item.strip() for item in statuses]
    if any(not item for item in cleaned) or len(set(cleaned)) != len(cleaned):
        raise HTTPException(status_code=422, detail="workflow statuses must be nonblank and unique")
    if not PROTECTED_STATUSES.issubset(cleaned):
        raise HTTPException(status_code=422, detail="Backlog, Paused, and Obsolete are required protected statuses")
    return cleaned


def pagination_bounds(page: int, page_size: int) -> tuple[int, int]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page must be >= 1 and page_size must be between 1 and 100")
    return (page - 1) * page_size, page_size


def api_error(code: str, message: str, request: Request, details: dict | None = None) -> HTTPException:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": {"code": code, "message": message, "details": details or {}}, "request_id": request_id},
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    if not startup_ready or not database_ready():
        raise HTTPException(status_code=503, detail="service not ready")
    return HealthResponse(ok=True, version=settings.app_version, database="ready")


@app.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(version=settings.app_version)


@app.post("/auth/login", response_model=MemberResponse)
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> TeamMember:
    now = time.monotonic()
    key = f"{request.client.host if request.client else 'unknown'}:{payload.username.lower()}"
    failed_logins[key] = [stamp for stamp in failed_logins.get(key, []) if now - stamp < 900]
    if len(failed_logins[key]) >= 5:
        raise HTTPException(status_code=429, detail="too many failed login attempts; try again later", headers={"Retry-After": "900"})
    member = db.scalar(select(TeamMember).where(TeamMember.username == payload.username))
    if not member or member.membership_status != "active" or not password_hash.verify(payload.password, member.password_hash):
        failed_logins.setdefault(key, []).append(now)
        raise HTTPException(status_code=401, detail="invalid credentials")
    failed_logins.pop(key, None)
    token = create_session(db, member)
    response.set_cookie(SESSION_COOKIE, token, max_age=86400, httponly=True, secure=settings.app_env != "local", samesite="lax")
    return member


@app.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        from database import hash_token
        from models import AppSession

        session = db.scalar(select(AppSession).where(AppSession.token_hash == hash_token(token)))
        if session:
            session.revoked_at = utc_now()
            db.commit()
    response.delete_cookie(SESSION_COOKIE)


@app.get("/auth/me", response_model=MemberResponse)
def me(member: TeamMember = Depends(current_member)) -> TeamMember:
    return member


@app.post("/auth/password-recovery", status_code=202)
def password_recovery(request: Request, _payload: PasswordRecoveryRequest):
    client_key = request.client.host if request.client else "unknown"
    enforce_rate_limit(f"password-recovery:{client_key}:{_payload.username.lower()}", 3, 3600)
    return {"ok": True, "message": "If the account exists, ask a Team Lead to provide a reset link."}


@app.post("/auth/change-password", status_code=204)
def change_password(payload: ChangePasswordRequest, request: Request, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)) -> None:
    if not password_hash.verify(payload.current_password, member.password_hash):
        raise HTTPException(status_code=401, detail="current password is invalid")
    member.password_hash = password_hash.hash(payload.new_password)
    token = request.cookies.get(SESSION_COOKIE)
    for session in db.scalars(select(AppSession).where(AppSession.member_id == member.id, AppSession.revoked_at.is_(None))):
        if not token or session.token_hash != hash_token(token):
            session.revoked_at = utc_now()
    db.commit()


@app.post("/auth/password-reset", response_model=MemberResponse)
def password_reset(payload: PasswordResetRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce_rate_limit(f"password-reset:{request.client.host if request.client else 'unknown'}", 3, 3600)
    reset = db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.token_hash == hash_token(payload.recovery_token),
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > utc_now(),
    ))
    if not reset:
        raise HTTPException(status_code=400, detail="invalid or expired recovery token")
    member = db.get(TeamMember, reset.member_id)
    if not member or member.membership_status != "active":
        raise HTTPException(status_code=400, detail="member cannot be recovered")
    member.password_hash = password_hash.hash(payload.new_password)
    reset.used_at = utc_now()
    for session in db.scalars(select(AppSession).where(AppSession.member_id == member.id, AppSession.revoked_at.is_(None))):
        session.revoked_at = utc_now()
    db.commit()
    token = create_session(db, member)
    response.set_cookie(SESSION_COOKIE, token, max_age=86400, httponly=True, secure=settings.app_env != "local", samesite="lax")
    return member


@app.post("/admin/reset")
def admin_reset(_member: TeamMember = Depends(require_team_lead)):
    if not settings.allow_admin_reset:
        raise HTTPException(status_code=403, detail="admin reset disabled")
    reset_database()
    return {"ok": True, "message": "database and attachments reset"}


def create_idea_record(payload: IdeaCreate, member: TeamMember, db: Session, project_id: UUID | None = None) -> Idea:
    idea = Idea(title=payload.title, description=payload.description, tags=payload.tags, scope="project" if project_id else "team", project_id=project_id, created_by=member.id)
    db.add(idea)
    db.commit()
    db.refresh(idea)
    return idea


@app.post("/api/v1/ideas", response_model=IdeaResponse, status_code=201)
def create_team_idea(payload: IdeaCreate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    return create_idea_record(payload, member, db)


@app.post("/api/v1/projects/{project_id}/ideas", response_model=IdeaResponse, status_code=201)
def create_project_idea(project_id: UUID, payload: IdeaCreate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    return create_idea_record(payload, member, db, project_id)


@app.get("/api/v1/ideas", response_model=IdeaPage)
def list_ideas(scope: str | None = None, project_id: UUID | None = None, status_filter: str | None = None, tag: str | None = None, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if scope and scope not in {"team", "project"}:
        raise HTTPException(status_code=422, detail="scope must be team or project")
    query = select(Idea).order_by(Idea.created_at.desc())
    if scope:
        query = query.where(Idea.scope == scope)
    if project_id:
        query = query.where(Idea.project_id == project_id)
    if status_filter:
        if status_filter not in {"parked", "promoted", "converted", "archived"}:
            raise HTTPException(status_code=422, detail="invalid idea status")
        query = query.where(Idea.status == status_filter)
    ideas = [idea for idea in db.scalars(query) if not tag or tag in (idea.tags or [])]
    return {"items": ideas[offset:offset + limit], "page": page, "page_size": page_size, "total": len(ideas)}


@app.get("/api/v1/ideas/{idea_id}", response_model=IdeaResponse)
def get_idea(idea_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    idea = db.get(Idea, idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="idea not found")
    return idea


@app.patch("/api/v1/ideas/{idea_id}", response_model=IdeaResponse)
def update_idea(idea_id: UUID, payload: IdeaUpdate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    idea = db.get(Idea, idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="idea not found")
    if idea.version != payload.version:
        raise HTTPException(status_code=409, detail="idea was changed by another user")
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("status") not in {None, "parked", "archived"}:
        raise HTTPException(status_code=422, detail="promoted and converted idea states are system-managed")
    for key, value in changes.items():
        setattr(idea, key, value)
    idea.version += 1
    db.commit()
    db.refresh(idea)
    return idea


@app.delete("/api/v1/ideas/{idea_id}", status_code=204)
def delete_idea(idea_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    idea = db.get(Idea, idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="idea not found")
    if idea.status in {"promoted", "converted"}:
        raise HTTPException(status_code=409, detail="promoted or converted ideas are retained")
    db.delete(idea)
    db.commit()


@app.get("/api/v1/ideas/{idea_id}/comments", response_model=IdeaCommentPage)
def list_idea_comments(idea_id: UUID, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if not db.get(Idea, idea_id):
        raise HTTPException(status_code=404, detail="idea not found")
    comments = list(db.scalars(select(IdeaComment).where(IdeaComment.idea_id == idea_id).order_by(IdeaComment.created_at)))
    return {"items": comments[offset:offset + limit], "page": page, "page_size": page_size, "total": len(comments)}


@app.post("/api/v1/ideas/{idea_id}/comments", response_model=IdeaCommentResponse, status_code=201)
def create_idea_comment(idea_id: UUID, payload: CommentCreate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    if not db.get(Idea, idea_id):
        raise HTTPException(status_code=404, detail="idea not found")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="comment cannot be blank")
    comment = IdeaComment(idea_id=idea_id, author_id=member.id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@app.patch("/api/v1/ideas/{idea_id}/comments/{comment_id}", response_model=IdeaCommentResponse)
def update_idea_comment(idea_id: UUID, comment_id: UUID, payload: CommentUpdate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    comment = db.scalar(select(IdeaComment).where(IdeaComment.id == comment_id, IdeaComment.idea_id == idea_id))
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.author_id != member.id and member.role != "Team Lead":
        raise HTTPException(status_code=403, detail="only the comment author or a Team Lead may edit it")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="comment cannot be blank")
    comment.body = body
    db.commit()
    db.refresh(comment)
    return comment


@app.delete("/api/v1/ideas/{idea_id}/comments/{comment_id}", status_code=204)
def delete_idea_comment(idea_id: UUID, comment_id: UUID, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    comment = db.scalar(select(IdeaComment).where(IdeaComment.id == comment_id, IdeaComment.idea_id == idea_id))
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.author_id != member.id and member.role != "Team Lead":
        raise HTTPException(status_code=403, detail="only the comment author or a Team Lead may delete it")
    db.delete(comment)
    db.commit()


@app.post("/api/v1/ideas/{idea_id}/promote-to-project", response_model=ProjectResponse, status_code=201)
def promote_idea(idea_id: UUID, payload: IdeaPromotion, member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    idea = db.get(Idea, idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="idea not found")
    if idea.scope != "team" or idea.status != "parked" or idea.promoted_project_id:
        raise HTTPException(status_code=409, detail="idea is not eligible for project promotion")
    start_date = today()
    due_date = payload.due_date or (start_date + timedelta(days=365))
    if due_date < start_date:
        raise HTTPException(status_code=422, detail="due_date cannot precede start_date")
    template = db.get(WorkflowTemplate, payload.workflow_template_id) if payload.workflow_template_id else db.scalar(select(WorkflowTemplate).where(WorkflowTemplate.name == "Standard Sprint"))
    if payload.workflow_template_id and not template:
        raise HTTPException(status_code=422, detail="workflow template not found")
    project = Project(name=payload.name, description=idea.description, vision=payload.vision, scope=payload.scope, start_date=start_date, due_date=due_date, workflow_template_id=template.id if template else None, workflow_statuses=list(template.statuses) if template else None)
    db.add(project)
    db.flush()
    idea.status = "promoted"
    idea.promoted_project_id = project.id
    idea.version += 1
    db.commit()
    db.refresh(project)
    return project


@app.post("/api/v1/ideas/{idea_id}/convert-to-story", response_model=StoryResponse, status_code=201)
def convert_idea_to_story(idea_id: UUID, payload: IdeaConversion, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    idea = db.get(Idea, idea_id)
    project = db.get(Project, payload.project_id)
    if not idea or not project:
        raise HTTPException(status_code=404, detail="idea or project not found")
    if idea.scope != "project" or idea.project_id != project.id:
        raise HTTPException(status_code=422, detail="project idea must belong to the selected project")
    if idea.status in {"converted", "promoted"}:
        raise HTTPException(status_code=409, detail="idea has already been converted")
    due_date = payload.due_date or project.due_date
    start_date = today()
    if due_date < start_date:
        raise HTTPException(status_code=422, detail="due_date cannot precede start_date")
    story = UserStory(project_id=project.id, title=payload.title or idea.title, description=payload.description or idea.description, due_date=due_date, start_date=start_date, source_idea_id=idea.id)
    db.add(story)
    idea.status = "converted"
    idea.version += 1
    db.commit()
    db.refresh(story)
    return story


@app.post("/api/v1/team/members/{member_id}/password-reset-link", response_model=PasswordResetLinkResponse)
def create_password_reset_link(member_id: UUID, _lead: TeamMember = Depends(require_team_lead), db: Session = Depends(get_db)):
    member = db.get(TeamMember, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="member not found")
    raw_token = secrets.token_urlsafe(32)
    expires_at = utc_now() + timedelta(minutes=15)
    db.add(PasswordResetToken(member_id=member.id, token_hash=hash_token(raw_token), expires_at=expires_at))
    db.commit()
    return PasswordResetLinkResponse(reset_link=f"{settings.app_url}/reset-password?token={raw_token}", expires_at=expires_at)


@app.get("/api/v1/team/members", response_model=MemberPage)
def list_members(page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    members = list(db.scalars(select(TeamMember).order_by(TeamMember.name)))
    return {"items": members[offset:offset + limit], "page": page, "page_size": page_size, "total": len(members)}


@app.get("/api/v1/team/members/{member_id}", response_model=MemberResponse)
def get_member(member_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    member = db.get(TeamMember, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="member not found")
    return member


@app.patch("/api/v1/team/members/{member_id}", response_model=MemberResponse)
def update_member(member_id: UUID, payload: MemberUpdate, lead: TeamMember = Depends(require_team_lead), db: Session = Depends(get_db)):
    member = db.get(TeamMember, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="member not found")
    if member.id == lead.id:
        raise HTTPException(status_code=403, detail="Team Leads cannot change their own membership record")
    if payload.role and payload.role not in {"Team Lead", "Team Member", "Faculty Advisor"}:
        raise HTTPException(status_code=422, detail="invalid member role")
    if payload.email and db.scalar(select(TeamMember).where(TeamMember.email == payload.email, TeamMember.id != member.id)):
        raise HTTPException(status_code=409, detail="email is already in use")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(member, key, value)
    db.commit()
    db.refresh(member)
    return member


@app.patch("/api/v1/team/members/{member_id}/deactivate", response_model=MemberResponse)
def deactivate_member(member_id: UUID, lead: TeamMember = Depends(require_team_lead), db: Session = Depends(get_db)):
    member = db.get(TeamMember, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="member not found")
    if member.id == lead.id:
        raise HTTPException(status_code=403, detail="Team Leads cannot deactivate themselves")
    if member.role == "Team Lead" and db.scalar(select(TeamMember).where(TeamMember.role == "Team Lead", TeamMember.membership_status == "active", TeamMember.id != member.id)) is None:
        raise HTTPException(status_code=409, detail="cannot deactivate the last active Team Lead")
    member.membership_status = "inactive"
    db.commit()
    return member


@app.patch("/api/v1/team/members/{member_id}/reactivate", response_model=MemberResponse)
def reactivate_member(member_id: UUID, _lead: TeamMember = Depends(require_team_lead), db: Session = Depends(get_db)):
    member = db.get(TeamMember, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="member not found")
    if member.membership_status == "active":
        raise HTTPException(status_code=409, detail="member is already active")
    member.membership_status = "active"
    db.commit()
    return member


@app.post("/api/v1/team/invitations", response_model=InvitationCreateResponse, status_code=201)
def create_invitation(payload: InvitationCreate, lead: TeamMember = Depends(require_team_lead), db: Session = Depends(get_db)):
    enforce_rate_limit(f"invitations:{lead.id}", 10, 3600)
    if payload.role not in {"Team Lead", "Team Member", "Faculty Advisor"}:
        raise HTTPException(status_code=422, detail="invalid invitation role")
    email = payload.email.lower()
    if db.scalar(select(TeamMember).where(TeamMember.email == email, TeamMember.membership_status == "active")):
        raise HTTPException(status_code=409, detail="email already belongs to an active member")
    if db.scalar(select(Invitation).where(Invitation.email == email, Invitation.status == "pending")):
        raise HTTPException(status_code=409, detail="email already has a pending invitation")
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(email=email, name=payload.name, role=payload.role, token_hash=hash_token(raw_token), expires_at=utc_now() + timedelta(hours=24))
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return InvitationCreateResponse.model_validate({**invitation.__dict__, "invitation_link": f"{settings.app_url}/accept-invitation?invitation_id={invitation.id}&token={raw_token}"})


@app.get("/api/v1/team/invitations", response_model=InvitationPage)
def list_invitations(page: int = 1, page_size: int = 25, _lead: TeamMember = Depends(require_team_lead), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    invitations = list(db.scalars(select(Invitation).order_by(Invitation.created_at.desc())))
    return {"items": invitations[offset:offset + limit], "page": page, "page_size": page_size, "total": len(invitations)}


@app.post("/api/v1/team/invitations/{invitation_id}/accept", response_model=MemberResponse)
def accept_invitation(invitation_id: UUID, token: str, payload: InvitationAccept, response: Response, db: Session = Depends(get_db)):
    invitation = db.get(Invitation, invitation_id)
    if not invitation or invitation.status != "pending" or invitation.token_hash != hash_token(token):
        raise HTTPException(status_code=400, detail="invalid invitation")
    if invitation.expires_at <= utc_now():
        invitation.status = "expired"
        db.commit()
        raise HTTPException(status_code=400, detail="invitation has expired")
    if db.scalar(select(TeamMember).where(TeamMember.username == payload.username)):
        raise HTTPException(status_code=409, detail="username is already in use")
    member = TeamMember(name=invitation.name, email=invitation.email, username=payload.username, password_hash=password_hash.hash(payload.password), role=invitation.role)
    invitation.status = "accepted"
    invitation.accepted_at = utc_now()
    db.add(member)
    db.commit()
    db.refresh(member)
    session_token = create_session(db, member)
    response.set_cookie(SESSION_COOKIE, session_token, max_age=86400, httponly=True, secure=settings.app_env != "local", samesite="lax")
    return member


@app.post("/api/v1/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(payload: ConversationCreate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    if payload.scope not in {"team", "project"}:
        raise HTTPException(status_code=422, detail="scope must be team or project")
    if payload.scope == "project" and (not payload.project_id or not db.get(Project, payload.project_id)):
        raise HTTPException(status_code=422, detail="project conversations require an existing project")
    if payload.scope == "team" and payload.project_id:
        raise HTTPException(status_code=422, detail="team conversations cannot reference a project")
    conversation = Conversation(scope=payload.scope, project_id=payload.project_id, title=payload.title.strip(), body=payload.body.strip(), created_by=member.id)
    if not conversation.title or not conversation.body:
        raise HTTPException(status_code=422, detail="conversation title and body cannot be blank")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@app.get("/api/v1/conversations", response_model=ConversationPage)
def list_conversations(scope: str | None = None, project_id: UUID | None = None, status_filter: str | None = None, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if scope and scope not in {"team", "project"}:
        raise HTTPException(status_code=422, detail="scope must be team or project")
    if status_filter and status_filter not in {"active", "archived"}:
        raise HTTPException(status_code=422, detail="invalid conversation status")
    query = select(Conversation).order_by(Conversation.updated_at.desc())
    if scope:
        query = query.where(Conversation.scope == scope)
    if project_id:
        query = query.where(Conversation.project_id == project_id)
    if status_filter:
        query = query.where(Conversation.status == status_filter)
    conversations = list(db.scalars(query))
    return {"items": conversations[offset:offset + limit], "page": page, "page_size": page_size, "total": len(conversations)}


@app.get("/api/v1/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")
    return conversation


@app.patch("/api/v1/conversations/{conversation_id}", response_model=ConversationResponse)
def update_conversation(conversation_id: UUID, payload: ConversationUpdate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")
    if conversation.version != payload.version:
        raise HTTPException(status_code=409, detail="conversation was changed by another user")
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    if changes.get("status") not in {None, "active", "archived"}:
        raise HTTPException(status_code=422, detail="invalid conversation status")
    for key, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise HTTPException(status_code=422, detail="conversation fields cannot be blank")
        setattr(conversation, key, value)
    conversation.version += 1
    db.commit()
    db.refresh(conversation)
    return conversation


@app.delete("/api/v1/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="conversation not found")
    db.delete(conversation)
    db.commit()


@app.post("/api/v1/conversations/{conversation_id}/comments", response_model=ConversationCommentResponse, status_code=201)
def create_conversation_comment(conversation_id: UUID, payload: ConversationCommentCreate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    if not db.get(Conversation, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    comment = ConversationComment(conversation_id=conversation_id, author_id=member.id, body=payload.body.strip())
    if not comment.body:
        raise HTTPException(status_code=422, detail="comment cannot be blank")
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@app.patch("/api/v1/conversations/{conversation_id}/comments/{comment_id}", response_model=ConversationCommentResponse)
def update_conversation_comment(conversation_id: UUID, comment_id: UUID, payload: ConversationCommentCreate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    comment = db.scalar(select(ConversationComment).where(ConversationComment.id == comment_id, ConversationComment.conversation_id == conversation_id))
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.author_id != member.id and member.role != "Team Lead":
        raise HTTPException(status_code=403, detail="only the comment author or a Team Lead may edit it")
    comment.body = payload.body.strip()
    if not comment.body:
        raise HTTPException(status_code=422, detail="comment cannot be blank")
    db.commit()
    db.refresh(comment)
    return comment


@app.delete("/api/v1/conversations/{conversation_id}/comments/{comment_id}", status_code=204)
def delete_conversation_comment(conversation_id: UUID, comment_id: UUID, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    comment = db.scalar(select(ConversationComment).where(ConversationComment.id == comment_id, ConversationComment.conversation_id == conversation_id))
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.author_id != member.id and member.role != "Team Lead":
        raise HTTPException(status_code=403, detail="only the comment author or a Team Lead may delete it")
    db.delete(comment)
    db.commit()


@app.get("/api/v1/workflow-templates", response_model=WorkflowTemplatePage)
def list_workflow_templates(page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    templates = list(db.scalars(select(WorkflowTemplate).order_by(WorkflowTemplate.protected.desc(), WorkflowTemplate.name)))
    return {"items": templates[offset:offset + limit], "page": page, "page_size": page_size, "total": len(templates)}


@app.get("/api/v1/workflow-templates/{template_id}", response_model=WorkflowTemplateResponse)
def get_workflow_template(template_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    template = db.get(WorkflowTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="workflow template not found")
    return template


@app.post("/api/v1/workflow-templates", response_model=WorkflowTemplateResponse, status_code=201)
def create_workflow_template(payload: WorkflowTemplateCreate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    statuses = validate_template_statuses(payload.statuses)
    if db.scalar(select(WorkflowTemplate).where(WorkflowTemplate.name == payload.name.strip())):
        raise HTTPException(status_code=409, detail="workflow template name is already in use")
    template = WorkflowTemplate(name=payload.name.strip(), statuses=statuses, setup_steps=[step.strip() for step in payload.setup_steps if step.strip()])
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@app.patch("/api/v1/workflow-templates/{template_id}", response_model=WorkflowTemplateResponse)
def update_workflow_template(template_id: UUID, payload: WorkflowTemplateUpdate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    template = db.get(WorkflowTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="workflow template not found")
    if template.version != payload.version:
        raise HTTPException(status_code=409, detail="workflow template was changed by another user")
    if template.protected and payload.name is not None and payload.name.strip() != template.name:
        raise HTTPException(status_code=409, detail="protected workflow template cannot be renamed")
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    if "statuses" in changes:
        changes["statuses"] = validate_template_statuses(changes["statuses"])
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if db.scalar(select(WorkflowTemplate).where(WorkflowTemplate.name == changes["name"], WorkflowTemplate.id != template.id)):
            raise HTTPException(status_code=409, detail="workflow template name is already in use")
    if "setup_steps" in changes:
        changes["setup_steps"] = [step.strip() for step in changes["setup_steps"] if step.strip()]
    for key, value in changes.items():
        setattr(template, key, value)
    template.version += 1
    db.commit()
    db.refresh(template)
    return template


@app.delete("/api/v1/workflow-templates/{template_id}", status_code=204)
def delete_workflow_template(template_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    template = db.get(WorkflowTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="workflow template not found")
    if template.protected:
        raise HTTPException(status_code=409, detail="protected workflow templates cannot be deleted")
    if db.scalar(select(Project).where(Project.workflow_template_id == template.id)) or db.scalar(select(Sprint).where(Sprint.workflow_template_id == template.id)):
        raise HTTPException(status_code=409, detail="workflow template is still used")
    db.delete(template)
    db.commit()


@app.get("/api/v1/projects", response_model=ProjectPage)
def list_projects(page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    projects = list(db.scalars(select(Project).order_by(Project.created_at.desc())))
    return {"items": projects[offset:offset + limit], "page": page, "page_size": page_size, "total": len(projects)}


@app.post("/api/v1/projects", response_model=ProjectResponse, status_code=201)
def create_project(payload: ProjectCreate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    start_date = payload.start_date or today()
    if payload.due_date < start_date:
        raise HTTPException(status_code=422, detail="due_date cannot precede start_date")
    template = db.scalar(select(WorkflowTemplate).where(WorkflowTemplate.name == "Standard Sprint"))
    project = Project(
        name=payload.name,
        start_date=start_date,
        due_date=payload.due_date,
        description=payload.description,
        vision=payload.vision,
        scope=payload.scope,
        tentative_outline=payload.tentative_outline,
        workflow_template_id=template.id if template else None,
        workflow_statuses=list(template.statuses) if template else None,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.patch("/api/v1/projects/{project_id}/workflow", response_model=WorkflowResponse)
def update_project_workflow(project_id: UUID, payload: WorkflowUpdate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    statuses = [status.strip() for status in payload.statuses]
    if any(not status for status in statuses) or len(set(statuses)) != len(statuses):
        raise HTTPException(status_code=422, detail="workflow statuses must be nonblank and unique")
    if not PROTECTED_STATUSES.issubset(statuses):
        raise HTTPException(status_code=422, detail="Backlog, Paused, and Obsolete are protected statuses")
    current = project_statuses(project, db)
    renames = payload.renames
    if any(old not in current or not new.strip() for old, new in renames.items()):
        raise HTTPException(status_code=422, detail="workflow rename references an unknown or blank status")
    if len(set(renames.values())) != len(renames.values()):
        raise HTTPException(status_code=422, detail="workflow rename targets must be unique")
    for old, new in renames.items():
        if old in PROTECTED_STATUSES and old != new:
            raise HTTPException(status_code=422, detail="protected statuses cannot be renamed")
        if old != new and new not in statuses:
            raise HTTPException(status_code=422, detail="renamed status must appear in statuses")
    for story in db.scalars(select(UserStory).where(UserStory.project_id == project_id)):
        if story.status in renames:
            story.status = renames[story.status]
        elif story.status not in statuses:
            story.status = "Backlog"
        story.version += 1
    project.workflow_statuses = statuses
    project.version += 1
    db.commit()
    return WorkflowResponse(project_id=project.id, statuses=statuses, additional_steps=payload.additional_steps)


@app.get("/api/v1/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@app.patch("/api/v1/projects/{project_id}", response_model=ProjectResponse)
def update_project(project_id: UUID, payload: ProjectUpdate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    if project.version != payload.version:
        raise HTTPException(status_code=409, detail="project was changed by another user")
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    start_date = changes.get("start_date", project.start_date)
    due_date = changes.get("due_date", project.due_date)
    if due_date < start_date:
        raise HTTPException(status_code=422, detail="due_date cannot precede start_date")
    if project.status == "archived":
        raise HTTPException(status_code=409, detail="archived projects cannot be edited")
    for key, value in changes.items():
        setattr(project, key, value)
    project.version += 1
    db.commit()
    db.refresh(project)
    return project


@app.post("/api/v1/projects/{project_id}/complete", response_model=ProjectResponse)
def complete_project(project_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    if project.status != "active":
        raise HTTPException(status_code=409, detail="only active projects can be completed")
    project.status = "complete"
    project.version += 1
    db.commit()
    db.refresh(project)
    return project


@app.post("/api/v1/projects/{project_id}/archive", response_model=ProjectResponse)
def archive_project(project_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    if project.status != "complete":
        raise HTTPException(status_code=409, detail="only completed projects can be archived")
    project.status = "archived"
    project.version += 1
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/v1/projects/{project_id}", status_code=204)
def delete_project(project_id: UUID, _lead: TeamMember = Depends(require_team_lead), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    if project.start_date <= today():
        raise HTTPException(status_code=409, detail="started or historical projects must be retained")
    stories = list(db.scalars(select(UserStory).where(UserStory.project_id == project.id)))
    if any(story.start_date <= today() for story in stories):
        raise HTTPException(status_code=409, detail="projects with started stories must be retained")
    sprints = list(db.scalars(select(Sprint).where(Sprint.project_id == project.id)))
    if any(sprint.status != "planned" or sprint.start_date <= today() for sprint in sprints):
        raise HTTPException(status_code=409, detail="projects with active or historical sprints must be retained")

    sprint_ids = [sprint.id for sprint in sprints]
    story_ids = [story.id for story in stories]
    if sprint_ids:
        report_ids = list(db.scalars(select(SprintReport.id).where(SprintReport.sprint_id.in_(sprint_ids))))
        if report_ids:
            db.execute(delete(SprintReportComment).where(SprintReportComment.report_id.in_(report_ids)))
            db.execute(delete(SprintReport).where(SprintReport.id.in_(report_ids)))
        db.execute(delete(SprintStory).where(SprintStory.sprint_id.in_(sprint_ids)))
        db.execute(delete(Sprint).where(Sprint.id.in_(sprint_ids)))
    if story_ids:
        for attachment in db.scalars(select(Attachment).where(Attachment.story_id.in_(story_ids))):
            (settings.attachments_dir / attachment.storage_key).unlink(missing_ok=True)
        db.execute(delete(Attachment).where(Attachment.story_id.in_(story_ids)))
        db.execute(delete(StoryComment).where(StoryComment.story_id.in_(story_ids)))
        db.execute(delete(StoryAssignee).where(StoryAssignee.story_id.in_(story_ids)))
        db.execute(update(UserStory).where(UserStory.id.in_(story_ids)).values(parent_id=None))
        db.execute(delete(UserStory).where(UserStory.id.in_(story_ids)))
    idea_ids = list(db.scalars(select(Idea.id).where(Idea.project_id == project.id)))
    if idea_ids:
        db.execute(delete(IdeaComment).where(IdeaComment.idea_id.in_(idea_ids)))
        db.execute(delete(Idea).where(Idea.id.in_(idea_ids)))
    conversation_ids = list(db.scalars(select(Conversation.id).where(Conversation.project_id == project.id)))
    if conversation_ids:
        db.execute(delete(ConversationComment).where(ConversationComment.conversation_id.in_(conversation_ids)))
        db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
    db.execute(update(Idea).where(Idea.promoted_project_id == project.id).values(promoted_project_id=None, status="parked", version=Idea.version + 1))
    db.delete(project)
    db.commit()


@app.get("/api/v1/projects/{project_id}/stories", response_model=StoryPage)
def list_stories(project_id: UUID, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    stories = list(db.scalars(select(UserStory).where(UserStory.project_id == project_id).order_by(UserStory.created_at.desc())))
    return {"items": stories[offset:offset + limit], "page": page, "page_size": page_size, "total": len(stories)}


@app.post("/api/v1/projects/{project_id}/stories", response_model=StoryResponse, status_code=201)
def create_story(project_id: UUID, payload: StoryCreate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    start_date = payload.start_date or today()
    if payload.due_date < start_date:
        raise HTTPException(status_code=422, detail="due_date cannot precede start_date")
    if payload.parent_id:
        parent = db.get(UserStory, payload.parent_id)
        if not parent or parent.project_id != project_id:
            raise HTTPException(status_code=422, detail="parent story must belong to the project")
    statuses = project_statuses(project, db)
    if payload.status not in statuses:
        raise HTTPException(status_code=422, detail="status is not configured for this project")
    if payload.status in {"Paused", "Obsolete"}:
        raise HTTPException(status_code=422, detail="new stories cannot start in Paused or Obsolete")
    story = UserStory(
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        due_date=payload.due_date,
        start_date=start_date,
        priority=payload.priority,
        story_type=payload.story_type,
        estimated_time=payload.estimated_time,
        completion_percent=payload.completion_percent,
        github_repo_url=str(payload.github_repo_url) if payload.github_repo_url else None,
        notes=payload.notes,
        parent_id=payload.parent_id,
        tags=payload.tags,
        status=payload.status,
    )
    db.add(story)
    db.flush()
    set_story_assignees(story, payload.assignee_ids, db)
    db.commit()
    db.refresh(story)
    return story


@app.get("/api/v1/stories/{story_id}", response_model=StoryResponse)
def get_story(story_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    story = db.get(UserStory, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    return story


@app.get("/api/v1/stories/{story_id}/comments", response_model=CommentPage)
def list_story_comments(story_id: UUID, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if not db.get(UserStory, story_id):
        raise HTTPException(status_code=404, detail="story not found")
    comments = list(db.scalars(select(StoryComment).where(StoryComment.story_id == story_id).order_by(StoryComment.created_at)))
    return {"items": comments[offset:offset + limit], "page": page, "page_size": page_size, "total": len(comments)}


@app.post("/api/v1/stories/{story_id}/comments", response_model=CommentResponse, status_code=201)
def create_story_comment(story_id: UUID, payload: CommentCreate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    if not db.get(UserStory, story_id):
        raise HTTPException(status_code=404, detail="story not found")
    comment = StoryComment(story_id=story_id, author_id=member.id, body=payload.body.strip())
    if not comment.body:
        raise HTTPException(status_code=422, detail="comment cannot be blank")
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@app.patch("/api/v1/stories/{story_id}/comments/{comment_id}", response_model=CommentResponse)
def update_story_comment(story_id: UUID, comment_id: UUID, payload: CommentUpdate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    comment = db.scalar(select(StoryComment).where(StoryComment.id == comment_id, StoryComment.story_id == story_id))
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.author_id != member.id:
        raise HTTPException(status_code=403, detail="only the comment author may edit it")
    comment.body = payload.body.strip()
    if not comment.body:
        raise HTTPException(status_code=422, detail="comment cannot be blank")
    db.commit()
    db.refresh(comment)
    return comment


@app.delete("/api/v1/stories/{story_id}/comments/{comment_id}", status_code=204)
def delete_story_comment(story_id: UUID, comment_id: UUID, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    comment = db.scalar(select(StoryComment).where(StoryComment.id == comment_id, StoryComment.story_id == story_id))
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.author_id != member.id and member.role != "Team Lead":
        raise HTTPException(status_code=403, detail="only the comment author or a Team Lead may delete it")
    db.delete(comment)
    db.commit()


ALLOWED_ATTACHMENT_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain", "text/markdown", "application/zip",
}
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024


@app.get("/api/v1/stories/{story_id}/attachments", response_model=AttachmentPage)
def list_story_attachments(story_id: UUID, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if not db.get(UserStory, story_id):
        raise HTTPException(status_code=404, detail="story not found")
    attachments = list(db.scalars(select(Attachment).where(Attachment.story_id == story_id).order_by(Attachment.created_at)))
    return {"items": attachments[offset:offset + limit], "page": page, "page_size": page_size, "total": len(attachments)}


@app.post("/api/v1/stories/{story_id}/attachments", response_model=AttachmentResponse, status_code=201)
def upload_story_attachment(story_id: UUID, file: UploadFile = File(...), member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    if not db.get(UserStory, story_id):
        raise HTTPException(status_code=404, detail="story not found")
    if file.content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise HTTPException(status_code=422, detail="file type is not permitted")
    original_name = Path(file.filename or "attachment").name[:255]
    storage_key = f"{uuid.uuid4().hex}{Path(original_name).suffix.lower()}"
    destination = settings.attachments_dir / storage_key
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(status_code=413, detail="attachment exceeds the 30 MB limit")
                output.write(chunk)
        attachment = Attachment(story_id=story_id, file_name=original_name, content_type=file.content_type, size_bytes=size, storage_key=storage_key, uploaded_by=member.id)
        db.add(attachment)
        db.commit()
        db.refresh(attachment)
        return attachment
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception:
        destination.unlink(missing_ok=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="attachment could not be saved")


@app.get("/api/v1/stories/{story_id}/attachments/{attachment_id}/download")
def download_story_attachment(story_id: UUID, attachment_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    attachment = db.scalar(select(Attachment).where(Attachment.id == attachment_id, Attachment.story_id == story_id))
    if not attachment:
        raise HTTPException(status_code=404, detail="attachment not found")
    path = settings.attachments_dir / attachment.storage_key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="attachment file not found")
    return FileResponse(path, media_type=attachment.content_type, filename=attachment.file_name)


@app.delete("/api/v1/stories/{story_id}/attachments/{attachment_id}", status_code=204)
def delete_story_attachment(story_id: UUID, attachment_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    attachment = db.scalar(select(Attachment).where(Attachment.id == attachment_id, Attachment.story_id == story_id))
    if not attachment:
        raise HTTPException(status_code=404, detail="attachment not found")
    (settings.attachments_dir / attachment.storage_key).unlink(missing_ok=True)
    db.delete(attachment)
    db.commit()


@app.patch("/api/v1/stories/{story_id}", response_model=StoryResponse)
def update_story(story_id: UUID, payload: StoryUpdate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    story = db.get(UserStory, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    if payload.version != story.version:
        raise HTTPException(status_code=409, detail="story was changed by another user")
    changes = payload.model_dump(exclude_unset=True, exclude={"version", "assignee_ids"})
    if "github_repo_url" in changes and changes["github_repo_url"]:
        changes["github_repo_url"] = str(changes["github_repo_url"])
    for key, value in changes.items():
        setattr(story, key, value)
    if payload.assignee_ids is not None:
        set_story_assignees(story, payload.assignee_ids, db)
    story.version += 1
    db.commit()
    db.refresh(story)
    return story


@app.delete("/api/v1/stories/{story_id}", status_code=204)
def delete_story(story_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    story = db.get(UserStory, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    if story.status == "Obsolete":
        raise HTTPException(status_code=409, detail="obsolete stories are retained and may be restored")
    if story.start_date <= today():
        raise HTTPException(status_code=409, detail="started or historical stories must be marked obsolete")
    if db.scalar(select(UserStory.id).where(UserStory.parent_id == story.id)):
        raise HTTPException(status_code=409, detail="stories with child relationships cannot be deleted")
    sprint_links = list(db.scalars(select(SprintStory).where(SprintStory.story_id == story.id)))
    if any(link.sprint.status != "planned" or link.sprint.start_date <= today() for link in sprint_links):
        raise HTTPException(status_code=409, detail="stories with active or historical sprint participation must be marked obsolete")
    for attachment in db.scalars(select(Attachment).where(Attachment.story_id == story.id)):
        (settings.attachments_dir / attachment.storage_key).unlink(missing_ok=True)
        db.delete(attachment)
    db.execute(delete(StoryComment).where(StoryComment.story_id == story.id))
    db.execute(delete(StoryAssignee).where(StoryAssignee.story_id == story.id))
    db.execute(delete(SprintStory).where(SprintStory.story_id == story.id))
    db.delete(story)
    db.commit()


@app.post("/api/v1/stories/{story_id}/restore", response_model=StoryResponse)
def restore_story(story_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    story = db.get(UserStory, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    if story.status != "Obsolete":
        raise HTTPException(status_code=409, detail="only obsolete stories can be restored")
    story.status = "Backlog"
    story.completion_percent = 0
    story.version += 1
    db.commit()
    db.refresh(story)
    return story


@app.patch("/api/v1/stories/{story_id}/status", response_model=StoryResponse)
def update_story_status(story_id: UUID, payload: StoryStatusUpdate, member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    story = db.get(UserStory, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    project = db.get(Project, story.project_id)
    statuses = project_statuses(project, db)
    if payload.status not in statuses:
        raise HTTPException(status_code=422, detail="status is not configured for this project")
    if payload.status in {"Paused", "Obsolete"} and (not payload.reason_comment or not payload.reason_comment.strip()):
        raise HTTPException(status_code=422, detail="Paused and Obsolete statuses require a reason comment")
    story.status = payload.status
    story.version += 1
    if payload.status == "Complete":
        story.completion_percent = 100
    elif payload.status in {"Backlog", "Obsolete"}:
        story.completion_percent = 0
    if payload.status in {"Paused", "Obsolete"}:
        db.add(StoryComment(story_id=story.id, author_id=member.id, body=payload.reason_comment.strip()))
    db.commit()
    db.refresh(story)
    return story


@app.get("/api/v1/projects/{project_id}/views", response_model=BoardViewResponse)
def project_view(
    project_id: UUID,
    view: str = "board",
    sprint_id: UUID | None = None,
    story_type: str | None = None,
    tag: str | None = None,
    assignee_id: UUID | None = None,
    include_obsolete: bool = False,
    _member: TeamMember = Depends(current_member),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    if view not in {"board", "task", "timeline"}:
        raise HTTPException(status_code=422, detail="view must be board, task, or timeline")
    query = select(UserStory).where(UserStory.project_id == project_id)
    if not include_obsolete:
        query = query.where(UserStory.status != "Obsolete")
    if story_type:
        query = query.where(UserStory.story_type == story_type)
    if tag:
        query = query.where(UserStory.tags.contains([tag]))
    if assignee_id:
        if not db.get(TeamMember, assignee_id):
            raise HTTPException(status_code=422, detail="assignee not found")
        query = query.join(StoryAssignee, StoryAssignee.story_id == UserStory.id).where(StoryAssignee.member_id == assignee_id)
    if sprint_id:
        sprint = db.get(Sprint, sprint_id)
        if not sprint or sprint.project_id != project_id:
            raise HTTPException(status_code=422, detail="sprint must belong to the project")
        query = query.join(SprintStory, SprintStory.story_id == UserStory.id).where(SprintStory.sprint_id == sprint_id)
    if view == "board":
        query = query.order_by(UserStory.status, UserStory.created_at.desc())
    else:
        query = query.order_by(UserStory.due_date, UserStory.created_at.desc())
    return BoardViewResponse(view=view, items=list(db.scalars(query)))


@app.get("/api/v1/projects/{project_id}/metrics", response_model=ProjectMetricsResponse)
def get_project_metrics(project_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    return project_metrics(project, today())


@app.get("/api/v1/sprints/{sprint_id}/metrics", response_model=SprintMetricsResponse)
def get_sprint_metrics(sprint_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    return sprint_metrics(sprint, today())


@app.post("/api/v1/sprints/{sprint_id}/report-draft", response_model=SprintReportResponse, status_code=201)
def generate_report_draft(sprint_id: UUID, payload: ReportDraftRequest, request: Request, member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    enforce_rate_limit(f"report-draft:{member.id}:{request.client.host if request.client else 'unknown'}", 10, 60)
    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    existing = db.scalar(select(SprintReport).where(SprintReport.sprint_id == sprint_id))
    if existing and existing.status != "draft" and not payload.replace_existing_draft:
        raise HTTPException(status_code=409, detail="reviewed or finalized reports require explicit regeneration")
    source = report_source(sprint, payload.additional_context)
    try:
        content = provider_report(source)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    content_json = json.loads(content.model_dump_json())
    if existing:
        existing.content = content_json
        existing.provider = settings.ai_provider
        existing.model = "deterministic-mock" if settings.ai_provider == "mock" else settings.litellm_model
        existing.input_hash = source_hash(source)
        existing.generated_at = utc_now()
        existing.updated_at = utc_now()
        existing.status = "draft"
        existing.version += 1
        report = existing
    else:
        report = SprintReport(sprint_id=sprint_id, content=content_json, status="draft", provider=settings.ai_provider, model="deterministic-mock" if settings.ai_provider == "mock" else settings.litellm_model, input_hash=source_hash(source))
        db.add(report)
    db.commit()
    db.refresh(report)
    return report


@app.post("/api/v1/sprints/{sprint_id}/report-draft/regenerate", response_model=SprintReportResponse)
def regenerate_report_draft(sprint_id: UUID, payload: ReportDraftRequest, request: Request, member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    replacement = payload.model_copy(update={"replace_existing_draft": True})
    return generate_report_draft(sprint_id, replacement, request, member, db)


@app.get("/api/v1/sprints/{sprint_id}/reports", response_model=SprintReportPage)
def list_sprint_reports(sprint_id: UUID, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if not db.get(Sprint, sprint_id):
        raise HTTPException(status_code=404, detail="sprint not found")
    reports = list(db.scalars(select(SprintReport).where(SprintReport.sprint_id == sprint_id)))
    return {"items": reports[offset:offset + limit], "page": page, "page_size": page_size, "total": len(reports)}


@app.get("/api/v1/sprint-reports/{report_id}", response_model=SprintReportResponse)
def get_sprint_report(report_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    report = db.get(SprintReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="sprint report not found")
    return report


@app.patch("/api/v1/sprint-reports/{report_id}", response_model=SprintReportResponse)
def update_sprint_report(report_id: UUID, payload: SprintReportUpdate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    report = db.get(SprintReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="sprint report not found")
    if report.version != payload.version:
        raise HTTPException(status_code=409, detail="report was changed by another user")
    try:
        validated = ReportContent.model_validate(payload.content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="report content does not match the report schema") from exc
    if payload.status not in {None, "draft", "reviewed"}:
        raise HTTPException(status_code=422, detail="invalid report status")
    report.content = json.loads(validated.model_dump_json())
    report.status = payload.status or ("reviewed" if report.status == "finalized" else report.status)
    report.version += 1
    report.updated_at = utc_now()
    db.commit()
    db.refresh(report)
    return report


@app.get("/api/v1/sprint-reports/{report_id}/comments", response_model=SprintReportCommentPage)
def list_sprint_report_comments(report_id: UUID, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if not db.get(SprintReport, report_id):
        raise HTTPException(status_code=404, detail="sprint report not found")
    comments = list(db.scalars(select(SprintReportComment).where(SprintReportComment.report_id == report_id).order_by(SprintReportComment.created_at)))
    return {"items": comments[offset:offset + limit], "page": page, "page_size": page_size, "total": len(comments)}


@app.post("/api/v1/sprint-reports/{report_id}/comments", response_model=SprintReportCommentResponse, status_code=201)
def create_sprint_report_comment(report_id: UUID, payload: CommentCreate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    if not db.get(SprintReport, report_id):
        raise HTTPException(status_code=404, detail="sprint report not found")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="comment cannot be blank")
    comment = SprintReportComment(report_id=report_id, author_id=member.id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@app.patch("/api/v1/sprint-reports/{report_id}/comments/{comment_id}", response_model=SprintReportCommentResponse)
def update_sprint_report_comment(report_id: UUID, comment_id: UUID, payload: CommentUpdate, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    comment = db.scalar(select(SprintReportComment).where(SprintReportComment.id == comment_id, SprintReportComment.report_id == report_id))
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.author_id != member.id and member.role != "Team Lead":
        raise HTTPException(status_code=403, detail="only the comment author or a Team Lead may edit it")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="comment cannot be blank")
    comment.body = body
    db.commit()
    db.refresh(comment)
    return comment


@app.delete("/api/v1/sprint-reports/{report_id}/comments/{comment_id}", status_code=204)
def delete_sprint_report_comment(report_id: UUID, comment_id: UUID, member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    comment = db.scalar(select(SprintReportComment).where(SprintReportComment.id == comment_id, SprintReportComment.report_id == report_id))
    if not comment:
        raise HTTPException(status_code=404, detail="comment not found")
    if comment.author_id != member.id and member.role != "Team Lead":
        raise HTTPException(status_code=403, detail="only the comment author or a Team Lead may delete it")
    db.delete(comment)
    db.commit()


@app.post("/api/v1/sprint-reports/{report_id}/finalize", response_model=SprintReportResponse)
def finalize_sprint_report(report_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    report = db.get(SprintReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="sprint report not found")
    if report.status == "finalized":
        raise HTTPException(status_code=409, detail="report is already finalized")
    report.status = "finalized"
    report.version += 1
    report.updated_at = utc_now()
    db.commit()
    db.refresh(report)
    return report


@app.post("/api/v1/projects/{project_id}/sprints", response_model=SprintResponse, status_code=201)
def create_sprint(project_id: UUID, payload: SprintCreate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    if payload.end_date < payload.start_date:
        raise HTTPException(status_code=422, detail="end_date cannot precede start_date")
    template_id = payload.workflow_template_id or project.workflow_template_id
    if template_id and not db.get(WorkflowTemplate, template_id):
        raise HTTPException(status_code=422, detail="workflow template not found")
    sprint = Sprint(
        project_id=project_id,
        goal=payload.goal,
        start_date=payload.start_date,
        end_date=payload.end_date,
        workflow_template_id=template_id,
    )
    db.add(sprint)
    db.commit()
    db.refresh(sprint)
    return sprint


@app.get("/api/v1/projects/{project_id}/sprints", response_model=SprintPage)
def list_sprints(project_id: UUID, page: int = 1, page_size: int = 25, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    offset, limit = pagination_bounds(page, page_size)
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    sprints = list(db.scalars(select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.start_date.desc())))
    return {"items": sprints[offset:offset + limit], "page": page, "page_size": page_size, "total": len(sprints)}


@app.get("/api/v1/sprints/{sprint_id}", response_model=SprintResponse)
def get_sprint(sprint_id: UUID, _member: TeamMember = Depends(current_member), db: Session = Depends(get_db)):
    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    return sprint


@app.patch("/api/v1/sprints/{sprint_id}", response_model=SprintResponse)
def update_sprint(sprint_id: UUID, payload: SprintUpdate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    if payload.version != sprint.version:
        raise HTTPException(status_code=409, detail="sprint was changed by another user")
    changes = payload.model_dump(exclude_unset=True, exclude={"version"})
    start_date = changes.get("start_date", sprint.start_date)
    end_date = changes.get("end_date", sprint.end_date)
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date cannot precede start_date")
    if "status" in changes and changes["status"] not in {"planned", "active", "paused"}:
        raise HTTPException(status_code=422, detail="invalid sprint status")
    if sprint.status in {"closed", "archived"}:
        raise HTTPException(status_code=409, detail="closed or archived sprints require an explicit reopen operation")
    if "status" in changes:
        allowed = {
            "planned": {"active", "paused"},
            "active": {"planned", "paused"},
            "paused": {"active", "planned"},
        }
        if changes["status"] != sprint.status and changes["status"] not in allowed[sprint.status]:
            raise HTTPException(status_code=409, detail="invalid sprint lifecycle transition")
    for key, value in changes.items():
        setattr(sprint, key, value)
    sprint.version += 1
    db.commit()
    db.refresh(sprint)
    return sprint


@app.post("/api/v1/sprints/{sprint_id}/stories", response_model=SprintStoryResponse, status_code=201)
def add_sprint_story(sprint_id: UUID, payload: SprintStoryCreate, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    sprint = db.get(Sprint, sprint_id)
    story = db.get(UserStory, payload.story_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    if not story:
        raise HTTPException(status_code=404, detail="story not found")
    if story.project_id != sprint.project_id:
        raise HTTPException(status_code=422, detail="story and sprint must belong to the same project")
    if db.scalar(select(SprintStory).where(SprintStory.sprint_id == sprint_id, SprintStory.story_id == payload.story_id)):
        raise HTTPException(status_code=409, detail="story is already assigned to this sprint")
    if sprint.status not in {"planned", "active"}:
        raise HTTPException(status_code=409, detail="stories may only be added to planned or active sprints")
    association = SprintStory(
        sprint_id=sprint_id,
        story_id=story.id,
        planned_estimated_time=story.estimated_time,
        planned_priority=story.priority,
    )
    db.add(association)
    db.commit()
    db.refresh(association)
    return association


@app.delete("/api/v1/sprints/{sprint_id}/stories/{story_id}", status_code=204)
def remove_sprint_story(sprint_id: UUID, story_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    sprint = db.get(Sprint, sprint_id)
    association = db.scalar(select(SprintStory).where(SprintStory.sprint_id == sprint_id, SprintStory.story_id == story_id))
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    if not association:
        raise HTTPException(status_code=404, detail="story is not assigned to this sprint")
    if sprint.status != "planned" or sprint.start_date <= today():
        raise HTTPException(status_code=409, detail="only future planned sprints can have stories removed")
    db.delete(association)
    db.commit()


@app.delete("/api/v1/sprints/{sprint_id}", status_code=204)
def delete_sprint(sprint_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    if sprint.status != "planned" or sprint.start_date <= today() or sprint.stories:
        raise HTTPException(status_code=409, detail="only future planned sprints without stories can be deleted")
    db.delete(sprint)
    db.commit()


@app.post("/api/v1/sprints/{sprint_id}/close", response_model=SprintResponse)
def close_sprint(
    sprint_id: UUID,
    payload: SprintCloseRequest,
    member: TeamMember = Depends(require_editor),
    db: Session = Depends(get_db),
):
    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    if sprint.status not in {"planned", "active", "paused"}:
        raise HTTPException(status_code=409, detail="sprint is not closable in its current state")

    associations = list(db.scalars(select(SprintStory).where(SprintStory.sprint_id == sprint_id)))
    by_story = {association.story_id: association for association in associations}
    supplied = {item.story_id: item for item in payload.unfinished_story_outcomes}
    unfinished = {association.story_id for association in associations if association.story.status != "Complete"}
    if set(supplied) != unfinished:
        raise HTTPException(status_code=422, detail="every unfinished sprint story requires exactly one close-out outcome")

    for story_id, item in supplied.items():
        if item.outcome not in {"backlog", "future_sprint", "obsolete"}:
            raise HTTPException(status_code=422, detail="invalid unfinished story outcome")
        if item.outcome == "obsolete" and (not item.reason_comment or not item.reason_comment.strip()):
            raise HTTPException(status_code=422, detail="obsolete stories require a reason comment")
        if item.outcome == "future_sprint":
            future = db.get(Sprint, item.future_sprint_id) if item.future_sprint_id else None
            if not future or future.project_id != sprint.project_id or future.id == sprint.id or future.status in {"closed", "archived"}:
                raise HTTPException(status_code=422, detail="future sprint must be an open sprint in the same project")
            if db.scalar(select(SprintStory).where(SprintStory.sprint_id == future.id, SprintStory.story_id == story_id)):
                raise HTTPException(status_code=409, detail="story is already assigned to the future sprint")

    for association in associations:
        story = association.story
        if story.status == "Complete":
            association.completed_at = utc_now()
            continue
        item = supplied[story.id]
        association.close_outcome = item.outcome
        if item.outcome == "future_sprint":
            db.add(SprintStory(
                sprint_id=item.future_sprint_id,
                story_id=story.id,
                planned_estimated_time=story.estimated_time,
                planned_priority=story.priority,
            ))
            story.status = "Backlog"
            story.completion_percent = 0
        elif item.outcome == "backlog":
            story.status = "Backlog"
            story.completion_percent = 0
        else:
            story.status = "Obsolete"
            db.add(StoryComment(story_id=story.id, author_id=member.id, body=item.reason_comment.strip()))
    sprint.status = "closed"
    sprint.version += 1
    db.commit()
    db.refresh(sprint)
    return sprint


@app.post("/api/v1/sprints/{sprint_id}/reopen", response_model=SprintResponse)
def reopen_sprint(sprint_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    if sprint.status != "closed":
        raise HTTPException(status_code=409, detail="only closed sprints can be reopened")
    sprint.status = "active"
    sprint.version += 1
    report = db.scalar(select(SprintReport).where(SprintReport.sprint_id == sprint.id))
    if report and report.status == "finalized":
        report.status = "reviewed"
        report.version += 1
        report.updated_at = utc_now()
    db.commit()
    db.refresh(sprint)
    return sprint


@app.post("/api/v1/sprints/{sprint_id}/archive", response_model=SprintResponse)
def archive_sprint(sprint_id: UUID, _member: TeamMember = Depends(require_editor), db: Session = Depends(get_db)):
    sprint = db.get(Sprint, sprint_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="sprint not found")
    if sprint.status not in {"closed", "paused"}:
        raise HTTPException(status_code=409, detail="only closed or paused sprints can be archived")
    sprint.status = "archived"
    sprint.version += 1
    db.commit()
    db.refresh(sprint)
    return sprint
