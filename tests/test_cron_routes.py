"""Tests for cron job API routes."""

import pytest
from fastapi.testclient import TestClient

import claude_code_remote.server as server_mod
import claude_code_remote.config as config_mod
from claude_code_remote.server import create_app


@pytest.fixture(autouse=True)
def _isolate_cron_dir(tmp_path, monkeypatch):
    """Use a temporary cron dir so tests don't pollute each other."""
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir()
    history_file = tmp_path / "cron_history.jsonl"
    monkeypatch.setattr(config_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(config_mod, "CRON_HISTORY_FILE", history_file)
    monkeypatch.setattr(server_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(server_mod, "CRON_HISTORY_FILE", history_file)


@pytest.fixture
def client():
    app = create_app(skip_auth=True, host="127.0.0.1", port=9999)
    return TestClient(app)


@pytest.fixture
def sample_cron_payload():
    return {
        "name": "Daily Review",
        "schedule": "0 9 * * *",
        "execution_mode": "spawn",
        "session_config": {
            "name": "cron-review",
            "project_dir": "/tmp",
            "initial_prompt": "Review code",
        },
    }


def test_list_cron_jobs_empty(client):
    resp = client.get("/api/cron-jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_cron_job(client, sample_cron_payload):
    resp = client.post("/api/cron-jobs", json=sample_cron_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Daily Review"
    assert data["schedule"] == "0 9 * * *"
    assert data["enabled"] is True


def test_get_cron_job(client, sample_cron_payload):
    create_resp = client.post("/api/cron-jobs", json=sample_cron_payload)
    job_id = create_resp.json()["id"]
    resp = client.get(f"/api/cron-jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


def test_get_nonexistent_returns_404(client):
    resp = client.get("/api/cron-jobs/nonexistent")
    assert resp.status_code == 404


def test_update_cron_job(client, sample_cron_payload):
    create_resp = client.post("/api/cron-jobs", json=sample_cron_payload)
    job_id = create_resp.json()["id"]
    resp = client.patch(f"/api/cron-jobs/{job_id}", json={"name": "Updated Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


def test_delete_cron_job(client, sample_cron_payload):
    create_resp = client.post("/api/cron-jobs", json=sample_cron_payload)
    job_id = create_resp.json()["id"]
    resp = client.delete(f"/api/cron-jobs/{job_id}")
    assert resp.status_code == 204
    assert client.get(f"/api/cron-jobs/{job_id}").status_code == 404


def test_toggle_cron_job(client, sample_cron_payload):
    create_resp = client.post("/api/cron-jobs", json=sample_cron_payload)
    job_id = create_resp.json()["id"]
    resp = client.post(f"/api/cron-jobs/{job_id}/toggle")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


def test_invalid_schedule_returns_422(client, sample_cron_payload):
    sample_cron_payload["schedule"] = "not valid"
    resp = client.post("/api/cron-jobs", json=sample_cron_payload)
    assert resp.status_code == 422


def test_trigger_cron_job(client, sample_cron_payload):
    create_resp = client.post("/api/cron-jobs", json=sample_cron_payload)
    job_id = create_resp.json()["id"]
    resp = client.post(f"/api/cron-jobs/{job_id}/trigger")
    assert resp.status_code == 200
    assert resp.json()["status"] == "triggered"


def test_trigger_nonexistent_returns_404(client):
    resp = client.post("/api/cron-jobs/nonexistent/trigger")
    assert resp.status_code == 404


def test_get_history_empty(client, sample_cron_payload):
    create_resp = client.post("/api/cron-jobs", json=sample_cron_payload)
    job_id = create_resp.json()["id"]
    resp = client.get(f"/api/cron-jobs/{job_id}/history")
    assert resp.status_code == 200
    assert resp.json() == []
