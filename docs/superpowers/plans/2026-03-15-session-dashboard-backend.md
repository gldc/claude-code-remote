# Session Dashboard Backend Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add API endpoints that unify CCR sessions, native Claude Code sessions, and cron jobs into a single dashboard API.

**Architecture:** A `native_sessions.py` module discovers and parses Claude Code's local JSONL conversation files. A `dashboard.py` module provides unified API routes that merge native sessions with existing CCR sessions and cron data. New Pydantic models normalize the data. Everything is wired into the existing FastAPI server.

**Tech Stack:** Python, FastAPI, Pydantic, JSONL parsing

**Spec:** `docs/superpowers/specs/2026-03-15-session-dashboard-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/claude_code_remote/models.py` | Modify | Add `DashboardSessionSummary`, `DashboardSession`, `DashboardResumeRequest`, `CronJobWithRuns` |
| `src/claude_code_remote/native_sessions.py` | Create | Discover and parse native Claude Code JSONL sessions |
| `src/claude_code_remote/dashboard.py` | Create | Dashboard API routes (`/api/dashboard/*`) |
| `src/claude_code_remote/server.py` | Modify | Mount dashboard router and static files |
| `tests/test_native_sessions.py` | Create | Tests for JSONL parsing and session discovery |
| `tests/test_dashboard_routes.py` | Create | Tests for dashboard API routes |

---

## Chunk 1: Models and Native Session Parsing

### Task 1: Add dashboard Pydantic models

**Files:**
- Modify: `src/claude_code_remote/models.py` (append after line 486)

- [ ] **Step 1: Add the models**

Append to the end of `models.py`:

```python

# --- Dashboard ---


class DashboardSessionSummary(BaseModel):
    """Lightweight session summary for list views, unifying CCR and native sessions."""

    id: str
    name: str
    project_dir: str
    source: str  # "ccr" or "native"
    status: str
    current_model: str | None = None
    total_cost_usd: float = 0.0
    cost_is_estimated: bool = False
    message_count: int = 0
    context_percent: int | None = None
    git_branch: str | None = None
    created_at: datetime
    updated_at: datetime
    owner: str | None = None
    claude_session_id: str | None = None
    cron_job_id: str | None = None


class DashboardSession(DashboardSessionSummary):
    """Full session detail with messages."""

    messages: list[dict] = Field(default_factory=list)
    total_messages: int = 0  # Total count for pagination


class DashboardResumeRequest(BaseModel):
    prompt: str


class DashboardAnalytics(BaseModel):
    active_sessions: int = 0
    total_cost_7d: float = 0.0
    top_model: str | None = None
    active_cron_jobs: int = 0


class CronJobWithRuns(CronJob):
    """CronJob with recent execution history inlined."""

    recent_runs: list[CronJobRun] = Field(default_factory=list)
```

- [ ] **Step 2: Verify import**

Run: `python -c "from claude_code_remote.models import DashboardSessionSummary, DashboardSession, DashboardResumeRequest, DashboardAnalytics, CronJobWithRuns; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/models.py
git commit -m "feat(dashboard): add Pydantic models for dashboard API"
```

---

### Task 2: Create native_sessions.py — session discovery

**Files:**
- Create: `src/claude_code_remote/native_sessions.py`
- Create: `tests/test_native_sessions.py`

- [ ] **Step 1: Write tests for session discovery and JSONL parsing**

Create `tests/test_native_sessions.py`:

```python
"""Tests for native Claude Code session discovery and parsing."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_code_remote.native_sessions import NativeSessionReader


@pytest.fixture
def claude_dir(tmp_path):
    """Set up a fake ~/.claude directory structure."""
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    projects_dir.mkdir()
    sessions_dir.mkdir()
    return tmp_path


@pytest.fixture
def sample_jsonl(claude_dir):
    """Create a sample JSONL conversation file."""
    project_hash = "-Users-test-Developer-myproject"
    project_dir = claude_dir / "projects" / project_hash
    project_dir.mkdir()

    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    jsonl_file = project_dir / f"{session_id}.jsonl"

    events = [
        {
            "type": "user",
            "message": {"role": "user", "content": "Hello"},
            "uuid": "u1",
            "timestamp": "2026-03-15T10:00:00.000Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/myproject",
            "gitBranch": "main",
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-6",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi!"}],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
            "uuid": "a1",
            "timestamp": "2026-03-15T10:00:01.000Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/myproject",
            "gitBranch": "main",
        },
        {
            "type": "progress",
            "data": {"type": "hook_progress"},
            "uuid": "p1",
            "timestamp": "2026-03-15T10:00:00.500Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/myproject",
        },
    ]
    with open(jsonl_file, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return jsonl_file, session_id


@pytest.fixture
def history_jsonl(claude_dir):
    """Create a sample history.jsonl."""
    history_file = claude_dir / "history.jsonl"
    entries = [
        {
            "display": "Hello",
            "timestamp": 1741950000000,
            "project": "/Users/test/Developer/myproject",
            "sessionId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
    ]
    with open(history_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return history_file


def test_list_sessions(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    sessions = reader.list_sessions()
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "native"
    assert s.project_dir == "/Users/test/Developer/myproject"
    assert s.current_model == "claude-sonnet-4-6"
    assert s.message_count == 2  # user + assistant, not progress
    assert s.git_branch == "main"
    assert s.cost_is_estimated is True
    assert s.total_cost_usd > 0


def test_get_session_messages(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    session_id = sample_jsonl[1]
    messages, total = reader.get_session_messages(session_id, offset=0, limit=100)
    assert total == 2  # user + assistant
    assert messages[0]["type"] == "user"
    assert messages[1]["type"] == "assistant"


def test_get_session_messages_pagination(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    session_id = sample_jsonl[1]
    messages, total = reader.get_session_messages(session_id, offset=0, limit=1)
    assert len(messages) == 1
    assert total == 2


def test_get_session(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    session_id = sample_jsonl[1]
    s = reader.get_session(session_id)
    assert s is not None
    assert s.id == session_id
    assert s.source == "native"


def test_get_session_not_found(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    s = reader.get_session("nonexistent-session-id")
    assert s is None


def test_malformed_jsonl_skipped(claude_dir):
    """Malformed lines should be skipped, not crash."""
    project_dir = claude_dir / "projects" / "-Users-test-Developer-broken"
    project_dir.mkdir()
    session_id = "11111111-2222-3333-4444-555555555555"
    jsonl_file = project_dir / f"{session_id}.jsonl"
    with open(jsonl_file, "w") as f:
        f.write("NOT VALID JSON\n")
        f.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "test"},
            "uuid": "u1",
            "timestamp": "2026-03-15T10:00:00.000Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/broken",
        }) + "\n")

    reader = NativeSessionReader(claude_dir)
    sessions = reader.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].message_count == 1


def test_cost_estimation(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    sessions = reader.list_sessions()
    s = sessions[0]
    # sonnet: $3/1M input, $15/1M output
    # 100 input + 10 output = $0.0003 + $0.00015 = $0.00045
    assert abs(s.total_cost_usd - 0.00045) < 0.0001


def test_cache_invalidation(claude_dir, sample_jsonl):
    """Metadata should update when file changes."""
    reader = NativeSessionReader(claude_dir)
    sessions = reader.list_sessions()
    assert sessions[0].message_count == 2

    # Append another user message
    jsonl_file = sample_jsonl[0]
    with open(jsonl_file, "a") as f:
        f.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "Another message"},
            "uuid": "u2",
            "timestamp": "2026-03-15T10:01:00.000Z",
            "sessionId": sample_jsonl[1],
            "cwd": "/Users/test/Developer/myproject",
        }) + "\n")

    sessions = reader.list_sessions()
    assert sessions[0].message_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_native_sessions.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement NativeSessionReader**

Create `src/claude_code_remote/native_sessions.py`:

```python
"""Discover and parse native Claude Code sessions from ~/.claude/projects/."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from claude_code_remote.models import DashboardSessionSummary

logger = logging.getLogger(__name__)

# Model pricing: (input_per_1m, output_per_1m)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
}
DEFAULT_PRICING = MODEL_PRICING["claude-sonnet-4-6"]


def _estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost from token counts using model-specific pricing."""
    pricing = MODEL_PRICING.get(model or "", DEFAULT_PRICING)
    return (input_tokens * pricing[0] + output_tokens * pricing[1]) / 1_000_000


class _CachedMetadata:
    """Cached metadata for a single JSONL session file."""

    __slots__ = ("summary", "mtime")

    def __init__(self, summary: DashboardSessionSummary, mtime: float):
        self.summary = summary
        self.mtime = mtime


class NativeSessionReader:
    """Reads native Claude Code sessions from the local filesystem."""

    DISPLAYED_TYPES = {"user", "assistant", "system"}

    def __init__(self, claude_dir: Path | None = None):
        self._claude_dir = claude_dir or Path.home() / ".claude"
        self._projects_dir = self._claude_dir / "projects"
        self._sessions_dir = self._claude_dir / "sessions"
        self._cache: dict[str, _CachedMetadata] = {}
        # Map session_id -> jsonl file path (built during scans)
        self._session_paths: dict[str, Path] = {}

    def _parse_metadata(self, jsonl_path: Path) -> DashboardSessionSummary | None:
        """Parse a JSONL file to extract session metadata."""
        session_id: str | None = None
        project_dir: str | None = None
        git_branch: str | None = None
        model: str | None = None
        total_input = 0
        total_output = 0
        message_count = 0
        first_ts: str | None = None
        last_ts: str | None = None

        try:
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    ts = event.get("timestamp")

                    if session_id is None:
                        session_id = event.get("sessionId")
                    if project_dir is None:
                        project_dir = event.get("cwd")
                    if git_branch is None:
                        git_branch = event.get("gitBranch")
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts

                    if event_type in self.DISPLAYED_TYPES:
                        message_count += 1

                    if event_type == "assistant":
                        msg = event.get("message", {})
                        if msg.get("model"):
                            model = msg["model"]
                        usage = msg.get("usage", {})
                        total_input += usage.get("input_tokens", 0)
                        total_input += usage.get("cache_read_input_tokens", 0)
                        total_input += usage.get("cache_creation_input_tokens", 0)
                        total_output += usage.get("output_tokens", 0)
        except OSError:
            return None

        if session_id is None:
            return None

        cost = _estimate_cost(model, total_input, total_output)

        # Determine status by checking if a live process owns this session
        status = self._check_active_status(session_id)

        now = datetime.now(timezone.utc)
        created = datetime.fromisoformat(first_ts.replace("Z", "+00:00")) if first_ts else now
        updated = datetime.fromisoformat(last_ts.replace("Z", "+00:00")) if last_ts else now

        # Derive name from project dir basename
        name = Path(project_dir).name if project_dir else session_id[:12]

        return DashboardSessionSummary(
            id=session_id,
            name=name,
            project_dir=project_dir or "",
            source="native",
            status=status,
            current_model=model,
            total_cost_usd=round(cost, 5),
            cost_is_estimated=True,
            message_count=message_count,
            git_branch=git_branch,
            created_at=created,
            updated_at=updated,
            claude_session_id=session_id,
        )

    def _check_active_status(self, session_id: str) -> str:
        """Check if a native session has an active process."""
        if not self._sessions_dir.exists():
            return "completed"
        for sf in self._sessions_dir.glob("*.json"):
            try:
                data = json.loads(sf.read_text())
                if data.get("sessionId") == session_id:
                    pid = data.get("pid")
                    if pid:
                        try:
                            os.kill(pid, 0)
                            return "active"
                        except (ProcessLookupError, PermissionError):
                            pass
            except (json.JSONDecodeError, OSError):
                continue
        return "completed"

    def _scan_sessions(self) -> None:
        """Scan projects directory and update cache."""
        if not self._projects_dir.exists():
            return

        seen: set[str] = set()
        for project_dir in self._projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                # Session ID is the filename without extension
                session_id_candidate = jsonl_file.stem
                # Skip files that don't look like UUIDs
                if len(session_id_candidate) < 30:
                    continue

                try:
                    mtime = jsonl_file.stat().st_mtime
                except OSError:
                    continue

                cached = self._cache.get(session_id_candidate)
                if cached and cached.mtime == mtime:
                    seen.add(session_id_candidate)
                    self._session_paths[session_id_candidate] = jsonl_file
                    continue

                summary = self._parse_metadata(jsonl_file)
                if summary:
                    self._cache[summary.id] = _CachedMetadata(summary, mtime)
                    self._session_paths[summary.id] = jsonl_file
                    seen.add(summary.id)

        # Remove stale entries
        for stale_id in set(self._cache.keys()) - seen:
            del self._cache[stale_id]
            self._session_paths.pop(stale_id, None)

    def list_sessions(self) -> list[DashboardSessionSummary]:
        """List all native sessions with cached metadata."""
        self._scan_sessions()
        return [c.summary for c in self._cache.values()]

    def get_session(self, session_id: str) -> DashboardSessionSummary | None:
        """Get metadata for a single session."""
        self._scan_sessions()
        cached = self._cache.get(session_id)
        return cached.summary if cached else None

    def get_session_messages(
        self, session_id: str, offset: int = 0, limit: int = 100
    ) -> tuple[list[dict], int]:
        """Get paginated messages for a session.

        Returns (messages, total_count) where messages are only displayed types.
        """
        self._scan_sessions()
        jsonl_path = self._session_paths.get(session_id)
        if not jsonl_path or not jsonl_path.exists():
            return [], 0

        messages: list[dict] = []
        try:
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") in self.DISPLAYED_TYPES:
                        messages.append(event)
        except OSError:
            return [], 0

        total = len(messages)
        return messages[offset : offset + limit], total
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_native_sessions.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_code_remote/native_sessions.py tests/test_native_sessions.py
git commit -m "feat(dashboard): add native session reader with JSONL parsing and cost estimation"
```

---

## Chunk 2: Dashboard API Routes and Server Wiring

### Task 3: Create dashboard.py routes

**Files:**
- Create: `src/claude_code_remote/dashboard.py`
- Create: `tests/test_dashboard_routes.py`

- [ ] **Step 1: Write tests for dashboard routes**

Create `tests/test_dashboard_routes.py`:

```python
"""Tests for dashboard API routes."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_code_remote.dashboard import create_dashboard_router
from claude_code_remote.native_sessions import NativeSessionReader
from claude_code_remote.models import (
    CronExecutionMode,
    CronJobCreate,
    Session,
    SessionCreate,
    SessionStatus,
)
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.cron_manager import CronManager


@pytest.fixture
def session_dir(tmp_path):
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture
def session_mgr(session_dir):
    mgr = SessionManager(
        session_dir=session_dir,
        max_concurrent=5,
        api_url="http://localhost:8080",
        push_mgr=None,
    )
    return mgr


@pytest.fixture
def claude_dir(tmp_path):
    """Fake ~/.claude with one native session."""
    d = tmp_path / "claude"
    projects = d / "projects" / "-Users-test-Developer-myproject"
    projects.mkdir(parents=True)
    sessions = d / "sessions"
    sessions.mkdir()

    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    jsonl = projects / f"{session_id}.jsonl"
    events = [
        {
            "type": "user",
            "message": {"role": "user", "content": "Hello"},
            "uuid": "u1",
            "timestamp": "2026-03-15T10:00:00.000Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/myproject",
            "gitBranch": "main",
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-6",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi!"}],
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
            "uuid": "a1",
            "timestamp": "2026-03-15T10:00:01.000Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/myproject",
            "gitBranch": "main",
        },
    ]
    with open(jsonl, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    return d


@pytest.fixture
def native_reader(claude_dir):
    return NativeSessionReader(claude_dir)


@pytest.fixture
def cron_mgr(tmp_path):
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir()
    return CronManager(
        cron_dir=cron_dir,
        history_file=tmp_path / "cron_history.jsonl",
        session_mgr=None,
    )


@pytest.fixture
def app(session_mgr, native_reader, cron_mgr):
    app = FastAPI()
    router = create_dashboard_router(session_mgr, native_reader, cron_mgr)
    app.include_router(router, prefix="/api/dashboard")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_list_sessions_native_only(client):
    resp = client.get("/api/dashboard/sessions")
    assert resp.status_code == 200
    data = resp.json()
    # Should have the native session from fixture (no CCR sessions created)
    assert len(data["sessions"]) == 1
    assert data["sessions"][0]["source"] == "native"


def test_list_sessions_with_source_filter(client):
    resp = client.get("/api/dashboard/sessions?source=ccr")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 0

    resp = client.get("/api/dashboard/sessions?source=native")
    assert resp.status_code == 200
    assert len(resp.json()["sessions"]) == 1


def test_get_native_session_detail(client):
    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    resp = client.get(f"/api/dashboard/sessions/{session_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == session_id
    assert data["source"] == "native"
    assert len(data["messages"]) == 2
    assert data["total_messages"] == 2


def test_get_session_not_found(client):
    resp = client.get("/api/dashboard/sessions/nonexistent")
    assert resp.status_code == 404


def test_analytics(client):
    resp = client.get("/api/dashboard/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_sessions" in data
    assert "total_cost_7d" in data
    assert "active_cron_jobs" in data


def test_cron_jobs_enriched(client, cron_mgr):
    # Create a cron job
    job = cron_mgr.create(CronJobCreate(
        name="Test Cron",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=SessionCreate(
            name="cron-test",
            project_dir="/tmp",
            initial_prompt="test",
        ),
    ))
    resp = client.get("/api/dashboard/cron-jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Cron"
    assert "recent_runs" in data[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement dashboard routes**

Create `src/claude_code_remote/dashboard.py`:

```python
"""Dashboard API routes -- unified view of CCR and native sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from claude_code_remote.cron_manager import CronManager
from claude_code_remote.models import (
    CronJobWithRuns,
    DashboardAnalytics,
    DashboardResumeRequest,
    DashboardSession,
    DashboardSessionSummary,
    SessionCreate,
)
from claude_code_remote.native_sessions import NativeSessionReader
from claude_code_remote.session_manager import SessionManager

logger = logging.getLogger(__name__)


def create_dashboard_router(
    session_mgr: SessionManager,
    native_reader: NativeSessionReader,
    cron_mgr: CronManager | None = None,
) -> APIRouter:
    router = APIRouter()

    def _ccr_summary_to_dashboard(summary) -> DashboardSessionSummary:
        """Convert a CCR SessionSummary to DashboardSessionSummary.

        Works with SessionSummary from list_sessions() (no messages/owner fields).
        """
        return DashboardSessionSummary(
            id=summary.id,
            name=summary.name,
            project_dir=summary.project_dir,
            source="ccr",
            status=summary.status.value if hasattr(summary.status, "value") else summary.status,
            current_model=summary.current_model,
            total_cost_usd=summary.total_cost_usd,
            cost_is_estimated=False,
            context_percent=summary.context_percent,
            git_branch=summary.git_branch,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            cron_job_id=summary.cron_job_id,
        )

    def _ccr_session_to_dashboard(session) -> DashboardSessionSummary:
        """Convert a full CCR Session to DashboardSessionSummary."""
        return DashboardSessionSummary(
            id=session.id,
            name=session.name,
            project_dir=session.project_dir,
            source="ccr",
            status=session.status.value if hasattr(session.status, "value") else session.status,
            current_model=session.current_model,
            total_cost_usd=session.total_cost_usd,
            cost_is_estimated=False,
            message_count=len(session.messages),
            context_percent=session.context_percent,
            git_branch=session.git_branch,
            created_at=session.created_at,
            updated_at=session.updated_at,
            owner=session.owner,
            claude_session_id=session.claude_session_id,
            cron_job_id=session.cron_job_id,
        )

    @router.get("/sessions")
    def list_sessions(
        source: str | None = None,
        status: str | None = None,
        project: str | None = None,
        q: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ):
        """List sessions from both CCR and native sources."""
        all_sessions: list[DashboardSessionSummary] = []

        # CCR sessions
        if source is None or source == "ccr":
            if q:
                # search_sessions returns list[dict] with session_id keys
                seen_ids: set[str] = set()
                for result in session_mgr.search_sessions(q):
                    sid = result["session_id"]
                    if sid not in seen_ids:
                        seen_ids.add(sid)
                        s = session_mgr.get_session(sid)
                        if s:
                            all_sessions.append(_ccr_session_to_dashboard(s))
            else:
                # list_sessions returns list[SessionSummary] (no messages)
                for s in session_mgr.list_sessions():
                    all_sessions.append(_ccr_summary_to_dashboard(s))

        # Native sessions
        if source is None or source == "native":
            native = native_reader.list_sessions()
            if q:
                q_lower = q.lower()
                native = [
                    s for s in native
                    if q_lower in s.name.lower() or q_lower in s.project_dir.lower()
                ]
            all_sessions.extend(native)

        # Apply filters
        if status:
            all_sessions = [s for s in all_sessions if s.status == status]
        if project:
            project_lower = project.lower()
            all_sessions = [
                s for s in all_sessions if project_lower in s.project_dir.lower()
            ]

        # Sort by updated_at descending
        all_sessions.sort(key=lambda s: s.updated_at, reverse=True)

        # Paginate
        total = len(all_sessions)
        start = (page - 1) * page_size
        page_sessions = all_sessions[start : start + page_size]

        return {
            "sessions": [s.model_dump() for s in page_sessions],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @router.get("/sessions/{session_id}")
    def get_session(
        session_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
    ):
        """Get session detail with paginated messages."""
        # Try CCR first
        ccr_session = session_mgr.get_session(session_id)
        if ccr_session:
            messages = ccr_session.messages
            total = len(messages)
            return DashboardSession(
                **_ccr_session_to_dashboard(ccr_session).model_dump(),
                messages=messages[offset : offset + limit],
                total_messages=total,
            ).model_dump()

        # Try native
        native_summary = native_reader.get_session(session_id)
        if native_summary:
            messages, total = native_reader.get_session_messages(
                session_id, offset=offset, limit=limit
            )
            return DashboardSession(
                **native_summary.model_dump(),
                messages=messages,
                total_messages=total,
            ).model_dump()

        raise HTTPException(status_code=404, detail="Session not found")

    @router.get("/analytics")
    def get_analytics():
        """Summary stats for the dashboard header."""
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        # CCR sessions (list_sessions returns SessionSummary objects)
        ccr_sessions = session_mgr.list_sessions()
        active_ccr = sum(
            1 for s in ccr_sessions
            if s.status.value in ("running", "idle", "awaiting_approval")
        )

        # Native sessions
        native_sessions = native_reader.list_sessions()
        active_native = sum(1 for s in native_sessions if s.status == "active")

        # Cost (last 7 days)
        cost_7d = 0.0
        model_counts: dict[str, int] = {}

        for s in ccr_sessions:
            if s.updated_at >= seven_days_ago:
                cost_7d += s.total_cost_usd
            if s.current_model:
                model_counts[s.current_model] = model_counts.get(s.current_model, 0) + 1

        for s in native_sessions:
            if s.updated_at >= seven_days_ago:
                cost_7d += s.total_cost_usd
            if s.current_model:
                model_counts[s.current_model] = model_counts.get(s.current_model, 0) + 1

        top_model = max(model_counts, key=model_counts.get) if model_counts else None

        # Cron jobs
        active_cron = 0
        if cron_mgr:
            active_cron = sum(1 for j in cron_mgr.list() if j.enabled)

        return DashboardAnalytics(
            active_sessions=active_ccr + active_native,
            total_cost_7d=round(cost_7d, 2),
            top_model=top_model,
            active_cron_jobs=active_cron,
        ).model_dump()

    @router.post("/sessions/{session_id}/resume")
    def resume_native_session(session_id: str, req: DashboardResumeRequest):
        """Resume a native session by creating a CCR session with --resume."""
        native_summary = native_reader.get_session(session_id)
        if not native_summary:
            raise HTTPException(status_code=404, detail="Native session not found")

        # Create a CCR session pointing to the native session
        ccr_session = session_mgr.create_session(
            SessionCreate(
                name=f"{native_summary.name} (resumed)",
                project_dir=native_summary.project_dir,
                initial_prompt=req.prompt,
            )
        )
        # Set the claude_session_id so --resume picks up the conversation
        ccr_session.claude_session_id = native_summary.claude_session_id
        session_mgr.persist_session(ccr_session.id)

        return {"session_id": ccr_session.id, "status": "created"}

    @router.get("/cron-jobs")
    def list_cron_jobs_enriched():
        """List all cron jobs with recent runs inlined."""
        if not cron_mgr:
            return []
        jobs = cron_mgr.list()
        result = []
        for job in jobs:
            runs = cron_mgr.get_history(job.id, limit=5)
            enriched = CronJobWithRuns(
                **job.model_dump(),
                recent_runs=runs,
            )
            result.append(enriched.model_dump())
        return result

    return router
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_dashboard_routes.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_code_remote/dashboard.py tests/test_dashboard_routes.py
git commit -m "feat(dashboard): add dashboard API routes with unified session list"
```

---

### Task 4: Wire dashboard into the server

**Files:**
- Modify: `src/claude_code_remote/server.py`

- [ ] **Step 1: Add imports to server.py**

Add after the existing imports (after line 38 `from claude_code_remote.terminal import ...`):

```python
from claude_code_remote.native_sessions import NativeSessionReader
from claude_code_remote.dashboard import create_dashboard_router
```

- [ ] **Step 2: Instantiate NativeSessionReader and mount dashboard router**

In `create_app()`, add after the `terminal_mgr` line (find `terminal_mgr = TerminalManager()`):

```python
    native_reader = NativeSessionReader()
```

Then add after the `app.include_router(terminal_router)` line (find `app.include_router(terminal_router)`):

```python
    dashboard_router = create_dashboard_router(session_mgr, native_reader, cron_mgr)
    app.include_router(dashboard_router, prefix="/api/dashboard")
```

- [ ] **Step 3: Verify import**

Run: `python -c "from claude_code_remote.server import create_app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add src/claude_code_remote/server.py
git commit -m "feat(dashboard): wire dashboard routes into FastAPI server"
```

---

### Task 5: Manual smoke test

- [ ] **Step 1: Start the server**

Run: `ccr start --no-auth`

- [ ] **Step 2: Test session list**

Run: `curl -s http://127.0.0.1:8080/api/dashboard/sessions | python -m json.tool | head -30`
Expected: JSON with `sessions` array containing native sessions from `~/.claude/projects/`

- [ ] **Step 3: Test analytics**

Run: `curl -s http://127.0.0.1:8080/api/dashboard/analytics | python -m json.tool`
Expected: JSON with `active_sessions`, `total_cost_7d`, `top_model`, `active_cron_jobs`

- [ ] **Step 4: Test session detail**

Pick a session ID from the list response and:
Run: `curl -s http://127.0.0.1:8080/api/dashboard/sessions/<session-id> | python -m json.tool | head -20`
Expected: JSON with `messages` array and `total_messages` count

- [ ] **Step 5: Test cron jobs enriched**

Run: `curl -s http://127.0.0.1:8080/api/dashboard/cron-jobs | python -m json.tool`
Expected: JSON array of cron jobs with `recent_runs` arrays

- [ ] **Step 6: Stop the server and commit if any fixes were needed**

Run: `ccr stop`
