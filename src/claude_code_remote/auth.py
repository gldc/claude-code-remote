"""Tailscale WhoIs authentication middleware."""

import asyncio
import json
import logging
import subprocess
import shutil

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def _find_tailscale() -> str:
    return shutil.which("tailscale") or "/usr/local/bin/tailscale"


def _whois_tailscale_client_sync(client_ip: str) -> dict | None:
    """Synchronous helper — returns parsed WhoIs JSON or None on failure."""
    try:
        result = subprocess.run(
            [_find_tailscale(), "whois", "--json", client_ip],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def extract_identity(whois_data: dict) -> str | None:
    """Extract a stable user identity string from WhoIs JSON.

    Returns the login name (e.g. ``user@example.com``) if present, else None.
    """
    user_profile = whois_data.get("UserProfile", {})
    login_name = user_profile.get("LoginName")
    if login_name:
        return login_name
    # Fallback: Node.Name (machine name in the tailnet)
    node = whois_data.get("Node", {})
    node_name = node.get("Name")
    return node_name or None


async def verify_tailscale_client(client_ip: str) -> bool:
    """Verify a client IP belongs to this tailnet via `tailscale whois`."""
    data = await asyncio.to_thread(_whois_tailscale_client_sync, client_ip)
    return data is not None


async def identify_tailscale_client(client_ip: str) -> str | None:
    """Return the Tailscale identity for *client_ip*, or None."""
    data = await asyncio.to_thread(_whois_tailscale_client_sync, client_ip)
    if data is None:
        return None
    return extract_identity(data)


class TailscaleAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else None
        if not client_ip:
            return JSONResponse(
                status_code=403,
                content={"detail": "Not authorized. Connect via Tailscale."},
            )
        identity = await identify_tailscale_client(client_ip)
        if identity is None:
            return JSONResponse(
                status_code=403,
                content={"detail": "Not authorized. Connect via Tailscale."},
            )
        # Stash identity on request state so routes can access it
        request.state.tailscale_identity = identity
        response = await call_next(request)
        return response
