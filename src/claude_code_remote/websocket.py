"""WebSocket endpoint for streaming session events."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from claude_code_remote.auth import identify_tailscale_client
from claude_code_remote.session_manager import SessionManager

logger = logging.getLogger(__name__)


def create_ws_router(session_mgr: SessionManager) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/sessions/{session_id}")
    async def session_stream(websocket: WebSocket, session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            await websocket.close(code=4004, reason="Session not found")
            return

        # Ownership check: perform Tailscale identity lookup directly
        # (BaseHTTPMiddleware does NOT set state on WebSocket connections)
        if session.owner:
            client_ip = websocket.client.host if websocket.client else None
            identity = await identify_tailscale_client(client_ip) if client_ip else None
            if not identity or (
                identity != session.owner
                and identity not in getattr(session, "collaborators", [])
            ):
                await websocket.close(code=4003, reason="Not authorized")
                return

        await websocket.accept()

        # Sync messages from JSONL in case terminal added new ones
        session_mgr.sync_from_jsonl(session_id)

        # Send existing messages as backfill
        for msg in session.messages:
            await websocket.send_json(msg)

        # Subscribe to new events
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def on_event(event: dict):
            await queue.put(event)

        session_mgr.subscribe(session_id, on_event)

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    await websocket.send_json(msg)
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    await websocket.send_json({"type": "ping"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(
                "WebSocket error for session %s: %s", session_id, type(e).__name__
            )
        finally:
            session_mgr.unsubscribe(session_id, on_event)

    return router
