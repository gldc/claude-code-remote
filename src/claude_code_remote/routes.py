"""REST API routes."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
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
    SendPromptRequest,
    ResumeSessionRequest,
    InternalApprovalRequest,
    StatuslineRequest,
    MCPServer,
    CollaboratorRequest,
    WorkflowStep,
)
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.projects import scan_directory
from claude_code_remote.push import PushManager
from claude_code_remote.git import git_status, git_diff, git_branches, git_log
from claude_code_remote.mcp import (
    list_mcp_servers,
    add_mcp_server,
    remove_mcp_server,
    check_mcp_health,
)

logger = logging.getLogger(__name__)

# Skills cache
_skills_cache: dict = {"data": None, "time": 0}
SKILLS_CACHE_TTL = 300  # 5 minutes


def _parse_skills_output(output: str) -> list[dict]:
    """Parse skills output from Claude CLI."""
    skills = []
    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Simple parsing: each line is a skill name, possibly with description
        parts = line.split("\t", 1)
        name = parts[0].strip()
        desc = parts[1].strip() if len(parts) > 1 else ""
        if name:
            skills.append({"name": name, "description": desc})
    return skills


def create_router(
    session_mgr: SessionManager,
    template_store: TemplateStore,
    push_mgr: PushManager,
    scan_dirs: list[str],
    usage_client=None,
    approval_store=None,
    workflow_engine=None,
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

    # --- Search & Export (must be before /{session_id} catch-all) ---

    @router.get("/sessions/search")
    async def search_sessions(q: str = ""):
        if not q or len(q) < 2:
            raise HTTPException(400, "Query must be at least 2 characters")
        return session_mgr.search_sessions(q)

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    @router.get("/sessions/{session_id}/export")
    async def export_session(session_id: str):
        data = session_mgr.export_session(session_id)
        if not data:
            raise HTTPException(404)
        return data

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
    async def send_prompt(session_id: str, body: SendPromptRequest):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        await session_mgr.send_prompt(session_id, body.prompt)
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
    async def resume_session(session_id: str, body: ResumeSessionRequest):
        await session_mgr.send_prompt(session_id, body.prompt)
        return {"ok": True}

    # --- Session Git ---

    @router.get("/sessions/{session_id}/git/status")
    async def get_git_status(session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        return await git_status(session.project_dir)

    @router.get("/sessions/{session_id}/git/diff")
    async def get_git_diff(session_id: str, file: str | None = None):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        return {"diff": await git_diff(session.project_dir, file)}

    @router.get("/sessions/{session_id}/git/branches")
    async def get_git_branches(session_id: str):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        return await git_branches(session.project_dir)

    @router.get("/sessions/{session_id}/git/log")
    async def get_git_log(session_id: str, n: int = 10):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        return await git_log(session.project_dir, n)

    # --- Session Collaboration ---

    @router.post("/sessions/{session_id}/collaborators")
    async def add_collaborator(session_id: str, body: CollaboratorRequest):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404)
        if body.identity not in session.collaborators:
            session.collaborators.append(body.identity)
            session_mgr.persist_session(session_id)
        return {"collaborators": session.collaborators}

    @router.delete("/sessions/{session_id}/collaborators/{identity}")
    async def remove_collaborator(session_id: str, identity: str):
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404)
        session.collaborators = [c for c in session.collaborators if c != identity]
        session_mgr.persist_session(session_id)
        return {"collaborators": session.collaborators}

    # --- Internal (called by hook scripts / statusline) ---

    @router.post("/internal/approval-request")
    async def internal_approval_request(body: InternalApprovalRequest):
        result = await session_mgr.request_approval(
            body.session_id, body.tool_name, body.tool_input
        )
        return result

    @router.post("/internal/statusline")
    async def internal_statusline(body: StatuslineRequest):
        session_mgr.update_statusline(
            body.session_id,
            model=body.model,
            context_percent=body.context_percent,
            git_branch=body.git_branch,
        )
        return {"ok": True}

    # --- Templates ---

    @router.get("/templates")
    async def list_templates(tag: str | None = None):
        templates = template_store.list()
        if tag:
            templates = [t for t in templates if tag in t.tags]
        return templates

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

    # --- Usage ---

    @router.get("/usage")
    async def get_usage():
        if not usage_client:
            raise HTTPException(503, "Usage client not configured")
        return await usage_client.get_usage()

    @router.get("/usage/history")
    async def get_usage_history(days: int = 7):
        if not usage_client:
            raise HTTPException(503, "Usage client not configured")
        return await usage_client.get_history(days)

    # --- Approval Rules ---

    @router.get("/approval-rules")
    async def list_approval_rules():
        if not approval_store:
            raise HTTPException(503, "Approval rules not configured")
        return approval_store.list()

    @router.post("/approval-rules", status_code=201)
    async def create_approval_rule(
        tool_pattern: str,
        action: str = "approve",
        project_dir: str | None = None,
    ):
        if not approval_store:
            raise HTTPException(503, "Approval rules not configured")
        return approval_store.create(tool_pattern, action, project_dir)

    @router.delete("/approval-rules/{rule_id}", status_code=204)
    async def delete_approval_rule(rule_id: str):
        if not approval_store:
            raise HTTPException(503, "Approval rules not configured")
        if not approval_store.delete(rule_id):
            raise HTTPException(404)
        return Response(status_code=204)

    @router.get("/approval-rules/check")
    async def check_approval_rule(tool: str, project_dir: str | None = None):
        if not approval_store:
            return {"match": None}
        rule = approval_store.check(tool, project_dir)
        if rule:
            return {"match": rule.model_dump(mode="json")}
        return {"match": None}

    # --- MCP ---

    @router.get("/mcp/servers")
    async def list_mcp():
        return list_mcp_servers()

    @router.post("/mcp/servers", status_code=201)
    async def add_mcp(server: MCPServer):
        return add_mcp_server(server)

    @router.delete("/mcp/servers/{name}", status_code=204)
    async def remove_mcp(name: str, scope: str = "global"):
        if not remove_mcp_server(name, scope):
            raise HTTPException(404)
        return Response(status_code=204)

    @router.get("/mcp/servers/{name}/health")
    async def mcp_health(name: str):
        servers = list_mcp_servers()
        server = next((s for s in servers if s.name == name), None)
        if not server:
            raise HTTPException(404)
        return await check_mcp_health(server)

    # --- Skills ---

    @router.get("/skills")
    async def list_skills():
        now = time.time()
        if _skills_cache["data"] and (now - _skills_cache["time"]) < SKILLS_CACHE_TTL:
            return _skills_cache["data"]

        claude_bin = shutil.which("claude")
        if not claude_bin:
            return []

        try:
            proc = await asyncio.create_subprocess_exec(
                claude_bin,
                "--print-skills",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            skills = _parse_skills_output(stdout.decode())
            _skills_cache["data"] = skills
            _skills_cache["time"] = now
            return skills
        except Exception as e:
            logger.error("Failed to discover skills: %s", e)
            # Fall back to known skills
            return [
                {"name": "commit", "description": "Create a git commit"},
                {"name": "review-pr", "description": "Review a pull request"},
                {"name": "compact", "description": "Compact conversation context"},
            ]

    # --- Workflows ---

    @router.get("/workflows")
    async def list_workflows():
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        return workflow_engine.list()

    @router.post("/workflows", status_code=201)
    async def create_workflow(name: str, steps: list[WorkflowStep]):
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        return workflow_engine.create(name, steps)

    @router.get("/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str):
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        wf = workflow_engine.get(workflow_id)
        if not wf:
            raise HTTPException(404)
        return wf

    @router.delete("/workflows/{workflow_id}", status_code=204)
    async def delete_workflow(workflow_id: str):
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        if not workflow_engine.delete(workflow_id):
            raise HTTPException(404)
        return Response(status_code=204)

    @router.post("/workflows/{workflow_id}/run")
    async def run_workflow(workflow_id: str):
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        try:
            wf = await workflow_engine.run(workflow_id, session_mgr)
            return wf
        except ValueError as e:
            raise HTTPException(404, str(e))

    return router
