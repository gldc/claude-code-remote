"""Pydantic data models for the API server."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    IDLE = "idle"
    AWAITING_APPROVAL = "awaiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


class ProjectType(str, Enum):
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"
    GO = "go"
    UNKNOWN = "unknown"


class WSMessageType(str, Enum):
    ASSISTANT_TEXT = "assistant_text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    STATUS_CHANGE = "status_change"
    APPROVAL_REQUEST = "approval_request"
    ERROR = "error"
    RATE_LIMIT = "rate_limit"
    COST_UPDATE = "cost_update"


# --- Session ---


class SessionCreate(BaseModel):
    name: str
    project_dir: str
    initial_prompt: str
    template_id: str | None = None
    model: str | None = None
    max_budget_usd: float | None = None
    skip_permissions: bool = True
    use_sandbox: bool = False


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    project_dir: str
    status: SessionStatus = SessionStatus.CREATED
    model: str | None = None
    max_budget_usd: float | None = None
    template_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_cost_usd: float = 0.0
    messages: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    archived: bool = False
    claude_session_id: str | None = None
    current_model: str | None = None
    context_percent: int = 0
    git_branch: str | None = None
    skip_permissions: bool = True
    use_sandbox: bool = False


class SessionSummary(BaseModel):
    """Lightweight session info for list views (no messages)."""

    id: str
    name: str
    project_dir: str
    status: SessionStatus
    model: str | None
    created_at: datetime
    updated_at: datetime
    total_cost_usd: float
    current_model: str | None = None
    context_percent: int = 0
    git_branch: str | None = None
    last_message_preview: str | None = None
    archived: bool = False


# --- Template ---


class TemplateCreate(BaseModel):
    name: str
    project_dir: str | None = None
    initial_prompt: str = ""
    model: str | None = None
    max_budget_usd: float | None = None
    allowed_tools: list[str] | None = None


class Template(TemplateCreate):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Project ---


class Project(BaseModel):
    id: str  # hash of path
    name: str
    path: str
    type: ProjectType = ProjectType.UNKNOWN
    session_count: int = 0
    last_session: datetime | None = None

    @staticmethod
    def id_from_path(path: str) -> str:
        return hashlib.sha256(path.encode()).hexdigest()[:12]


class ProjectRegister(BaseModel):
    path: str


# --- WebSocket ---


class WSMessage(BaseModel):
    type: WSMessageType
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Push ---


class PushRegister(BaseModel):
    expo_push_token: str


class PushSettings(BaseModel):
    notify_approvals: bool = True
    notify_completions: bool = True
    notify_errors: bool = True


# --- Approval ---


class ApprovalRequest(BaseModel):
    session_id: str
    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class ApprovalResponse(BaseModel):
    approved: bool
    reason: str | None = None
