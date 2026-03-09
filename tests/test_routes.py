# tests/test_routes.py
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_code_remote.routes import create_router
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore, BUILTIN_TEMPLATES
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
    # Session is created and prompt is sent, status depends on claude CLI availability
    assert resp.status_code in (201, 429, 500)
    if resp.status_code == 201:
        data = resp.json()
        assert data["name"] == "test"


def test_get_session(client):
    resp = client.post(
        "/api/sessions",
        json={
            "name": "test",
            "project_dir": "/tmp",
            "initial_prompt": "hello",
        },
    )
    if resp.status_code != 201:
        pytest.skip("Session creation failed (no Claude CLI)")
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
    if resp.status_code != 201:
        pytest.skip("Session creation failed (no Claude CLI)")
    sid = resp.json()["id"]
    resp = client.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 204


def test_list_templates(client):
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    # Should have built-in templates
    assert len(resp.json()) == len(BUILTIN_TEMPLATES)


def test_list_templates_with_tag_filter(client):
    resp = client.get("/api/templates?tag=review")
    assert resp.status_code == 200
    templates = resp.json()
    assert all("review" in t["tags"] for t in templates)


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


def test_search_sessions_short_query(client):
    resp = client.get("/api/sessions/search?q=a")
    assert resp.status_code == 400


def test_search_sessions_empty(client):
    resp = client.get("/api/sessions/search?q=test")
    assert resp.status_code == 200
    assert resp.json() == []


def test_usage_endpoint(client):
    resp = client.get("/api/usage")
    # Returns 503 when usage_client not configured
    assert resp.status_code == 503


def test_skills_endpoint(client):
    resp = client.get("/api/skills")
    assert resp.status_code == 200


def test_approval_rules_endpoint(client):
    resp = client.get("/api/approval-rules")
    # Returns 503 when approval_store not configured
    assert resp.status_code == 503


def test_mcp_servers_endpoint(client):
    resp = client.get("/api/mcp/servers")
    assert resp.status_code == 200


def test_workflows_endpoint(client):
    resp = client.get("/api/workflows")
    # Returns 503 when workflow_engine not configured
    assert resp.status_code == 503
