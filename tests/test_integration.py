"""Integration test for the full API server."""

import pytest
from fastapi.testclient import TestClient

from claude_code_remote.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("claude_code_remote.config.SESSION_DIR", tmp_path / "sessions")
    monkeypatch.setattr(
        "claude_code_remote.config.TEMPLATE_DIR", tmp_path / "templates"
    )
    monkeypatch.setattr("claude_code_remote.config.PUSH_FILE", tmp_path / "push.json")
    app = create_app(skip_auth=True)
    return TestClient(app)


def test_full_workflow(client):
    # Server status
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["active_sessions"] == 0

    # Create template
    resp = client.post(
        "/api/templates",
        json={
            "name": "quick-fix",
            "initial_prompt": "fix the bug",
            "model": "sonnet",
        },
    )
    assert resp.status_code == 201
    template_id = resp.json()["id"]

    # List templates
    resp = client.get("/api/templates")
    assert len(resp.json()) == 1

    # Create session
    resp = client.post(
        "/api/sessions",
        json={
            "name": "debug-auth",
            "project_dir": "/tmp",
            "initial_prompt": "fix login bug",
            "template_id": template_id,
        },
    )
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
    resp = client.post(
        "/api/push/register",
        json={
            "expo_push_token": "ExponentPushToken[test]",
        },
    )
    assert resp.status_code == 200

    # Update push settings
    resp = client.put(
        "/api/push/settings",
        json={
            "notify_approvals": True,
            "notify_completions": False,
            "notify_errors": True,
        },
    )
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
        resp = client.post(
            "/api/sessions",
            json={
                "name": f"s{i}",
                "project_dir": "/tmp",
                "initial_prompt": "x",
            },
        )
        assert resp.status_code == 201
