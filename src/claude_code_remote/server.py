"""FastAPI application factory and server entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from claude_code_remote.auth import TailscaleAuthMiddleware
from claude_code_remote.config import (
    ensure_dirs,
    load_config,
    SESSION_DIR,
    TEMPLATE_DIR,
    PUSH_FILE,
    PROJECTS_FILE,
    USAGE_HISTORY_FILE,
    APPROVAL_RULES_FILE,
    WORKFLOW_DIR,
)
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.push import PushManager
from claude_code_remote.usage import UsageClient
from claude_code_remote.approval_rules import ApprovalRulesStore
from claude_code_remote.workflows import WorkflowEngine
from claude_code_remote.project_store import ProjectStore
from claude_code_remote.projects import scan_directory
from claude_code_remote.routes import create_router
from claude_code_remote.websocket import create_ws_router
from claude_code_remote.terminal import TerminalManager, create_terminal_router

logger = logging.getLogger(__name__)


def create_app(
    skip_auth: bool = False, host: str = "127.0.0.1", port: int = 8080
) -> FastAPI:
    """Create and configure the FastAPI application."""
    ensure_dirs()
    config = load_config()

    api_url = f"http://{host}:{port}"
    session_mgr = SessionManager(
        session_dir=SESSION_DIR,
        max_concurrent=config.get("max_concurrent_sessions", 5),
        api_url=api_url,
    )
    session_mgr.load_sessions()

    template_store = TemplateStore(TEMPLATE_DIR)
    push_mgr = PushManager(PUSH_FILE)
    usage_client = UsageClient(USAGE_HISTORY_FILE)
    approval_store = ApprovalRulesStore(APPROVAL_RULES_FILE)
    workflow_engine = WorkflowEngine(WORKFLOW_DIR)
    project_store = ProjectStore(PROJECTS_FILE)
    terminal_mgr = TerminalManager()
    scan_dirs = config.get("scan_directories", ["~/Developer"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Server starting up")
        yield
        logger.info("Server shutting down")
        await terminal_mgr.shutdown()
        await session_mgr.shutdown()

    app = FastAPI(title="Claude Code Remote", lifespan=lifespan)

    # Restrictive CORS policy: no browser origins allowed by default.
    # The mobile app communicates over HTTP directly (no CORS), so this
    # only serves to block browser-based cross-origin attacks.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    if not skip_auth:
        app.add_middleware(TailscaleAuthMiddleware)

    api_router = create_router(
        session_mgr,
        template_store,
        push_mgr,
        scan_dirs,
        usage_client=usage_client,
        approval_store=approval_store,
        workflow_engine=workflow_engine,
        project_store=project_store,
    )
    app.include_router(api_router, prefix="/api")

    ws_router = create_ws_router(session_mgr)
    app.include_router(ws_router)

    def resolve_project(project_id: str):
        """Resolve project_id to Project from store or scanned directories."""
        stored = project_store.get(project_id)
        if stored:
            return stored
        for d in scan_dirs:
            for project in scan_directory(Path(d).expanduser()):
                if project.id == project_id:
                    return project
        return None

    terminal_router = create_terminal_router(terminal_mgr, resolve_project)
    app.include_router(terminal_router)

    # Stash references for CLI access
    app.state.session_mgr = session_mgr
    app.state.push_mgr = push_mgr
    app.state.usage_client = usage_client
    app.state.approval_store = approval_store
    app.state.workflow_engine = workflow_engine

    return app


def run_server(host: str, port: int, skip_auth: bool = False) -> None:
    """Run the server with uvicorn."""
    import uvicorn

    app = create_app(skip_auth=skip_auth, host=host, port=port)
    logging.basicConfig(level=logging.DEBUG)
    uvicorn.run(app, host=host, port=port, log_level="info")
