"""Tests for native session interop in the main /api/sessions routes."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_code_remote.models import DashboardSessionSummary
from claude_code_remote.hidden_sessions import HiddenSessionsStore


@pytest.fixture
def mock_native_reader():
    reader = MagicMock()
    reader.list_sessions.return_value = []
    reader.get_session.return_value = None
    reader.get_session_messages.return_value = ([], 0)
    reader.get_active_pid.return_value = None
    return reader


@pytest.fixture
def hidden_store(tmp_path):
    return HiddenSessionsStore(tmp_path / "hidden.json")


def _make_native(session_id="native-uuid-1234567890abcdef12345678", **kw):
    defaults = dict(
        id=session_id,
        name="my-project",
        project_dir="/Users/test/proj",
        source="native",
        status="completed",
        current_model="claude-sonnet-4-6",
        total_cost_usd=0.05,
        cost_is_estimated=True,
        message_count=10,
        git_branch="main",
        claude_session_id=session_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kw)
    return DashboardSessionSummary(**defaults)


def _test_client(session_mgr=None, native_reader=None, hidden_store=None):
    from claude_code_remote.routes import create_router

    if session_mgr is None:
        session_mgr = MagicMock()
        session_mgr.list_sessions.return_value = []
        session_mgr.get_session.return_value = None
    app = FastAPI()
    router = create_router(
        session_mgr,
        MagicMock(),
        MagicMock(),
        [],
        native_reader=native_reader,
        hidden_store=hidden_store,
    )
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_list_includes_native(mock_native_reader):
    mock_native_reader.list_sessions.return_value = [_make_native()]
    client = _test_client(native_reader=mock_native_reader)
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert any(s["source"] == "native" for s in sessions)


def test_get_native_by_id(mock_native_reader):
    native = _make_native()
    mock_native_reader.get_session.return_value = native
    mock_native_reader.get_session_messages.return_value = ([{"type": "user"}], 1)
    client = _test_client(native_reader=mock_native_reader)
    resp = client.get(f"/api/sessions/{native.id}")
    assert resp.status_code == 200
    assert resp.json()["source"] == "native"


def test_send_to_native_active_409(mock_native_reader):
    mock_native_reader.get_session.return_value = _make_native()
    mock_native_reader.get_active_pid.return_value = 12345
    client = _test_client(native_reader=mock_native_reader)
    resp = client.post(f"/api/sessions/{_make_native().id}/send", json={"prompt": "hi"})
    assert resp.status_code == 409


def test_hide_unhide(hidden_store):
    client = _test_client(hidden_store=hidden_store)
    assert client.post("/api/sessions/x/hide").status_code == 200
    assert hidden_store.is_hidden("x")
    assert client.post("/api/sessions/x/unhide").status_code == 200
    assert not hidden_store.is_hidden("x")


def test_hide_permanent(hidden_store):
    client = _test_client(hidden_store=hidden_store)
    assert client.post("/api/sessions/x/hide?permanent=true").status_code == 200
    assert hidden_store.is_permanently_hidden("x")
