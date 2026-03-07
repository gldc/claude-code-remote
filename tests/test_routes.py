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
    resp = client.post(
        "/api/sessions",
        json={
            "name": "test",
            "project_dir": "/tmp",
            "initial_prompt": "hello",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test"
    assert data["status"] == "created"


def test_get_session(client):
    resp = client.post(
        "/api/sessions",
        json={
            "name": "test",
            "project_dir": "/tmp",
            "initial_prompt": "hello",
        },
    )
    sid = resp.json()["id"]
    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sid


def test_get_session_not_found(client):
    resp = client.get("/api/sessions/nonexistent")
    assert resp.status_code == 404


def test_delete_session(client):
    resp = client.post(
        "/api/sessions",
        json={
            "name": "test",
            "project_dir": "/tmp",
            "initial_prompt": "hello",
        },
    )
    sid = resp.json()["id"]
    resp = client.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 204


def test_list_templates_empty(client):
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_template(client):
    resp = client.post(
        "/api/templates",
        json={
            "name": "debug",
            "initial_prompt": "fix it",
        },
    )
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
    resp = client.post(
        "/api/push/register",
        json={
            "expo_push_token": "ExponentPushToken[abc]",
        },
    )
    assert resp.status_code == 200
