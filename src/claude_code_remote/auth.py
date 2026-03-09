"""Tailscale WhoIs authentication middleware."""

import asyncio
import subprocess
import shutil

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _find_tailscale() -> str:
    return shutil.which("tailscale") or "/usr/local/bin/tailscale"


def _verify_tailscale_client_sync(client_ip: str) -> bool:
    """Synchronous helper for tailscale whois verification."""
    try:
        result = subprocess.run(
            [_find_tailscale(), "whois", "--json", client_ip],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


async def verify_tailscale_client(client_ip: str) -> bool:
    """Verify a client IP belongs to this tailnet via `tailscale whois`."""
    return await asyncio.to_thread(_verify_tailscale_client_sync, client_ip)


class TailscaleAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else None
        if not client_ip or not await verify_tailscale_client(client_ip):
            return JSONResponse(
                status_code=403,
                content={"detail": "Not authorized. Connect via Tailscale."},
            )
        response = await call_next(request)
        return response
