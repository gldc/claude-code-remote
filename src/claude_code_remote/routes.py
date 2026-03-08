"""REST API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import Response

from claude_code_remote.models import (
    SessionCreate,
    TemplateCreate,
    ProjectRegister,
    PushRegister,
    PushSettings,
    SessionStatus,
    ApprovalResponse,
)
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.projects import scan_directory
from claude_code_remote.push import PushManager


def create_router(
    session_mgr: SessionManager,
    template_store: TemplateStore,
    push_mgr: PushManager,
    scan_dirs: list[str],
) -> APIRouter:
    router = APIRouter()

    # --- Sessions ---

    @router.get("/sessions")
    async def list_sessions(
        status: SessionStatus | None = None,
        project_dir: str | None = None,
        archived: bool | None = None,
    ):
        return session_mgr.list_sessions(
            status=status, project_dir=project_dir, archived=archived
        )

    @router.post("/sessions", status_code=201)
    async def create_session(req: SessionCreate):
        try:
            session = session_mgr.create_session(req)
            if req.initial_prompt:
                await session_mgr.send_prompt(session.id, req.initial_prompt)
            return session
        except RuntimeError as e:
            raise HTTPException(status_code=429, detail=str(e))

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str):
        session_mgr.delete_session(session_id)
        return Response(status_code=204)

    @router.post("/sessions/{session_id}/archive")
    async def archive_session(session_id: str):
        session_mgr.archive_session(session_id, archived=True)
        return {"ok": True}

    @router.post("/sessions/{session_id}/unarchive")
    async def unarchive_session(session_id: str):
        session_mgr.archive_session(session_id, archived=False)
        return {"ok": True}

    @router.post("/sessions/{session_id}/send")
    async def send_prompt(session_id: str, body: dict):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        prompt = body.get("prompt", "")
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")
        await session_mgr.send_prompt(session_id, prompt)
        return {"ok": True}

    @router.post("/sessions/{session_id}/approve")
    async def approve_tool(session_id: str):
        await session_mgr.approve_tool_use(session_id)
        return {"ok": True}

    @router.post("/sessions/{session_id}/deny")
    async def deny_tool(session_id: str, body: ApprovalResponse | None = None):
        reason = body.reason if body else None
        await session_mgr.deny_tool_use(session_id, reason)
        return {"ok": True}

    @router.post("/sessions/{session_id}/pause")
    async def pause_session(session_id: str):
        await session_mgr.pause_session(session_id)
        return {"ok": True}

    @router.post("/sessions/{session_id}/resume")
    async def resume_session(session_id: str, body: dict):
        prompt = body.get("prompt", "")
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")
        await session_mgr.send_prompt(session_id, prompt)
        return {"ok": True}

    # --- Internal (called by hook scripts / statusline) ---

    @router.post("/internal/approval-request")
    async def internal_approval_request(body: dict):
        session_id = body.get("session_id", "")
        tool_name = body.get("tool_name", "")
        tool_input = body.get("tool_input", {})
        result = await session_mgr.request_approval(session_id, tool_name, tool_input)
        return result

    @router.post("/internal/statusline")
    async def internal_statusline(body: dict):
        session_id = body.get("session_id", "")
        session_mgr.update_statusline(
            session_id,
            model=body.get("model"),
            context_percent=body.get("context_percent", 0),
            git_branch=body.get("git_branch"),
        )
        return {"ok": True}

    # --- Templates ---

    @router.get("/templates")
    async def list_templates():
        return template_store.list()

    @router.post("/templates", status_code=201)
    async def create_template(req: TemplateCreate):
        return template_store.create(req)

    @router.put("/templates/{template_id}")
    async def update_template(template_id: str, req: TemplateCreate):
        try:
            return template_store.update(template_id, req)
        except ValueError:
            raise HTTPException(status_code=404, detail="Template not found")

    @router.delete("/templates/{template_id}", status_code=204)
    async def delete_template(template_id: str):
        template_store.delete(template_id)
        return Response(status_code=204)

    # --- Projects ---

    @router.get("/projects")
    async def list_projects():
        all_projects = []
        for d in scan_dirs:
            expanded = Path(d).expanduser()
            all_projects.extend(scan_directory(expanded))
        return all_projects

    @router.post("/projects")
    async def register_project(req: ProjectRegister):
        path = Path(req.path).expanduser()
        if not path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
        scan_dirs.append(str(path.parent))
        return {"ok": True, "path": str(path)}

    # --- System ---

    @router.get("/status")
    async def server_status():
        sessions = session_mgr.list_sessions()
        active = sum(
            1
            for s in sessions
            if s.status in (SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL)
        )
        return {
            "status": "ok",
            "active_sessions": active,
            "total_sessions": len(sessions),
        }

    # --- Push ---

    @router.post("/push/register")
    async def register_push(req: PushRegister):
        push_mgr.register_token(req.expo_push_token)
        return {"ok": True}

    @router.get("/push/settings")
    async def get_push_settings():
        return push_mgr.get_settings()

    @router.put("/push/settings")
    async def update_push_settings(settings: PushSettings):
        push_mgr.update_settings(settings)
        return {"ok": True}

    return router
