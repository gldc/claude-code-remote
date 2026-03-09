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
        # Connection should succeed -- just close immediately
        pass
