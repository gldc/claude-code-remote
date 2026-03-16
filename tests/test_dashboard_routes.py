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


def test_resume_native_session(tmp_path, session_mgr, native_reader, cron_mgr):
    """Test resuming a native session creates a CCR session with --resume."""
    # Create a native session with a real project_dir (tmp_path exists)
    d = tmp_path / "resume_claude"
    projects = d / "projects" / "-tmp-resumetest"
    projects.mkdir(parents=True)
    sessions = d / "sessions"
    sessions.mkdir()
    project_dir = tmp_path / "resumetest"
    project_dir.mkdir()

    session_id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
    jsonl = projects / f"{session_id}.jsonl"
    import json

    with open(jsonl, "w") as f:
        f.write(
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "test"},
                    "uuid": "u1",
                    "timestamp": "2026-03-15T10:00:00.000Z",
                    "sessionId": session_id,
                    "cwd": str(project_dir),
                }
            )
            + "\n"
        )

    reader = NativeSessionReader(d)
    app = FastAPI()
    router = create_dashboard_router(session_mgr, reader, cron_mgr)
    app.include_router(router, prefix="/api/dashboard")
    client = TestClient(app)

    resp = client.post(
        f"/api/dashboard/sessions/{session_id}/resume",
        json={"prompt": "Continue working"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["status"] == "created"

    # Verify the CCR session was created with the right claude_session_id
    ccr_session = session_mgr.get_session(data["session_id"])
    assert ccr_session is not None
    assert ccr_session.claude_session_id == session_id
    assert "resumed" in ccr_session.name


def test_resume_nonexistent_session(client):
    resp = client.post(
        "/api/dashboard/sessions/nonexistent/resume",
        json={"prompt": "test"},
    )
    assert resp.status_code == 404


def test_cron_jobs_enriched(client, cron_mgr):
    # Create a cron job
    job = cron_mgr.create(
        CronJobCreate(
            name="Test Cron",
            schedule="0 9 * * *",
            execution_mode=CronExecutionMode.SPAWN,
            session_config=SessionCreate(
                name="cron-test",
                project_dir="/tmp",
                initial_prompt="test",
            ),
        )
    )
    resp = client.get("/api/dashboard/cron-jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Cron"
    assert "recent_runs" in data[0]
