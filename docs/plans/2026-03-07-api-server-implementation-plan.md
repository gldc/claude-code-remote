# Claude Code Remote API Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace tmux/ttyd/voice wrapper with a FastAPI server managing Claude Code subprocesses via stream-json, REST + WebSocket API, Tailscale WhoIs auth, and Expo push notifications.

**Architecture:** FastAPI server binds to Tailscale IP, manages Claude Code as subprocesses with stream-json I/O, exposes REST endpoints for CRUD + WebSocket for live streaming, uses MCP approval tool for permission routing, sends push notifications via Expo Push API.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, httpx, asyncio subprocesses, pydantic

---

### Task 1: Update Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Update pyproject.toml**

Replace the current dependencies and add new ones:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "claude-code-remote"
version = "0.2.0"
description = "Remote access to Claude Code CLI over Tailscale"
requires-python = ">=3.10"
dependencies = [
    "click",
    "fastapi",
    "uvicorn[standard]",
    "httpx",
    "pydantic>=2.0",
    "websockets",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "pytest-httpx",
]

[project.scripts]
ccr = "claude_code_remote.cli:cli"
```

**Step 2: Reinstall**

Run: `cd /Users/gldc/Developer/claude-code-remote && pip install -e ".[dev]"`

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: update dependencies for API server redesign"
```

---

### Task 2: Pydantic Data Models

**Files:**
- Create: `src/claude_code_remote/models.py`
- Create: `tests/test_models.py`

**Step 1: Write tests**

```python
# tests/test_models.py
import pytest
from claude_code_remote.models import (
    Session, SessionStatus, SessionCreate,
    Template, TemplateCreate,
    Project, ProjectType,
    WSMessage, WSMessageType,
    PushSettings,
)


def test_session_create_defaults():
    s = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    assert s.template_id is None
    assert s.model is None
    assert s.max_budget_usd is None


def test_session_status_values():
    assert SessionStatus.RUNNING == "running"
    assert SessionStatus.AWAITING_APPROVAL == "awaiting_approval"
    assert SessionStatus.COMPLETED == "completed"
    assert SessionStatus.ERROR == "error"
    assert SessionStatus.PAUSED == "paused"


def test_template_create():
    t = TemplateCreate(name="debug", initial_prompt="fix the bug")
    assert t.project_dir is None
    assert t.model is None


def test_ws_message_serialization():
    msg = WSMessage(type=WSMessageType.ASSISTANT_TEXT, data={"text": "hello"})
    d = msg.model_dump()
    assert d["type"] == "assistant_text"
    assert "timestamp" in d


def test_project_type_detection():
    assert ProjectType.PYTHON == "python"
    assert ProjectType.NODE == "node"
```

**Step 2: Run tests — expect FAIL**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/test_models.py -v`

**Step 3: Implement models**

```python
# src/claude_code_remote/models.py
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
    last_message_preview: str | None = None


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
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_models.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/models.py tests/test_models.py
git commit -m "feat: add pydantic data models for API server"
```

---

### Task 3: Update Config Module

**Files:**
- Modify: `src/claude_code_remote/config.py`
- Create: `tests/test_config.py`

**Step 1: Write tests**

```python
# tests/test_config.py
from claude_code_remote.config import (
    STATE_DIR, SESSION_DIR, TEMPLATE_DIR,
    DEFAULT_CONFIG, load_config,
)


def test_default_config_has_new_keys():
    cfg = DEFAULT_CONFIG
    assert "port" in cfg
    assert cfg["port"] == 8080
    assert "max_concurrent_sessions" in cfg
    assert cfg["max_concurrent_sessions"] == 5
    assert "scan_directories" in cfg


def test_state_subdirs_exist():
    assert SESSION_DIR.name == "sessions"
    assert TEMPLATE_DIR.name == "templates"
```

**Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_config.py -v`

**Step 3: Update config.py**

```python
"""Configuration loading and saving."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "claude-code-remote"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DIR = Path.home() / ".local" / "state" / "claude-code-remote"
LOG_DIR = STATE_DIR / "logs"
PID_DIR = STATE_DIR / "pids"
SESSION_DIR = STATE_DIR / "sessions"
TEMPLATE_DIR = STATE_DIR / "templates"
PUSH_FILE = STATE_DIR / "push.json"
PROJECTS_FILE = STATE_DIR / "projects.json"

DEFAULT_CONFIG = {
    "port": 8080,
    "max_concurrent_sessions": 5,
    "scan_directories": ["~/Developer"],
    "session_idle_timeout_minutes": None,
}


def ensure_dirs() -> None:
    for d in [LOG_DIR, PID_DIR, SESSION_DIR, TEMPLATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_config.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/config.py tests/test_config.py
git commit -m "feat: update config module for API server"
```

---

### Task 4: Tailscale Auth Middleware

**Files:**
- Create: `src/claude_code_remote/auth.py`
- Create: `tests/test_auth.py`

**Step 1: Write tests**

```python
# tests/test_auth.py
import pytest
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_code_remote.auth import TailscaleAuthMiddleware


@pytest.fixture
def app_with_auth():
    app = FastAPI()
    app.add_middleware(TailscaleAuthMiddleware)

    @app.get("/test")
    async def test_route():
        return {"ok": True}

    return app


def test_allows_request_when_whois_succeeds(app_with_auth):
    client = TestClient(app_with_auth)
    with patch("claude_code_remote.auth.verify_tailscale_client", return_value=True):
        resp = client.get("/test")
    assert resp.status_code == 200


def test_rejects_request_when_whois_fails(app_with_auth):
    client = TestClient(app_with_auth)
    with patch("claude_code_remote.auth.verify_tailscale_client", return_value=False):
        resp = client.get("/test")
    assert resp.status_code == 403
```

**Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_auth.py -v`

**Step 3: Implement auth middleware**

```python
# src/claude_code_remote/auth.py
"""Tailscale WhoIs authentication middleware."""

import subprocess
import shutil

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _find_tailscale() -> str:
    return shutil.which("tailscale") or "/usr/local/bin/tailscale"


def verify_tailscale_client(client_ip: str) -> bool:
    """Verify a client IP belongs to this tailnet via `tailscale whois`."""
    try:
        result = subprocess.run(
            [_find_tailscale(), "whois", "--json", client_ip],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


class TailscaleAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else None
        if not client_ip or not verify_tailscale_client(client_ip):
            return JSONResponse(
                status_code=403,
                content={"detail": "Not authorized. Connect via Tailscale."},
            )
        response = await call_next(request)
        return response
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_auth.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/auth.py tests/test_auth.py
git commit -m "feat: add Tailscale WhoIs auth middleware"
```

---

### Task 5: Session Manager

This is the core module. It spawns Claude Code subprocesses, reads stream-json output, manages session lifecycle, and persists state.

**Files:**
- Create: `src/claude_code_remote/session_manager.py`
- Create: `tests/test_session_manager.py`

**Step 1: Write tests**

```python
# tests/test_session_manager.py
import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from claude_code_remote.session_manager import SessionManager
from claude_code_remote.models import SessionCreate, SessionStatus


@pytest.fixture
def tmp_session_dir(tmp_path):
    return tmp_path / "sessions"


@pytest.fixture
def manager(tmp_session_dir):
    return SessionManager(session_dir=tmp_session_dir, max_concurrent=5)


def test_create_session(manager):
    req = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    session = manager.create_session(req)
    assert session.name == "test"
    assert session.status == SessionStatus.CREATED
    assert session.id in manager.sessions


def test_list_sessions_empty(manager):
    assert manager.list_sessions() == []


def test_list_sessions_with_filter(manager):
    req1 = SessionCreate(name="a", project_dir="/tmp", initial_prompt="x")
    req2 = SessionCreate(name="b", project_dir="/tmp", initial_prompt="y")
    s1 = manager.create_session(req1)
    s2 = manager.create_session(req2)
    s1.status = SessionStatus.RUNNING
    s2.status = SessionStatus.COMPLETED
    running = manager.list_sessions(status=SessionStatus.RUNNING)
    assert len(running) == 1
    assert running[0].id == s1.id


def test_get_session(manager):
    req = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    session = manager.create_session(req)
    found = manager.get_session(session.id)
    assert found is not None
    assert found.id == session.id


def test_get_session_not_found(manager):
    assert manager.get_session("nonexistent") is None


def test_delete_session(manager):
    req = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    session = manager.create_session(req)
    manager.delete_session(session.id)
    assert manager.get_session(session.id) is None


def test_max_concurrent_sessions(manager):
    manager.max_concurrent = 2
    for i in range(2):
        req = SessionCreate(name=f"s{i}", project_dir="/tmp", initial_prompt="x")
        s = manager.create_session(req)
        s.status = SessionStatus.RUNNING
    req = SessionCreate(name="s3", project_dir="/tmp", initial_prompt="x")
    with pytest.raises(RuntimeError, match="Maximum concurrent"):
        manager.create_session(req)


def test_persist_and_load(manager, tmp_session_dir):
    req = SessionCreate(name="persist", project_dir="/tmp", initial_prompt="hello")
    session = manager.create_session(req)
    manager.persist_session(session.id)
    assert (tmp_session_dir / f"{session.id}.json").exists()

    manager2 = SessionManager(session_dir=tmp_session_dir, max_concurrent=5)
    manager2.load_sessions()
    loaded = manager2.get_session(session.id)
    assert loaded is not None
    assert loaded.name == "persist"
```

**Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_session_manager.py -v`

**Step 3: Implement session manager**

```python
# src/claude_code_remote/session_manager.py
"""Session manager — spawns and manages Claude Code subprocesses."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from claude_code_remote.models import (
    Session, SessionCreate, SessionStatus, SessionSummary,
    WSMessage, WSMessageType,
)

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, session_dir: Path, max_concurrent: int = 5):
        self.session_dir = session_dir
        self.max_concurrent = max_concurrent
        self.sessions: dict[str, Session] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.ws_subscribers: dict[str, list[Callable]] = {}
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_responses: dict[str, bool] = {}
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, req: SessionCreate) -> Session:
        running = sum(
            1 for s in self.sessions.values()
            if s.status in (SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL)
        )
        if running >= self.max_concurrent:
            raise RuntimeError(
                f"Maximum concurrent sessions ({self.max_concurrent}) reached."
            )

        session = Session(
            name=req.name,
            project_dir=req.project_dir,
            model=req.model,
            max_budget_usd=req.max_budget_usd,
            template_id=req.template_id,
        )
        self.sessions[session.id] = session
        self.persist_session(session.id)
        return session

    def list_sessions(
        self,
        status: SessionStatus | None = None,
        project_dir: str | None = None,
    ) -> list[SessionSummary]:
        results = []
        for s in self.sessions.values():
            if status and s.status != status:
                continue
            if project_dir and s.project_dir != project_dir:
                continue
            preview = None
            if s.messages:
                last = s.messages[-1]
                preview = str(last.get("data", {}).get("text", ""))[:100]
            results.append(SessionSummary(
                id=s.id,
                name=s.name,
                project_dir=s.project_dir,
                status=s.status,
                model=s.model,
                created_at=s.created_at,
                updated_at=s.updated_at,
                total_cost_usd=s.total_cost_usd,
                last_message_preview=preview,
            ))
        return results

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def delete_session(self, session_id: str) -> None:
        self._stop_process(session_id)
        self.sessions.pop(session_id, None)
        self.ws_subscribers.pop(session_id, None)
        path = self.session_dir / f"{session_id}.json"
        path.unlink(missing_ok=True)

    def persist_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        path = self.session_dir / f"{session_id}.json"
        path.write_text(session.model_dump_json(indent=2))

    def load_sessions(self) -> None:
        for path in self.session_dir.glob("*.json"):
            try:
                session = Session.model_validate_json(path.read_text())
                if session.status in (SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL):
                    session.status = SessionStatus.ERROR
                    session.error_message = "Server restarted while session was active"
                self.sessions[session.id] = session
            except Exception as e:
                logger.error(f"Failed to load session {path}: {e}")

    def _stop_process(self, session_id: str) -> None:
        proc = self.processes.pop(session_id, None)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    async def start_session(
        self,
        session_id: str,
        initial_prompt: str,
        on_event: Callable[[WSMessage], Any] | None = None,
    ) -> None:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("Claude Code CLI not found in PATH")

        cmd = [
            claude_bin, "-p",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--verbose",
            "--no-session-persistence",
        ]
        if session.model:
            cmd.extend(["--model", session.model])
        if session.max_budget_usd:
            cmd.extend(["--max-budget-usd", str(session.max_budget_usd)])

        env = os.environ.copy()
        for key in ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
                     "CLAUDE_CODE_ENTRY_VERSION", "CLAUDE_CODE_ENV_VERSION"]:
            env.pop(key, None)

        proc = await asyncio.create_subprocess_exec(
            *cmd, initial_prompt,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session.project_dir,
            env=env,
        )
        self.processes[session_id] = proc
        session.status = SessionStatus.RUNNING
        session.updated_at = datetime.now(timezone.utc)
        self.persist_session(session_id)

        asyncio.create_task(self._read_output(session_id, proc, on_event))

    async def _read_output(
        self,
        session_id: str,
        proc: asyncio.subprocess.Process,
        on_event: Callable[[WSMessage], Any] | None,
    ) -> None:
        session = self.sessions.get(session_id)
        if not session or not proc.stdout:
            return

        async for line in proc.stdout:
            text = line.decode().strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue

            ws_msg = self._parse_event(event)
            if ws_msg:
                session.messages.append(ws_msg.model_dump(mode="json"))
                session.updated_at = datetime.now(timezone.utc)
                if on_event:
                    await on_event(ws_msg) if asyncio.iscoroutinefunction(on_event) else on_event(ws_msg)
                await self._broadcast(session_id, ws_msg)

            if event.get("type") == "result":
                cost = event.get("total_cost_usd", 0)
                session.total_cost_usd = cost
                subtype = event.get("subtype", "")
                if subtype == "success":
                    session.status = SessionStatus.COMPLETED
                else:
                    session.status = SessionStatus.ERROR
                    session.error_message = event.get("result", "Unknown error")
                session.updated_at = datetime.now(timezone.utc)
                self.persist_session(session_id)

        await proc.wait()
        if session.status == SessionStatus.RUNNING:
            session.status = SessionStatus.ERROR
            session.error_message = f"Process exited with code {proc.returncode}"
            session.updated_at = datetime.now(timezone.utc)
            self.persist_session(session_id)

    def _parse_event(self, event: dict) -> WSMessage | None:
        etype = event.get("type")

        if etype == "assistant":
            msg = event.get("message", {})
            content = msg.get("content", [])
            messages = []
            for block in content:
                if block.get("type") == "text":
                    messages.append(WSMessage(
                        type=WSMessageType.ASSISTANT_TEXT,
                        data={"text": block["text"]},
                    ))
                elif block.get("type") == "tool_use":
                    messages.append(WSMessage(
                        type=WSMessageType.TOOL_USE,
                        data={
                            "tool_name": block.get("name", ""),
                            "tool_input": block.get("input", {}),
                            "tool_use_id": block.get("id", ""),
                        },
                    ))
            return messages[0] if len(messages) == 1 else messages[0] if messages else None

        elif etype == "result":
            return WSMessage(
                type=WSMessageType.STATUS_CHANGE,
                data={
                    "status": "completed" if event.get("subtype") == "success" else "error",
                    "cost_usd": event.get("total_cost_usd", 0),
                    "duration_ms": event.get("duration_ms", 0),
                    "result": event.get("result", ""),
                },
            )

        elif etype == "rate_limit_event":
            return WSMessage(
                type=WSMessageType.RATE_LIMIT,
                data=event.get("rate_limit_info", {}),
            )

        return None

    async def send_prompt(self, session_id: str, prompt: str) -> None:
        proc = self.processes.get(session_id)
        if not proc or not proc.stdin:
            raise ValueError(f"No active process for session {session_id}")
        msg = json.dumps({"type": "user", "content": prompt}) + "\n"
        proc.stdin.write(msg.encode())
        await proc.stdin.drain()

    async def pause_session(self, session_id: str) -> None:
        proc = self.processes.get(session_id)
        session = self.sessions.get(session_id)
        if proc and proc.returncode is None:
            proc.send_signal(signal.SIGINT)
            if session:
                session.status = SessionStatus.PAUSED
                session.updated_at = datetime.now(timezone.utc)
                self.persist_session(session_id)

    async def approve_tool_use(self, session_id: str) -> None:
        event = self._approval_events.get(session_id)
        if event:
            self._approval_responses[session_id] = True
            event.set()

    async def deny_tool_use(self, session_id: str, reason: str | None = None) -> None:
        event = self._approval_events.get(session_id)
        if event:
            self._approval_responses[session_id] = False
            event.set()

    def subscribe(self, session_id: str, callback: Callable) -> None:
        self.ws_subscribers.setdefault(session_id, []).append(callback)

    def unsubscribe(self, session_id: str, callback: Callable) -> None:
        subs = self.ws_subscribers.get(session_id, [])
        if callback in subs:
            subs.remove(callback)

    async def _broadcast(self, session_id: str, msg: WSMessage) -> None:
        for cb in self.ws_subscribers.get(session_id, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(msg)
                else:
                    cb(msg)
            except Exception as e:
                logger.error(f"WebSocket broadcast error: {e}")

    async def shutdown(self) -> None:
        for session_id in list(self.processes.keys()):
            self._stop_process(session_id)
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_session_manager.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/session_manager.py tests/test_session_manager.py
git commit -m "feat: add session manager for Claude Code subprocesses"
```

---

### Task 6: Project Scanner

**Files:**
- Create: `src/claude_code_remote/projects.py`
- Create: `tests/test_projects.py`

**Step 1: Write tests**

```python
# tests/test_projects.py
import pytest
from pathlib import Path
from claude_code_remote.projects import scan_directory, detect_project_type
from claude_code_remote.models import ProjectType


def test_detect_python_project(tmp_path):
    (tmp_path / "pyproject.toml").touch()
    assert detect_project_type(tmp_path) == ProjectType.PYTHON


def test_detect_node_project(tmp_path):
    (tmp_path / "package.json").touch()
    assert detect_project_type(tmp_path) == ProjectType.NODE


def test_detect_rust_project(tmp_path):
    (tmp_path / "Cargo.toml").touch()
    assert detect_project_type(tmp_path) == ProjectType.RUST


def test_detect_go_project(tmp_path):
    (tmp_path / "go.mod").touch()
    assert detect_project_type(tmp_path) == ProjectType.GO


def test_detect_unknown_project(tmp_path):
    assert detect_project_type(tmp_path) == ProjectType.UNKNOWN


def test_scan_directory(tmp_path):
    proj1 = tmp_path / "project-a"
    proj1.mkdir()
    (proj1 / ".git").mkdir()
    (proj1 / "package.json").touch()

    proj2 = tmp_path / "project-b"
    proj2.mkdir()
    (proj2 / "pyproject.toml").touch()

    not_a_project = tmp_path / "random-dir"
    not_a_project.mkdir()

    projects = scan_directory(tmp_path)
    assert len(projects) == 2
    names = {p.name for p in projects}
    assert "project-a" in names
    assert "project-b" in names
```

**Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_projects.py -v`

**Step 3: Implement project scanner**

```python
# src/claude_code_remote/projects.py
"""Project discovery and scanning."""

from pathlib import Path

from claude_code_remote.models import Project, ProjectType

PROJECT_INDICATORS = [".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod"]

TYPE_MAP = {
    "pyproject.toml": ProjectType.PYTHON,
    "setup.py": ProjectType.PYTHON,
    "package.json": ProjectType.NODE,
    "Cargo.toml": ProjectType.RUST,
    "go.mod": ProjectType.GO,
}


def detect_project_type(path: Path) -> ProjectType:
    for filename, ptype in TYPE_MAP.items():
        if (path / filename).exists():
            return ptype
    return ProjectType.UNKNOWN


def is_project(path: Path) -> bool:
    return any((path / ind).exists() for ind in PROJECT_INDICATORS)


def scan_directory(root: Path) -> list[Project]:
    projects = []
    if not root.is_dir():
        return projects
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if is_project(child):
            projects.append(Project(
                id=Project.id_from_path(str(child)),
                name=child.name,
                path=str(child),
                type=detect_project_type(child),
            ))
    return projects
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_projects.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/projects.py tests/test_projects.py
git commit -m "feat: add project scanner"
```

---

### Task 7: Template Store

**Files:**
- Create: `src/claude_code_remote/templates.py`
- Create: `tests/test_templates.py`

**Step 1: Write tests**

```python
# tests/test_templates.py
import pytest
from pathlib import Path
from claude_code_remote.templates import TemplateStore
from claude_code_remote.models import TemplateCreate


@pytest.fixture
def store(tmp_path):
    return TemplateStore(tmp_path / "templates")


def test_create_template(store):
    req = TemplateCreate(name="debug", initial_prompt="fix it")
    t = store.create(req)
    assert t.name == "debug"
    assert t.id is not None


def test_list_templates(store):
    store.create(TemplateCreate(name="a", initial_prompt="x"))
    store.create(TemplateCreate(name="b", initial_prompt="y"))
    assert len(store.list()) == 2


def test_get_template(store):
    t = store.create(TemplateCreate(name="test", initial_prompt="hi"))
    found = store.get(t.id)
    assert found is not None
    assert found.name == "test"


def test_update_template(store):
    t = store.create(TemplateCreate(name="old", initial_prompt="x"))
    updated = store.update(t.id, TemplateCreate(name="new", initial_prompt="y"))
    assert updated.name == "new"
    assert updated.id == t.id


def test_delete_template(store):
    t = store.create(TemplateCreate(name="del", initial_prompt="x"))
    store.delete(t.id)
    assert store.get(t.id) is None
```

**Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_templates.py -v`

**Step 3: Implement template store**

```python
# src/claude_code_remote/templates.py
"""Template persistence — CRUD for session templates."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from claude_code_remote.models import Template, TemplateCreate

logger = logging.getLogger(__name__)


class TemplateStore:
    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.templates: dict[str, Template] = {}
        self._load()

    def _load(self) -> None:
        for path in self.template_dir.glob("*.json"):
            try:
                t = Template.model_validate_json(path.read_text())
                self.templates[t.id] = t
            except Exception as e:
                logger.error(f"Failed to load template {path}: {e}")

    def _save(self, template: Template) -> None:
        path = self.template_dir / f"{template.id}.json"
        path.write_text(template.model_dump_json(indent=2))

    def create(self, req: TemplateCreate) -> Template:
        t = Template(**req.model_dump())
        self.templates[t.id] = t
        self._save(t)
        return t

    def list(self) -> list[Template]:
        return list(self.templates.values())

    def get(self, template_id: str) -> Template | None:
        return self.templates.get(template_id)

    def update(self, template_id: str, req: TemplateCreate) -> Template:
        existing = self.templates.get(template_id)
        if not existing:
            raise ValueError(f"Template {template_id} not found")
        updated = Template(id=existing.id, created_at=existing.created_at, **req.model_dump())
        self.templates[template_id] = updated
        self._save(updated)
        return updated

    def delete(self, template_id: str) -> None:
        self.templates.pop(template_id, None)
        path = self.template_dir / f"{template_id}.json"
        path.unlink(missing_ok=True)
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_templates.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/templates.py tests/test_templates.py
git commit -m "feat: add template store"
```

---

### Task 8: Push Notification Module

**Files:**
- Create: `src/claude_code_remote/push.py`
- Create: `tests/test_push.py`

**Step 1: Write tests**

```python
# tests/test_push.py
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from claude_code_remote.push import PushManager


@pytest.fixture
def push_mgr(tmp_path):
    return PushManager(tmp_path / "push.json")


def test_register_token(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    assert "ExponentPushToken[abc123]" in push_mgr.tokens


def test_register_duplicate_token(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    push_mgr.register_token("ExponentPushToken[abc123]")
    assert len(push_mgr.tokens) == 1


def test_persist_tokens(push_mgr, tmp_path):
    push_mgr.register_token("ExponentPushToken[abc123]")
    mgr2 = PushManager(tmp_path / "push.json")
    assert "ExponentPushToken[abc123]" in mgr2.tokens


def test_default_settings(push_mgr):
    s = push_mgr.get_settings()
    assert s.notify_approvals is True
    assert s.notify_completions is True
    assert s.notify_errors is True


@pytest.mark.asyncio
async def test_send_notification(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch("claude_code_remote.push.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()
        await push_mgr.send("Test Title", "Test body", {"session_id": "123"})
        mock_client.post.assert_called_once()
```

**Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_push.py -v`

**Step 3: Implement push module**

```python
# src/claude_code_remote/push.py
"""Push notifications via Expo Push API."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from claude_code_remote.models import PushSettings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class PushManager:
    def __init__(self, push_file: Path):
        self.push_file = push_file
        self.tokens: set[str] = set()
        self.settings = PushSettings()
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.push_file.read_text())
            self.tokens = set(data.get("tokens", []))
            if "settings" in data:
                self.settings = PushSettings(**data["settings"])
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        self.push_file.parent.mkdir(parents=True, exist_ok=True)
        self.push_file.write_text(json.dumps({
            "tokens": list(self.tokens),
            "settings": self.settings.model_dump(),
        }, indent=2))

    def register_token(self, token: str) -> None:
        self.tokens.add(token)
        self._save()

    def get_settings(self) -> PushSettings:
        return self.settings

    def update_settings(self, settings: PushSettings) -> None:
        self.settings = settings
        self._save()

    async def send(
        self,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self.tokens:
            return

        messages = [
            {
                "to": token,
                "title": title,
                "body": body,
                "data": data or {},
                "sound": "default",
            }
            for token in self.tokens
        ]

        try:
            async with httpx.AsyncClient() as client:
                await client.post(EXPO_PUSH_URL, json=messages, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")

    async def notify_approval(self, session_name: str, tool_name: str, session_id: str) -> None:
        if self.settings.notify_approvals:
            await self.send(
                "Approval Needed",
                f"Session '{session_name}' wants to: {tool_name}",
                {"session_id": session_id, "type": "approval_request"},
            )

    async def notify_completion(self, session_name: str, cost: float, session_id: str) -> None:
        if self.settings.notify_completions:
            await self.send(
                "Task Complete",
                f"Session '{session_name}' finished (${cost:.2f})",
                {"session_id": session_id, "type": "session_completed"},
            )

    async def notify_error(self, session_name: str, error: str, session_id: str) -> None:
        if self.settings.notify_errors:
            await self.send(
                "Session Error",
                f"Session '{session_name}': {error[:100]}",
                {"session_id": session_id, "type": "session_error"},
            )
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_push.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/push.py tests/test_push.py
git commit -m "feat: add push notification module"
```

---

### Task 9: REST API Routes

**Files:**
- Create: `src/claude_code_remote/routes.py`
- Create: `tests/test_routes.py`

**Step 1: Write tests**

```python
# tests/test_routes.py
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_code_remote.routes import create_router
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.projects import scan_directory
from claude_code_remote.push import PushManager
from claude_code_remote.models import SessionCreate, TemplateCreate


@pytest.fixture
def app(tmp_path):
    session_mgr = SessionManager(session_dir=tmp_path / "sessions")
    template_store = TemplateStore(tmp_path / "templates")
    push_mgr = PushManager(tmp_path / "push.json")
    scan_dirs = [str(tmp_path / "projects")]

    router = create_router(session_mgr, template_store, push_mgr, scan_dirs)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_list_sessions_empty(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_session(client):
    resp = client.post("/api/sessions", json={
        "name": "test",
        "project_dir": "/tmp",
        "initial_prompt": "hello",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test"
    assert data["status"] == "created"


def test_get_session(client):
    resp = client.post("/api/sessions", json={
        "name": "test",
        "project_dir": "/tmp",
        "initial_prompt": "hello",
    })
    sid = resp.json()["id"]
    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sid


def test_get_session_not_found(client):
    resp = client.get("/api/sessions/nonexistent")
    assert resp.status_code == 404


def test_delete_session(client):
    resp = client.post("/api/sessions", json={
        "name": "test",
        "project_dir": "/tmp",
        "initial_prompt": "hello",
    })
    sid = resp.json()["id"]
    resp = client.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 204


def test_list_templates_empty(client):
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_template(client):
    resp = client.post("/api/templates", json={
        "name": "debug",
        "initial_prompt": "fix it",
    })
    assert resp.status_code == 201
    assert resp.json()["name"] == "debug"


def test_list_projects(client, tmp_path):
    proj = tmp_path / "projects" / "my-app"
    proj.mkdir(parents=True)
    (proj / "package.json").touch()
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()
    assert len(projects) == 1
    assert projects[0]["name"] == "my-app"


def test_server_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_sessions" in data


def test_register_push_token(client):
    resp = client.post("/api/push/register", json={
        "expo_push_token": "ExponentPushToken[abc]",
    })
    assert resp.status_code == 200
```

**Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_routes.py -v`

**Step 3: Implement routes**

```python
# src/claude_code_remote/routes.py
"""REST API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import Response

from claude_code_remote.models import (
    SessionCreate, TemplateCreate, ProjectRegister,
    PushRegister, PushSettings, SessionStatus,
    ApprovalResponse,
)
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.projects import scan_directory
from claude_code_remote.push import PushManager


def create_router(
    session_mgr: SessionManager,
    template_store: TemplateStore,
    push_mgr: PushManager,
    scan_dirs: list[str],
) -> APIRouter:
    router = APIRouter()

    # --- Sessions ---

    @router.get("/sessions")
    async def list_sessions(status: SessionStatus | None = None, project_dir: str | None = None):
        return session_mgr.list_sessions(status=status, project_dir=project_dir)

    @router.post("/sessions", status_code=201)
    async def create_session(req: SessionCreate):
        try:
            session = session_mgr.create_session(req)
            return session
        except RuntimeError as e:
            raise HTTPException(status_code=429, detail=str(e))

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        session_mgr.delete_session(session_id)
        return Response(status_code=204)

    @router.post("/sessions/{session_id}/send")
    async def send_prompt(session_id: str, body: dict):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        prompt = body.get("prompt", "")
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")
        await session_mgr.send_prompt(session_id, prompt)
        return {"ok": True}

    @router.post("/sessions/{session_id}/approve")
    async def approve_tool(session_id: str):
        await session_mgr.approve_tool_use(session_id)
        return {"ok": True}

    @router.post("/sessions/{session_id}/deny")
    async def deny_tool(session_id: str, body: ApprovalResponse | None = None):
        reason = body.reason if body else None
        await session_mgr.deny_tool_use(session_id, reason)
        return {"ok": True}

    @router.post("/sessions/{session_id}/pause")
    async def pause_session(session_id: str):
        await session_mgr.pause_session(session_id)
        return {"ok": True}

    @router.post("/sessions/{session_id}/resume")
    async def resume_session(session_id: str, body: dict):
        prompt = body.get("prompt", "")
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")
        await session_mgr.send_prompt(session_id, prompt)
        return {"ok": True}

    # --- Templates ---

    @router.get("/templates")
    async def list_templates():
        return template_store.list()

    @router.post("/templates", status_code=201)
    async def create_template(req: TemplateCreate):
        return template_store.create(req)

    @router.put("/templates/{template_id}")
    async def update_template(template_id: str, req: TemplateCreate):
        try:
            return template_store.update(template_id, req)
        except ValueError:
            raise HTTPException(status_code=404, detail="Template not found")

    @router.delete("/templates/{template_id}", status_code=204)
    async def delete_template(template_id: str):
        template_store.delete(template_id)
        return Response(status_code=204)

    # --- Projects ---

    @router.get("/projects")
    async def list_projects():
        all_projects = []
        for d in scan_dirs:
            expanded = Path(d).expanduser()
            all_projects.extend(scan_directory(expanded))
        return all_projects

    @router.post("/projects")
    async def register_project(req: ProjectRegister):
        path = Path(req.path).expanduser()
        if not path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
        # Add to scan_dirs for this session
        scan_dirs.append(str(path.parent))
        return {"ok": True, "path": str(path)}

    # --- System ---

    @router.get("/status")
    async def server_status():
        sessions = session_mgr.list_sessions()
        active = sum(1 for s in sessions if s.status in (
            SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL
        ))
        return {
            "status": "ok",
            "active_sessions": active,
            "total_sessions": len(sessions),
        }

    # --- Push ---

    @router.post("/push/register")
    async def register_push(req: PushRegister):
        push_mgr.register_token(req.expo_push_token)
        return {"ok": True}

    @router.get("/push/settings")
    async def get_push_settings():
        return push_mgr.get_settings()

    @router.put("/push/settings")
    async def update_push_settings(settings: PushSettings):
        push_mgr.update_settings(settings)
        return {"ok": True}

    return router
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_routes.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/routes.py tests/test_routes.py
git commit -m "feat: add REST API routes"
```

---

### Task 10: WebSocket Endpoint

**Files:**
- Create: `src/claude_code_remote/websocket.py`
- Create: `tests/test_websocket.py`

**Step 1: Write tests**

```python
# tests/test_websocket.py
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_code_remote.websocket import create_ws_router
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.models import SessionCreate


@pytest.fixture
def app(tmp_path):
    session_mgr = SessionManager(session_dir=tmp_path / "sessions")
    req = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    session = session_mgr.create_session(req)

    ws_router = create_ws_router(session_mgr)
    app = FastAPI()
    app.include_router(ws_router)
    app.state.test_session_id = session.id
    return app


def test_ws_connect_invalid_session(app):
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/sessions/nonexistent"):
            pass


def test_ws_connect_valid_session(app):
    client = TestClient(app)
    sid = app.state.test_session_id
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        # Connection should succeed — just close immediately
        pass
```

**Step 2: Run tests — expect FAIL**

Run: `python -m pytest tests/test_websocket.py -v`

**Step 3: Implement WebSocket endpoint**

```python
# src/claude_code_remote/websocket.py
"""WebSocket endpoint for streaming session events."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from claude_code_remote.session_manager import SessionManager
from claude_code_remote.models import WSMessage

logger = logging.getLogger(__name__)


def create_ws_router(session_mgr: SessionManager) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/sessions/{session_id}")
    async def session_stream(websocket: WebSocket, session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            await websocket.close(code=4004, reason="Session not found")
            return

        await websocket.accept()

        # Send existing messages as backfill
        for msg in session.messages:
            await websocket.send_json(msg)

        # Subscribe to new events
        queue: asyncio.Queue[WSMessage] = asyncio.Queue()

        async def on_event(msg: WSMessage):
            await queue.put(msg)

        session_mgr.subscribe(session_id, on_event)

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    await websocket.send_json(msg.model_dump(mode="json"))
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_json({"type": "ping"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"WebSocket error for session {session_id}: {e}")
        finally:
            session_mgr.unsubscribe(session_id, on_event)

    return router
```

**Step 4: Run tests — expect PASS**

Run: `python -m pytest tests/test_websocket.py -v`

**Step 5: Commit**

```bash
git add src/claude_code_remote/websocket.py tests/test_websocket.py
git commit -m "feat: add WebSocket endpoint for session streaming"
```

---

### Task 11: Server Entry Point

**Files:**
- Create: `src/claude_code_remote/server.py`

**Step 1: Implement server**

```python
# src/claude_code_remote/server.py
"""FastAPI application factory and server entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from claude_code_remote.auth import TailscaleAuthMiddleware
from claude_code_remote.config import (
    ensure_dirs, load_config,
    SESSION_DIR, TEMPLATE_DIR, PUSH_FILE,
)
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.push import PushManager
from claude_code_remote.routes import create_router
from claude_code_remote.websocket import create_ws_router

logger = logging.getLogger(__name__)


def create_app(skip_auth: bool = False) -> FastAPI:
    """Create and configure the FastAPI application."""
    ensure_dirs()
    config = load_config()

    session_mgr = SessionManager(
        session_dir=SESSION_DIR,
        max_concurrent=config.get("max_concurrent_sessions", 5),
    )
    session_mgr.load_sessions()

    template_store = TemplateStore(TEMPLATE_DIR)
    push_mgr = PushManager(PUSH_FILE)
    scan_dirs = config.get("scan_directories", ["~/Developer"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Server starting up")
        yield
        logger.info("Server shutting down")
        await session_mgr.shutdown()

    app = FastAPI(title="Claude Code Remote", lifespan=lifespan)

    if not skip_auth:
        app.add_middleware(TailscaleAuthMiddleware)

    api_router = create_router(session_mgr, template_store, push_mgr, scan_dirs)
    app.include_router(api_router, prefix="/api")

    ws_router = create_ws_router(session_mgr)
    app.include_router(ws_router)

    # Stash references for CLI access
    app.state.session_mgr = session_mgr
    app.state.push_mgr = push_mgr

    return app


def run_server(host: str, port: int, skip_auth: bool = False) -> None:
    """Run the server with uvicorn."""
    import uvicorn
    app = create_app(skip_auth=skip_auth)
    uvicorn.run(app, host=host, port=port, log_level="info")
```

**Step 2: Verify it imports cleanly**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -c "from claude_code_remote.server import create_app; print('OK')"`

**Step 3: Commit**

```bash
git add src/claude_code_remote/server.py
git commit -m "feat: add FastAPI server entry point"
```

---

### Task 12: Update CLI

**Files:**
- Modify: `src/claude_code_remote/cli.py`

**Step 1: Rewrite cli.py**

```python
"""CLI entry point — the `ccr` command."""

import shutil
import subprocess
import sys
import click

from claude_code_remote import __version__


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__, prog_name="ccr")
def cli():
    """Claude Code Remote — manage Claude Code sessions from any device over Tailscale."""


@cli.command()
@click.option("-d", "--daemon", is_flag=True, help="Run in background.")
@click.option("--no-auth", is_flag=True, help="Disable Tailscale auth (for local dev).")
def start(daemon, no_auth):
    """Start the API server."""
    from claude_code_remote import tailscale
    from claude_code_remote.config import load_config, PID_DIR, LOG_DIR, ensure_dirs

    ensure_dirs()
    config = load_config()
    port = config.get("port", 8080)

    if no_auth:
        host = "127.0.0.1"
        click.echo(f"Starting server on {host}:{port} (auth disabled)")
    else:
        host = tailscale.require_ip()
        click.echo(f"Starting server on {host}:{port}")

    if daemon:
        log_file = LOG_DIR / "server.log"
        pid_file = PID_DIR / "server.pid"
        with open(log_file, "a") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "claude_code_remote.server_main",
                 "--host", host, "--port", str(port)]
                + (["--no-auth"] if no_auth else []),
                stdout=log, stderr=log,
                start_new_session=True,
            )
            pid_file.write_text(str(proc.pid))
        click.echo(f"Server running in background (PID {proc.pid})")
        click.echo(f"  API: http://{host}:{port}/api/status")
        click.echo(f"  Log: {log_file}")

        # Start caffeinate
        try:
            caf = subprocess.Popen(
                ["caffeinate", "-di", "-w", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            (PID_DIR / "caffeinate.pid").write_text(str(caf.pid))
        except FileNotFoundError:
            pass
    else:
        from claude_code_remote.server import run_server
        run_server(host=host, port=port, skip_auth=no_auth)


@cli.command()
def stop():
    """Stop the API server."""
    from claude_code_remote.config import PID_DIR
    import signal

    for name in ["server", "caffeinate"]:
        pid_file = PID_DIR / f"{name}.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                import os
                os.kill(pid, signal.SIGTERM)
                click.echo(f"Stopped {name} (PID {pid})")
            except (ProcessLookupError, ValueError):
                click.echo(f"{name} was not running")
            pid_file.unlink(missing_ok=True)
        else:
            click.echo(f"{name} is not running")


@cli.command()
def status():
    """Show server status."""
    from claude_code_remote import tailscale
    from claude_code_remote.config import PID_DIR, load_config
    import os

    ip = tailscale.get_ip()
    dns = tailscale.get_dns_name()
    host = dns or ip
    config = load_config()
    port = config.get("port", 8080)

    click.echo(f"Tailscale IP:  {ip or 'Not connected'}")
    click.echo(f"MagicDNS:      {dns or 'Not available'}")
    click.echo()

    pid_file = PID_DIR / "server.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            click.echo(click.style("  ● ", fg="green") + f"server (PID {pid})")
            if host:
                click.echo(f"  API: http://{host}:{port}/api/status")
        except (ProcessLookupError, ValueError):
            click.echo(click.style("  ○ ", fg="red") + "server (stale PID)")
    else:
        click.echo(click.style("  ○ ", fg="red") + "server")


@cli.command()
def doctor():
    """Check prerequisites and dependencies."""
    checks = [
        ("tailscale", "Install from https://tailscale.com"),
        ("claude", "npm install -g @anthropic-ai/claude-code"),
    ]
    all_ok = True
    for binary, hint in checks:
        found = shutil.which(binary)
        if found:
            click.echo(click.style("  ✓ ", fg="green") + f"{binary} ({found})")
        else:
            click.echo(click.style("  ✗ ", fg="red") + f"{binary} — {hint}")
            all_ok = False

    packages = ["fastapi", "uvicorn", "httpx", "pydantic", "click"]
    for pkg in packages:
        try:
            __import__(pkg)
            click.echo(click.style("  ✓ ", fg="green") + f"{pkg}")
        except ImportError:
            click.echo(click.style("  ✗ ", fg="red") + f"{pkg} — pip install {pkg}")
            all_ok = False

    if all_ok:
        click.echo()
        click.echo(click.style("All dependencies satisfied!", fg="green"))
```

**Step 2: Create server_main module for daemon mode**

```python
# src/claude_code_remote/server_main.py
"""Entry point for running server as a subprocess (daemon mode)."""

import argparse
from claude_code_remote.server import run_server

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-auth", action="store_true")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, skip_auth=args.no_auth)
```

**Step 3: Verify CLI loads**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m claude_code_remote.cli --help`

**Step 4: Commit**

```bash
git add src/claude_code_remote/cli.py src/claude_code_remote/server_main.py
git commit -m "feat: rewrite CLI for API server"
```

---

### Task 13: Remove Old Modules

**Files:**
- Delete: `src/claude_code_remote/voice.py`
- Delete: `src/claude_code_remote/voice_server.py`
- Delete: `src/claude_code_remote/tmux.py`
- Delete: `src/claude_code_remote/services.py`
- Delete: `src/claude_code_remote/menubar.py`

**Step 1: Remove old files**

```bash
cd /Users/gldc/Developer/claude-code-remote
rm -f src/claude_code_remote/voice.py
rm -f src/claude_code_remote/voice_server.py
rm -f src/claude_code_remote/tmux.py
rm -f src/claude_code_remote/services.py
rm -f src/claude_code_remote/menubar.py
```

**Step 2: Update __init__.py version**

Change `__version__` to `"0.2.0"` in `src/claude_code_remote/__init__.py`.

**Step 3: Run all tests**

Run: `python -m pytest tests/ -v`

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove deprecated tmux/ttyd/voice modules"
```

---

### Task 14: Update CLAUDE.md and README

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

**Step 1: Update CLAUDE.md**

Replace the architecture diagram, file overview, and setup instructions to reflect the new API server architecture. Remove all references to tmux, ttyd, voice wrapper, and menubar.

**Step 2: Update README.md**

Update to describe the new API server:
- New architecture diagram
- Updated installation instructions
- New CLI commands (`ccr start`, `ccr stop`, `ccr status`, `ccr doctor`)
- API endpoint documentation
- Link to companion Expo app

**Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update CLAUDE.md and README for API server"
```

---

### Task 15: Integration Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

```python
# tests/test_integration.py
"""Integration test for the full API server."""

import pytest
from fastapi.testclient import TestClient

from claude_code_remote.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("claude_code_remote.config.SESSION_DIR", tmp_path / "sessions")
    monkeypatch.setattr("claude_code_remote.config.TEMPLATE_DIR", tmp_path / "templates")
    monkeypatch.setattr("claude_code_remote.config.PUSH_FILE", tmp_path / "push.json")
    app = create_app(skip_auth=True)
    return TestClient(app)


def test_full_workflow(client):
    # Server status
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["active_sessions"] == 0

    # Create template
    resp = client.post("/api/templates", json={
        "name": "quick-fix",
        "initial_prompt": "fix the bug",
        "model": "sonnet",
    })
    assert resp.status_code == 201
    template_id = resp.json()["id"]

    # List templates
    resp = client.get("/api/templates")
    assert len(resp.json()) == 1

    # Create session
    resp = client.post("/api/sessions", json={
        "name": "debug-auth",
        "project_dir": "/tmp",
        "initial_prompt": "fix login bug",
        "template_id": template_id,
    })
    assert resp.status_code == 201
    session_id = resp.json()["id"]

    # Get session
    resp = client.get(f"/api/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "debug-auth"

    # List sessions
    resp = client.get("/api/sessions")
    assert len(resp.json()) == 1

    # Register push token
    resp = client.post("/api/push/register", json={
        "expo_push_token": "ExponentPushToken[test]",
    })
    assert resp.status_code == 200

    # Update push settings
    resp = client.put("/api/push/settings", json={
        "notify_approvals": True,
        "notify_completions": False,
        "notify_errors": True,
    })
    assert resp.status_code == 200

    # Delete session
    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 204

    # Delete template
    resp = client.delete(f"/api/templates/{template_id}")
    assert resp.status_code == 204


def test_session_limit(client):
    # Create max sessions
    for i in range(5):
        resp = client.post("/api/sessions", json={
            "name": f"s{i}",
            "project_dir": "/tmp",
            "initial_prompt": "x",
        })
        assert resp.status_code == 201
```

**Step 2: Run integration tests**

Run: `python -m pytest tests/test_integration.py -v`

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for API server"
```
