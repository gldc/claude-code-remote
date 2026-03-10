"""Pydantic data models for the API server."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pathlib import Path

from pydantic import BaseModel, Field, field_validator


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
    USER_MESSAGE = "user_message"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    STATUS_CHANGE = "status_change"
    APPROVAL_REQUEST = "approval_request"
    ERROR = "error"
    RATE_LIMIT = "rate_limit"
    COST_UPDATE = "cost_update"
    BASH_OUTPUT = "bash_output"


# --- Session ---


class SessionUpdate(BaseModel):
    name: str | None = None


class SessionCreate(BaseModel):
    name: str
    project_dir: str
    initial_prompt: str
    template_id: str | None = None
    model: str | None = None
    max_budget_usd: float | None = None
    skip_permissions: bool = False
    use_sandbox: bool = False
    allowed_tools: list[str] | None = None

    @field_validator("project_dir")
    @classmethod
    def validate_project_dir(cls, v: str) -> str:
        resolved = Path(v).expanduser().resolve()
        if ".." in Path(v).parts:
            raise ValueError("project_dir must not contain '..' components")
        if not resolved.is_dir():
            raise ValueError(
                f"project_dir does not exist or is not a directory: {resolved}"
            )
        return str(resolved)


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
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    git_branch: str | None = None
    skip_permissions: bool = True
    use_sandbox: bool = False
    allowed_tools: list[str] | None = None
    owner: str | None = None
    collaborators: list[str] = Field(default_factory=list)
    require_multi_approval: bool = False


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
    tags: list[str] = Field(default_factory=list)


class Template(TemplateCreate):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_builtin: bool = False


# --- Project ---


class Project(BaseModel):
    id: str  # hash of path
    name: str
    path: str
    type: ProjectType = ProjectType.UNKNOWN
    session_count: int = 0
    last_session: datetime | None = None
    status: str = "ready"
    error_message: str | None = None

    @staticmethod
    def id_from_path(path: str) -> str:
        return hashlib.sha256(path.encode()).hexdigest()[:12]


class ProjectRegister(BaseModel):
    path: str


class ProjectCreate(BaseModel):
    name: str


class ProjectClone(BaseModel):
    url: str
    name: str | None = None


# --- WebSocket ---


class WSMessage(BaseModel):
    type: WSMessageType
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Push ---


class PushRegister(BaseModel):
    expo_push_token: str

    @field_validator("expo_push_token")
    @classmethod
    def validate_expo_push_token(cls, v: str) -> str:
        import re

        if not re.match(r"^ExponentPushToken\[.+\]$", v):
            raise ValueError(
                "Invalid Expo push token format. "
                "Expected format: ExponentPushToken[...]"
            )
        return v


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


class ApprovalRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    tool_pattern: str  # exact name or glob pattern like "Bash*"
    action: str = "approve"  # "approve" or "deny"
    project_dir: str | None = None  # scope to project, or None for global
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Route request models ---


class SendPromptRequest(BaseModel):
    prompt: str = Field(..., max_length=100000)


class ResumeSessionRequest(BaseModel):
    prompt: str


class InternalApprovalRequest(BaseModel):
    session_id: str
    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class StatuslineRequest(BaseModel):
    session_id: str
    model: str | None = None
    context_percent: int = 0
    git_branch: str | None = None


# --- Usage ---


class UsageWindow(BaseModel):
    percent_remaining: float = 0.0
    resets_in_seconds: int = 0


class UsageWindowWithReserve(UsageWindow):
    reserve_percent: float = 0.0


class ExtraUsage(BaseModel):
    monthly_spend: float = 0.0
    monthly_limit: float = 0.0


class UsageData(BaseModel):
    session: UsageWindow = Field(default_factory=UsageWindow)
    weekly: UsageWindowWithReserve = Field(default_factory=UsageWindowWithReserve)
    sonnet: UsageWindow = Field(default_factory=UsageWindow)
    extra_usage: ExtraUsage = Field(default_factory=ExtraUsage)
    plan_tier: str = "unknown"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Git ---


class GitFileStatus(BaseModel):
    path: str
    status: str  # "M", "A", "D", "?", "R"


class GitStatus(BaseModel):
    branch: str = ""
    modified: list[GitFileStatus] = Field(default_factory=list)
    staged: list[GitFileStatus] = Field(default_factory=list)
    untracked: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class GitBranch(BaseModel):
    name: str
    is_current: bool = False


class GitLogEntry(BaseModel):
    hash: str
    message: str
    author: str
    date: str


# --- MCP ---


class MCPServer(BaseModel):
    name: str
    type: str = "stdio"  # "stdio" or "sse"
    command: str | None = None  # for stdio
    args: list[str] = Field(default_factory=list)
    url: str | None = None  # for sse
    env: dict[str, str] = Field(default_factory=dict)
    scope: str = "global"  # "global" or "project"

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Block shell meta-characters and path traversal
        dangerous = [";", "&&", "||", "|", "`", "$(", "${", ">", "<", "\n", "\r"]
        for ch in dangerous:
            if ch in v:
                raise ValueError(
                    f"MCP command must not contain shell metacharacter: {ch!r}"
                )
        if ".." in v.split("/"):
            raise ValueError("MCP command must not contain '..' path traversal")
        # Enforce absolute paths: if not already absolute, resolve via shutil.which
        if not Path(v).is_absolute():
            resolved = shutil.which(v)
            if resolved:
                v = resolved
            else:
                raise ValueError(
                    f"MCP command {v!r} is not an absolute path and could not be found on PATH"
                )
        return v

    @field_validator("args")
    @classmethod
    def validate_args(cls, v: list[str]) -> list[str]:
        dangerous = [";", "&&", "||", "|", "`", "$(", "${", "\n", "\r"]
        for i, arg in enumerate(v):
            for ch in dangerous:
                if ch in arg:
                    raise ValueError(
                        f"MCP arg[{i}] must not contain shell metacharacter: {ch!r}"
                    )
        return v


class MCPHealthResult(BaseModel):
    name: str
    healthy: bool
    latency_ms: int | None = None
    error: str | None = None


# --- Workflow ---


class WorkflowStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class WorkflowStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    session_config: SessionCreate
    depends_on: list[str] = Field(default_factory=list)  # step IDs
    status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    session_id: str | None = None  # created session ID


class WorkflowStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class WorkflowCreate(BaseModel):
    name: str
    steps: list[WorkflowStep] = Field(default_factory=list)


class WorkflowStepCreate(BaseModel):
    session_config: SessionCreate
    depends_on: list[str] = Field(default_factory=list)


class Workflow(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    steps: list[WorkflowStep] = Field(default_factory=list)
    status: WorkflowStatus = WorkflowStatus.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- Collaboration ---


class CollaboratorRequest(BaseModel):
    identity: str
