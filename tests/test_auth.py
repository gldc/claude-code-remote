# tests/test_auth.py
import pytest
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_code_remote.auth import (
    TailscaleAuthMiddleware,
    extract_identity,
)


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
    with patch(
        "claude_code_remote.auth.identify_tailscale_client",
        new_callable=AsyncMock,
        return_value="user@example.com",
    ):
        resp = client.get("/test")
    assert resp.status_code == 200


def test_rejects_request_when_whois_fails(app_with_auth):
    client = TestClient(app_with_auth)
    with patch(
        "claude_code_remote.auth.identify_tailscale_client",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get("/test")
    assert resp.status_code == 403


# --- extract_identity tests ---


def test_extract_identity_login_name():
    data = {
        "UserProfile": {"LoginName": "alice@example.com"},
        "Node": {"Name": "mybox"},
    }
    assert extract_identity(data) == "alice@example.com"


def test_extract_identity_fallback_node_name():
    data = {"UserProfile": {}, "Node": {"Name": "mybox.tail12345.ts.net"}}
    assert extract_identity(data) == "mybox.tail12345.ts.net"


def test_extract_identity_empty():
    assert extract_identity({}) is None
