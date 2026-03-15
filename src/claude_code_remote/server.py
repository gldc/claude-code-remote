"""FastAPI application factory and server entry point."""

from __future__ import annotations

import logging
import os
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
    CRON_DIR,
    CRON_HISTORY_FILE,
)
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.push import PushManager
from claude_code_remote.usage import UsageClient
from claude_code_remote.approval_rules import ApprovalRulesStore
from claude_code_remote.workflows import WorkflowEngine
from claude_code_remote.project_store import ProjectStore
from claude_code_remote.cron_manager import CronManager
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
    push_mgr = PushManager(PUSH_FILE)
    session_mgr = SessionManager(
        session_dir=SESSION_DIR,
        max_concurrent=config.get("max_concurrent_sessions", 5),
        api_url=api_url,
        push_mgr=push_mgr,
    )
    session_mgr.load_sessions()

    template_store = TemplateStore(TEMPLATE_DIR)
    usage_client = UsageClient(USAGE_HISTORY_FILE)
    approval_store = ApprovalRulesStore(APPROVAL_RULES_FILE)
    workflow_engine = WorkflowEngine(WORKFLOW_DIR)
    project_store = ProjectStore(PROJECTS_FILE)
    cron_mgr = CronManager(
        cron_dir=CRON_DIR,
        history_file=CRON_HISTORY_FILE,
        session_mgr=session_mgr,
    )
    terminal_mgr = TerminalManager()
    scan_dirs = config.get("scan_directories", ["~/Developer"])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Server starting up")
        await cron_mgr.start_scheduler()
        yield
        logger.info("Server shutting down")
        await cron_mgr.shutdown_scheduler()
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
        cron_mgr=cron_mgr,
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

    terminal_router = create_terminal_router(
        terminal_mgr, resolve_project, skip_auth=skip_auth
    )
    app.include_router(terminal_router)

    # Stash references for CLI access
    app.state.session_mgr = session_mgr
    app.state.push_mgr = push_mgr
    app.state.usage_client = usage_client
    app.state.approval_store = approval_store
    app.state.workflow_engine = workflow_engine
    app.state.cron_mgr = cron_mgr

    return app


def run_server(host: str, port: int, skip_auth: bool = False) -> None:
    """Run the server with uvicorn."""
    import uvicorn

    app = create_app(skip_auth=skip_auth, host=host, port=port)
    _VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    _log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    _log_level = (
        getattr(logging, _log_level_name)
        if _log_level_name in _VALID_LOG_LEVELS
        else logging.INFO
    )
    logging.basicConfig(level=_log_level)
    uvicorn.run(app, host=host, port=port, log_level="info")
