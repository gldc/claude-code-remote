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
    with patch(
        "claude_code_remote.auth.verify_tailscale_client",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = client.get("/test")
    assert resp.status_code == 200


def test_rejects_request_when_whois_fails(app_with_auth):
    client = TestClient(app_with_auth)
    with patch(
        "claude_code_remote.auth.verify_tailscale_client",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = client.get("/test")
    assert resp.status_code == 403
