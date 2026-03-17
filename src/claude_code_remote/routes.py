"""REST API routes."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from starlette.responses import Response

from claude_code_remote.models import (
    SessionCreate,
    SessionUpdate,
    SessionSummary,
    TemplateCreate,
    Project,
    ProjectRegister,
    ProjectCreate,
    ProjectClone,
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
    WorkflowCreate,
    WorkflowStepCreate,
    CronJobCreate,
    CronJobUpdate,
    UploadedFile,
    UploadResponse,
    GitStatus,
)
from claude_code_remote.native_sessions import NativeSessionReader
from claude_code_remote.hidden_sessions import HiddenSessionsStore
from starlette.requests import Request

from claude_code_remote.session_manager import SessionManager
from claude_code_remote.templates import TemplateStore
from claude_code_remote.project_store import ProjectStore
from claude_code_remote.projects import scan_directory, detect_project_type
from claude_code_remote.push import PushManager
from claude_code_remote.git_check import check_git_setup
from claude_code_remote.uploads import save_upload, ensure_gitignore
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


def _parse_skill_frontmatter(path: Path) -> tuple[str, str]:
    """Extract name and description from SKILL.md YAML frontmatter."""
    name = ""
    desc = ""
    try:
        text = path.read_text()
        if not text.startswith("---"):
            return name, desc
        end = text.index("---", 3)
        frontmatter = text[3:end]
        for line in frontmatter.strip().split("\n"):
            if line.startswith("name:"):
                name = line[5:].strip().strip('"').strip("'")
            elif line.startswith("description:"):
                desc = line[12:].strip().strip('"').strip("'")
    except Exception:
        pass
    return name, desc


def _discover_skills() -> list[dict]:
    """Discover skills from enabled Claude Code plugins."""
    from .mcp import SETTINGS_PATH, INSTALLED_PLUGINS_PATH

    skills = []
    try:
        settings = (
            json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.exists() else {}
        )
        enabled = settings.get("enabledPlugins", {})
        installed = (
            json.loads(INSTALLED_PLUGINS_PATH.read_text())
            if INSTALLED_PLUGINS_PATH.exists()
            else {}
        )
        plugins = installed.get("plugins", {})

        for plugin_id in enabled:
            entries = plugins.get(plugin_id, [])
            if not entries:
                continue
            install_path = entries[0].get("installPath")
            if not install_path:
                continue
            # plugin_id is like "superpowers@claude-plugins-official" — take the name part
            plugin_name = plugin_id.split("@")[0]
            skills_dir = Path(install_path) / "skills"
            if not skills_dir.is_dir():
                continue
            for skill_dir in sorted(skills_dir.iterdir()):
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                name, desc = _parse_skill_frontmatter(skill_md)
                skills.append(
                    {
                        "name": f"{plugin_name}:{name or skill_dir.name}",
                        "description": desc,
                    }
                )
    except Exception as e:
        logger.debug("Failed to discover skills: %s", e)
    return skills


def create_router(
    session_mgr: SessionManager,
    template_store: TemplateStore,
    push_mgr: PushManager,
    scan_dirs: list[str],
    usage_client=None,
    approval_store=None,
    workflow_engine=None,
    project_store: ProjectStore | None = None,
    cron_mgr=None,
    show_cost: bool = False,
    native_reader: NativeSessionReader | None = None,
    hidden_store: HiddenSessionsStore | None = None,
    native_max_age_days: int = 7,
) -> APIRouter:
    router = APIRouter()

    def _get_caller_identity(request: Request) -> str | None:
        """Extract the Tailscale identity stashed by auth middleware."""
        return getattr(request.state, "tailscale_identity", None)

    def _check_session_access(session_id: str, request: Request) -> None:
        """Raise 403 if the caller is not the session owner or a collaborator.

        Called for both read and mutating operations on session resources.
        When auth is disabled (no identity on request), access is allowed.
        """
        identity = _get_caller_identity(request)
        if identity is None:
            # Auth disabled (--no-auth) — allow everything
            return
        session = session_mgr.get_session(session_id)
        if session is None:
            return  # Will 404 later
        # Owner check
        if session.owner and session.owner != identity:
            # Collaborator check
            if identity not in session.collaborators:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this session.",
                )

    def _check_session_owner(session_id: str, request: Request) -> None:
        """Raise 403 if the caller is not the session owner.

        Stricter than _check_session_access — collaborators are NOT allowed.
        Used for privileged operations like managing collaborators.
        When auth is disabled (no identity on request), access is allowed.
        """
        identity = _get_caller_identity(request)
        if identity is None:
            return
        session = session_mgr.get_session(session_id)
        if session is None:
            return  # Will 404 later
        if session.owner and session.owner != identity:
            raise HTTPException(
                status_code=403,
                detail="Only the session owner can perform this action.",
            )

    # --- Sessions ---

    @router.get("/sessions")
    async def list_sessions(
        request: Request,
        status: SessionStatus | None = None,
        project_dir: str | None = None,
        archived: bool | None = None,
    ):
        sessions = session_mgr.list_sessions(
            status=status, project_dir=project_dir, archived=archived
        )
        identity = _get_caller_identity(request)
        if identity is not None:
            # Filter to only sessions the caller owns or collaborates on
            sessions = [
                s
                for s in sessions
                if not (full := session_mgr.get_session(s.id))
                or not full.owner
                or full.owner == identity
                or identity in full.collaborators
            ]

        # Merge native sessions
        if native_reader and not status:
            # Collect claude_session_ids from CCR sessions to deduplicate
            ccr_claude_ids: set[str] = set()
            for s in sessions:
                full = session_mgr.get_session(s.id)
                if full and full.claude_session_id:
                    ccr_claude_ids.add(full.claude_session_id)

            hidden_ids = set(hidden_store.list_hidden()) if hidden_store else set()
            is_archived = archived is True
            native_sessions = native_reader.list_sessions(
                max_age_days=None if is_archived else native_max_age_days,
                hidden_ids=hidden_ids,
                archived=is_archived,
            )

            # Load active PIDs once for the entire list (avoids N+1 reads)
            active_pids = native_reader.load_active_pids()

            for ns in native_sessions:
                if ns.id in ccr_claude_ids:
                    continue
                if project_dir and project_dir.lower() not in ns.project_dir.lower():
                    continue
                active_pid = active_pids.get(ns.id)
                sessions.append(
                    SessionSummary(
                        id=ns.id,
                        name=ns.name,
                        project_dir=ns.project_dir,
                        status=SessionStatus.RUNNING
                        if active_pid
                        else SessionStatus.IDLE,
                        model=None,
                        created_at=ns.created_at,
                        updated_at=ns.updated_at,
                        total_cost_usd=ns.total_cost_usd,
                        current_model=ns.current_model,
                        git_branch=ns.git_branch,
                        message_count=ns.message_count,
                        source="native",
                        native_pid=active_pid,
                    )
                )

        # Sort by updated_at descending
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    @router.post("/sessions", status_code=201)
    async def create_session(req: SessionCreate, request: Request):
        try:
            identity = _get_caller_identity(request)
            session = session_mgr.create_session(req, owner=identity)
            if req.initial_prompt:
                await session_mgr.send_prompt(session.id, req.initial_prompt)
            return session
        except RuntimeError as e:
            raise HTTPException(status_code=429, detail=str(e))

    # --- Search & Export (must be before /{session_id} catch-all) ---

    @router.get("/sessions/search")
    async def search_sessions(q: str = "", request: Request = None):
        if not q or len(q) < 2:
            raise HTTPException(400, "Query must be at least 2 characters")
        results = session_mgr.search_sessions(q)
        identity = _get_caller_identity(request)
        if identity is not None:
            results = [
                s
                for s in results
                if not s.owner
                or s.owner == identity
                or identity in getattr(s, "collaborators", [])
            ]
        return results

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str, request: Request):
        _check_session_access(session_id, request)
        session = session_mgr.get_session(session_id)
        if session:
            # Sync messages from JSONL in case terminal added new ones
            session_mgr.sync_from_jsonl(session_id)
            return session

        # Fall through to native session
        if native_reader:
            native = native_reader.get_session(session_id)
            if native:
                messages, total = native_reader.get_session_messages(session_id)
                active_pid = native_reader.get_active_pid(session_id)
                return {
                    **native.model_dump(),
                    "messages": messages,
                    "total_messages": total,
                    "native_pid": active_pid,
                }

        raise HTTPException(status_code=404, detail="Session not found")

    @router.get("/sessions/{session_id}/export")
    async def export_session(session_id: str, request: Request):
        _check_session_access(session_id, request)
        data = session_mgr.export_session(session_id)
        if not data:
            raise HTTPException(404)
        return data

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str, request: Request):
        _check_session_access(session_id, request)
        session_mgr.delete_session(session_id)
        return Response(status_code=204)

    @router.patch("/sessions/{session_id}")
    async def update_session(session_id: str, body: SessionUpdate, request: Request):
        _check_session_access(session_id, request)
        if not session_mgr.get_session(session_id):
            raise HTTPException(404, "Session not found")
        if body.name:
            session_mgr.rename_session(session_id, body.name)
        return session_mgr.get_summary(session_id)

    @router.post("/sessions/{session_id}/archive")
    async def archive_session(session_id: str, request: Request):
        _check_session_access(session_id, request)
        session_mgr.archive_session(session_id, archived=True)
        return {"ok": True}

    @router.post("/sessions/{session_id}/unarchive")
    async def unarchive_session(session_id: str, request: Request):
        _check_session_access(session_id, request)
        session_mgr.archive_session(session_id, archived=False)
        return {"ok": True}

    @router.post("/sessions/{session_id}/hide")
    async def hide_session(session_id: str, permanent: bool = False):
        if not hidden_store:
            raise HTTPException(503, "Hidden sessions store not configured")
        hidden_store.hide(session_id, permanent=permanent)
        return {"ok": True}

    @router.post("/sessions/{session_id}/unhide")
    async def unhide_session(session_id: str):
        if not hidden_store:
            raise HTTPException(503, "Hidden sessions store not configured")
        hidden_store.unhide(session_id)
        return {"ok": True}

    @router.post("/sessions/{session_id}/send")
    async def send_prompt(session_id: str, body: SendPromptRequest, request: Request):
        session = session_mgr.get_session(session_id)

        if not session and native_reader:
            native = native_reader.get_session(session_id)
            if not native:
                raise HTTPException(status_code=404, detail="Session not found")

            active_pid = native_reader.get_active_pid(session_id)
            if active_pid:
                raise HTTPException(
                    status_code=409,
                    detail=f"Session is active in terminal (PID {active_pid}). Close it first.",
                )

            identity = _get_caller_identity(request)
            try:
                adopted = session_mgr.create_session(
                    SessionCreate(
                        name=native.name,
                        project_dir=native.project_dir,
                        initial_prompt="",
                    ),
                    owner=identity,
                )
            except (ValueError, RuntimeError) as e:
                raise HTTPException(status_code=400, detail=str(e))
            adopted.claude_session_id = native.claude_session_id
            session_mgr.persist_session(adopted.id)
            await session_mgr.send_prompt(adopted.id, body.prompt)
            return {"ok": True, "adopted": True, "new_session_id": adopted.id}

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        _check_session_access(session_id, request)
        await session_mgr.send_prompt(session_id, body.prompt)
        return {"ok": True}

    @router.post("/sessions/{session_id}/upload")
    async def upload_files(
        session_id: str,
        request: Request,
        files: list[UploadFile] = File(...),
    ):
        """Upload files to the session's project directory."""
        _check_session_access(session_id, request)
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.status.value == "completed":
            raise HTTPException(
                status_code=400, detail="Cannot upload to a completed session"
            )
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        ensure_gitignore(session.project_dir)

        # Note: reads entire file into memory. For v1 this is acceptable since
        # the user controls what they upload. If OOM becomes an issue with very
        # large files, refactor to stream chunks via aiofiles.
        uploaded = []
        for f in files:
            content = await f.read()
            try:
                result = save_upload(
                    session.project_dir, f.filename or "unnamed", content
                )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            uploaded.append(UploadedFile(**result))

        return UploadResponse(files=uploaded)

    @router.post("/sessions/{session_id}/approve")
    async def approve_tool(session_id: str, request: Request):
        _check_session_access(session_id, request)
        await session_mgr.approve_tool_use(session_id)
        return {"ok": True}

    @router.post("/sessions/{session_id}/deny")
    async def deny_tool(
        session_id: str, request: Request, body: ApprovalResponse | None = None
    ):
        _check_session_access(session_id, request)
        reason = body.reason if body else None
        await session_mgr.deny_tool_use(session_id, reason)
        return {"ok": True}

    @router.post("/sessions/{session_id}/pause")
    async def pause_session(session_id: str, request: Request):
        _check_session_access(session_id, request)
        await session_mgr.pause_session(session_id)
        return {"ok": True}

    @router.post("/sessions/{session_id}/resume")
    async def resume_session(
        session_id: str, body: ResumeSessionRequest, request: Request
    ):
        _check_session_access(session_id, request)
        await session_mgr.send_prompt(session_id, body.prompt)
        return {"ok": True}

    # --- Session Git ---

    @router.get("/sessions/{session_id}/git/status")
    async def get_git_status(session_id: str, request: Request):
        _check_session_access(session_id, request)
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        try:
            return await git_status(session.project_dir)
        except (RuntimeError, TimeoutError):
            return GitStatus()

    @router.get("/sessions/{session_id}/git/diff")
    async def get_git_diff(session_id: str, request: Request, file: str | None = None):
        _check_session_access(session_id, request)
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        try:
            return {"diff": await git_diff(session.project_dir, file)}
        except (RuntimeError, TimeoutError):
            return {"diff": ""}

    @router.get("/sessions/{session_id}/git/branches")
    async def get_git_branches(session_id: str, request: Request):
        _check_session_access(session_id, request)
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        try:
            return await git_branches(session.project_dir)
        except (RuntimeError, TimeoutError):
            return []

    @router.get("/sessions/{session_id}/git/log")
    async def get_git_log(session_id: str, request: Request, n: int = 10):
        n = min(n, 100)
        _check_session_access(session_id, request)
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        try:
            return await git_log(session.project_dir, n)
        except (RuntimeError, TimeoutError):
            return []

    # --- Session Collaboration ---

    @router.post("/sessions/{session_id}/collaborators")
    async def add_collaborator(
        session_id: str, body: CollaboratorRequest, request: Request
    ):
        _check_session_owner(session_id, request)
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(404)
        if body.identity not in session.collaborators:
            session.collaborators.append(body.identity)
            session_mgr.persist_session(session_id)
        return {"collaborators": session.collaborators}

    @router.delete("/sessions/{session_id}/collaborators/{identity}")
    async def remove_collaborator(session_id: str, identity: str, request: Request):
        _check_session_owner(session_id, request)
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
        if project_store:
            return project_store.merge_with_scanned(all_projects)
        return all_projects

    @router.post("/projects")
    async def register_project(req: ProjectRegister):
        path = Path(req.path).expanduser()
        if not path.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
        scan_dirs.append(str(path.parent))
        return {"ok": True, "path": str(path)}

    @router.post("/projects/create", status_code=201)
    async def create_blank_project(body: ProjectCreate):
        if not project_store:
            raise HTTPException(503, "Project store not configured")
        if not scan_dirs:
            raise HTTPException(503, "No scan directories configured")
        if not body.name.strip():
            raise HTTPException(400, "Project name cannot be empty")

        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", body.name.strip())
        if not safe_name:
            raise HTTPException(400, "Invalid project name")

        base_dir = Path(scan_dirs[0]).expanduser()
        project_path = base_dir / safe_name
        if project_path.exists():
            raise HTTPException(409, f"Directory already exists: {safe_name}")

        project_path.mkdir(parents=True)

        proc = await asyncio.create_subprocess_exec(
            "git",
            "init",
            str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            shutil.rmtree(project_path, ignore_errors=True)
            logger.error(
                "git init failed for %s: %s", safe_name, stderr.decode().strip()
            )
            raise HTTPException(500, "git init failed")

        project = Project(
            id=Project.id_from_path(str(project_path)),
            name=safe_name,
            path=str(project_path),
            status="ready",
        )
        project_store.add(project)
        return project

    @router.post("/projects/clone", status_code=201)
    async def clone_project(body: ProjectClone):
        if not project_store:
            raise HTTPException(503, "Project store not configured")
        if not scan_dirs:
            raise HTTPException(503, "No scan directories configured")

        url = body.url.strip()
        if not url:
            raise HTTPException(400, "URL cannot be empty")

        # Validate URL scheme to prevent local path cloning
        if not re.match(r"^(https?://|ssh://|git://|git@)", url):
            raise HTTPException(
                400, "URL must use https://, http://, ssh://, git://, or git@ scheme"
            )

        if body.name:
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", body.name.strip())
        else:
            match = re.search(r"/([^/]+?)(?:\.git)?/?$", url)
            if not match:
                raise HTTPException(
                    400, "Cannot extract repo name from URL. Provide a name."
                )
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", match.group(1))

        if not safe_name:
            raise HTTPException(400, "Invalid project name")

        base_dir = Path(scan_dirs[0]).expanduser()
        project_path = base_dir / safe_name
        if project_path.exists():
            raise HTTPException(409, f"Directory already exists: {safe_name}")

        project = Project(
            id=Project.id_from_path(str(project_path)),
            name=safe_name,
            path=str(project_path),
            status="cloning",
        )
        project_store.add(project)

        async def _do_clone():
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "clone",
                    "--",
                    url,
                    str(project_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
                if proc.returncode == 0:
                    project_store.update_status(project.id, "ready")
                else:
                    raw_err = stderr.decode().strip()
                    logger.error("git clone failed for %s: %s", safe_name, raw_err)
                    # Expose only a safe summary, not raw stderr
                    error_msg = "Clone failed"
                    if "not found" in raw_err.lower():
                        error_msg = "Repository not found"
                    elif (
                        "authentication" in raw_err.lower()
                        or "permission" in raw_err.lower()
                    ):
                        error_msg = "Authentication failed"
                    shutil.rmtree(project_path, ignore_errors=True)
                    project_store.update_status(project.id, "error", error_msg)
            except asyncio.TimeoutError:
                shutil.rmtree(project_path, ignore_errors=True)
                project_store.update_status(
                    project.id, "error", "Clone timed out (5 min)"
                )
            except Exception as e:
                logger.error("git clone error for %s: %s", safe_name, e)
                shutil.rmtree(project_path, ignore_errors=True)
                project_store.update_status(project.id, "error", "Clone failed")

        asyncio.create_task(_do_clone())
        return project

    @router.get("/projects/git-check")
    async def git_check():
        return await check_git_setup()

    # --- System ---

    @router.get("/status")
    async def server_status():
        import socket

        sessions = session_mgr.list_sessions()
        active = sum(
            1
            for s in sessions
            if s.status in (SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL)
        )
        hostname = socket.gethostname().split(".")[0]
        return {
            "status": "ok",
            "active_sessions": active,
            "total_sessions": len(sessions),
            "show_cost": show_cost,
            "hostname": hostname,
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
    async def list_mcp(project_dir: str | None = None):
        return list_mcp_servers(project_dir)

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

        skills = _discover_skills()
        _skills_cache["data"] = skills
        _skills_cache["time"] = now
        return skills

    # --- Workflows ---

    @router.get("/workflows")
    async def list_workflows():
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        return workflow_engine.list()

    @router.post("/workflows", status_code=201)
    async def create_workflow(body: WorkflowCreate):
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        return workflow_engine.create(body.name, body.steps)

    @router.get("/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str):
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        wf = workflow_engine.get(workflow_id)
        if not wf:
            raise HTTPException(404)
        return wf

    @router.post("/workflows/{workflow_id}/steps", status_code=201)
    async def add_workflow_step(workflow_id: str, body: WorkflowStepCreate):
        if not workflow_engine:
            raise HTTPException(503, "Workflow engine not configured")
        step = WorkflowStep(
            session_config=body.session_config, depends_on=body.depends_on
        )
        wf = workflow_engine.add_step(workflow_id, step)
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

    # --- Cron Jobs ---

    @router.get("/cron-jobs")
    async def list_cron_jobs():
        if not cron_mgr:
            return []
        return cron_mgr.list()

    @router.post("/cron-jobs", status_code=201)
    async def create_cron_job(req: CronJobCreate):
        try:
            return cron_mgr.create(req)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.get("/cron-jobs/{job_id}")
    async def get_cron_job(job_id: str):
        job = cron_mgr.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Cron job not found")
        return job

    @router.patch("/cron-jobs/{job_id}")
    async def update_cron_job(job_id: str, req: CronJobUpdate):
        try:
            return cron_mgr.update(job_id, req)
        except ValueError as e:
            if "not found" in str(e):
                raise HTTPException(status_code=404, detail=str(e))
            raise HTTPException(status_code=422, detail=str(e))

    @router.delete("/cron-jobs/{job_id}", status_code=204)
    async def delete_cron_job(job_id: str):
        cron_mgr.delete(job_id)
        return Response(status_code=204)

    @router.post("/cron-jobs/{job_id}/toggle")
    async def toggle_cron_job(job_id: str):
        try:
            return cron_mgr.toggle(job_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Cron job not found")

    @router.post("/cron-jobs/{job_id}/trigger")
    async def trigger_cron_job(job_id: str, background_tasks: BackgroundTasks):
        job = cron_mgr.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Cron job not found")
        background_tasks.add_task(cron_mgr.execute_job, job_id)
        return {"status": "triggered"}

    @router.get("/cron-jobs/{job_id}/history")
    async def get_cron_job_history(job_id: str, limit: int = 50, offset: int = 0):
        return cron_mgr.get_history(job_id, limit=limit, offset=offset)

    return router
