"""FastAPI application factory and server entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from claude_code_remote.auth import TailscaleAuthMiddleware
from claude_code_remote.config import (
    ensure_dirs,
    load_config,
    SESSION_DIR,
    TEMPLATE_DIR,
    PUSH_FILE,
)
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.push import PushManager
from claude_code_remote.routes import create_router
from claude_code_remote.websocket import create_ws_router

logger = logging.getLogger(__name__)


def create_app(skip_auth: bool = False) -> FastAPI:
    """Create and configure the FastAPI application."""
    ensure_dirs()
    config = load_config()

    session_mgr = SessionManager(
        session_dir=SESSION_DIR,
        max_concurrent=config.get("max_concurrent_sessions", 5),
    )
    session_mgr.load_sessions()

    template_store = TemplateStore(TEMPLATE_DIR)
    push_mgr = PushManager(PUSH_FILE)
    scan_dirs = config.get("scan_directories", ["~/Developer"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Server starting up")
        yield
        logger.info("Server shutting down")
        await session_mgr.shutdown()

    app = FastAPI(title="Claude Code Remote", lifespan=lifespan)

    if not skip_auth:
        app.add_middleware(TailscaleAuthMiddleware)

    api_router = create_router(session_mgr, template_store, push_mgr, scan_dirs)
    app.include_router(api_router, prefix="/api")

    ws_router = create_ws_router(session_mgr)
    app.include_router(ws_router)

    # Stash references for CLI access
    app.state.session_mgr = session_mgr
    app.state.push_mgr = push_mgr

    return app


def run_server(host: str, port: int, skip_auth: bool = False) -> None:
    """Run the server with uvicorn."""
    import uvicorn

    app = create_app(skip_auth=skip_auth)
    uvicorn.run(app, host=host, port=port, log_level="info")
