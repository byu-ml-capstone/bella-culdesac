from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


class ErrorResponse(BaseModel):
    error: dict
    request_id: str


class HealthResponse(BaseModel):
    ok: bool
    version: str
    database: str


class VersionResponse(BaseModel):
    version: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=5, max_length=200)


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
    username: str
    role: str
    membership_status: str = "active"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    start_date: date | None = None
    due_date: date
    description: str | None = Field(default=None, max_length=1000)
    vision: str | None = Field(default=None, max_length=1000)
    scope: str | None = Field(default=None, max_length=1000)
    tentative_outline: str | None = Field(default=None, max_length=1000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: date | None = None
    due_date: date | None = None
    description: str | None = Field(default=None, max_length=1000)
    vision: str | None = Field(default=None, max_length=1000)
    scope: str | None = Field(default=None, max_length=1000)
    tentative_outline: str | None = Field(default=None, max_length=1000)
    version: int


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    vision: str | None
    scope: str | None
    tentative_outline: str | None
    status: str
    start_date: date
    due_date: date
    completion_percent: Decimal = Decimal("0.00")
    version: int
    created_at: datetime
    workflow_statuses: list[str] | None = None


class StoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_date: date
    start_date: date | None = None
    description: str | None = Field(default=None, max_length=1000)
    priority: str = Field(default="Medium")
    story_type: str = Field(default="User story")
    estimated_time: Decimal = Field(default=Decimal("1.00"), ge=Decimal("0.01"), max_digits=10, decimal_places=2)
    completion_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=100, decimal_places=2)
    status: str = "In Progress"
    github_repo_url: AnyHttpUrl | None = None
    notes: str | None = Field(default=None, max_length=1000)
    parent_id: UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    assignee_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, value: str) -> str:
        if value not in {"Low", "Medium", "High", "Critical"}:
            raise ValueError("invalid priority")
        return value

    @field_validator("story_type")
    @classmethod
    def valid_story_type(cls, value: str) -> str:
        if value not in {"Bug fix", "User story", "Spike story", "Enabler story"}:
            raise ValueError("invalid story type")
        return value


class StoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    due_date: date | None = None
    priority: str | None = None
    story_type: str | None = None
    estimated_time: Decimal | None = Field(default=None, ge=Decimal("0.01"), max_digits=10, decimal_places=2)
    completion_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    github_repo_url: AnyHttpUrl | None = None
    notes: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = Field(default=None, max_length=20)
    assignee_ids: list[UUID] | None = Field(default=None, max_length=20)
    version: int


class StoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    description: str | None
    status: str
    story_type: str
    due_date: date
    start_date: date
    priority: str
    estimated_time: Decimal
    completion_percent: Decimal
    github_repo_url: str | None
    notes: str | None
    parent_id: UUID | None
    tags: list[str]
    assignee_ids: list[UUID]
    version: int
    created_at: datetime


class SprintCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    start_date: date
    end_date: date
    workflow_template_id: UUID | None = None


class SprintUpdate(BaseModel):
    goal: str | None = Field(default=None, min_length=1, max_length=1000)
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None
    version: int


class SprintStoryCreate(BaseModel):
    story_id: UUID


class SprintStoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sprint_id: UUID
    story_id: UUID
    planned_estimated_time: Decimal
    planned_priority: str
    added_at: datetime
    completed_at: datetime | None
    close_outcome: str | None


class SprintResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    goal: str
    start_date: date
    end_date: date
    status: str
    workflow_template_id: UUID | None
    version: int
    created_at: datetime
    stories: list[SprintStoryResponse] = []


class SprintCloseOutcome(BaseModel):
    story_id: UUID
    outcome: str
    future_sprint_id: UUID | None = None
    reason_comment: str | None = Field(default=None, max_length=2000)


class SprintCloseRequest(BaseModel):
    unfinished_story_outcomes: list[SprintCloseOutcome] = []


class StoryCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    story_id: UUID
    author_id: UUID
    body: str
    created_at: datetime


class WorkflowUpdate(BaseModel):
    statuses: list[str] = Field(min_length=3, max_length=20)
    additional_steps: list[str] = []
    renames: dict[str, str] = {}


class WorkflowResponse(BaseModel):
    project_id: UUID
    statuses: list[str]
    additional_steps: list[str] = []


class StoryStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=80)
    reason_comment: str | None = Field(default=None, max_length=2000)


class BoardViewResponse(BaseModel):
    view: str
    items: list[StoryResponse]


class ProjectMetricsResponse(BaseModel):
    project_id: UUID
    completion_percent: Decimal
    overdue_story_count: int
    at_risk_story_count: int
    midpoint_at_risk: bool


class SprintMetricsResponse(BaseModel):
    sprint_id: UUID
    status: str
    planned_story_count: int
    completed_story_count: int
    planned_estimated_hours: Decimal
    completed_estimated_hours: Decimal
    velocity_eligible: bool
    risk: bool


class PasswordRecoveryRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)


class PasswordResetLinkResponse(BaseModel):
    reset_link: str
    expires_at: datetime


class PasswordResetRequest(BaseModel):
    recovery_token: str = Field(min_length=10, max_length=300)
    new_password: str = Field(min_length=8, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=5, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=120)
    role: str = "Team Member"


class InvitationAccept(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=200)


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    role: str
    status: str
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None


class InvitationCreateResponse(InvitationResponse):
    invitation_link: str


class MemberUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    role: str | None = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    story_id: UUID
    author_id: UUID
    body: str
    created_at: datetime
    updated_at: datetime


class IdeaCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    idea_id: UUID
    author_id: UUID
    body: str
    created_at: datetime
    updated_at: datetime


class SprintReportCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_id: UUID
    author_id: UUID
    body: str
    created_at: datetime
    updated_at: datetime


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    story_id: UUID
    file_name: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID
    created_at: datetime


class ReportDraftRequest(BaseModel):
    additional_context: str | None = Field(default=None, max_length=4000)
    replace_existing_draft: bool = False


class SprintReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sprint_id: UUID
    content: dict
    status: str
    provider: str
    model: str
    generated_at: datetime
    updated_at: datetime
    version: int


class SprintReportUpdate(BaseModel):
    content: dict
    status: str | None = None
    version: int


class IdeaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class IdeaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=20)
    status: str | None = None
    version: int


class IdeaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    scope: str
    project_id: UUID | None
    status: str
    tags: list[str]
    promoted_project_id: UUID | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    version: int


class IdeaPromotion(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    vision: str | None = Field(default=None, max_length=1000)
    scope: str | None = Field(default=None, max_length=1000)
    due_date: date | None = None
    workflow_template_id: UUID | None = None


class IdeaConversion(BaseModel):
    project_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    due_date: date | None = None


class ConversationCreate(BaseModel):
    scope: str
    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    status: str | None = None
    version: int


class ConversationCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ConversationCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    author_id: UUID
    body: str
    created_at: datetime
    updated_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope: str
    project_id: UUID | None
    title: str
    body: str
    created_by: UUID
    status: str
    created_at: datetime
    updated_at: datetime
    version: int
    comments: list[ConversationCommentResponse] = []


class WorkflowTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    statuses: list[str] = Field(min_length=3, max_length=20)
    setup_steps: list[str] = Field(default_factory=list, max_length=30)


class WorkflowTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    statuses: list[str] | None = Field(default=None, min_length=3, max_length=20)
    setup_steps: list[str] | None = Field(default=None, max_length=30)
    version: int


class WorkflowTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    statuses: list[str]
    setup_steps: list[str]
    protected: bool
    version: int


class ProjectPage(BaseModel):
    items: list[ProjectResponse]
    page: int
    page_size: int
    total: int


class MemberPage(BaseModel):
    items: list[MemberResponse]
    page: int
    page_size: int
    total: int


class InvitationPage(BaseModel):
    items: list[InvitationResponse]
    page: int
    page_size: int
    total: int


class WorkflowTemplatePage(BaseModel):
    items: list[WorkflowTemplateResponse]
    page: int
    page_size: int
    total: int


class CommentPage(BaseModel):
    items: list[CommentResponse]
    page: int
    page_size: int
    total: int


class AttachmentPage(BaseModel):
    items: list[AttachmentResponse]
    page: int
    page_size: int
    total: int


class IdeaCommentPage(BaseModel):
    items: list[IdeaCommentResponse]
    page: int
    page_size: int
    total: int


class SprintReportPage(BaseModel):
    items: list[SprintReportResponse]
    page: int
    page_size: int
    total: int


class SprintReportCommentPage(BaseModel):
    items: list[SprintReportCommentResponse]
    page: int
    page_size: int
    total: int


class StoryPage(BaseModel):
    items: list[StoryResponse]
    page: int
    page_size: int
    total: int


class SprintPage(BaseModel):
    items: list[SprintResponse]
    page: int
    page_size: int
    total: int


class IdeaPage(BaseModel):
    items: list[IdeaResponse]
    page: int
    page_size: int
    total: int


class ConversationPage(BaseModel):
    items: list[ConversationResponse]
    page: int
    page_size: int
    total: int
