"""Dashboard API routes -- unified view of CCR and native sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from claude_code_remote.cron_manager import CronManager
from claude_code_remote.models import (
    CronJobWithRuns,
    DashboardAnalytics,
    DashboardResumeRequest,
    DashboardSession,
    DashboardSessionSummary,
    SessionCreate,
)
from claude_code_remote.native_sessions import NativeSessionReader
from claude_code_remote.session_manager import SessionManager

logger = logging.getLogger(__name__)


def create_dashboard_router(
    session_mgr: SessionManager,
    native_reader: NativeSessionReader,
    cron_mgr: CronManager | None = None,
    show_cost: bool = False,
) -> APIRouter:
    router = APIRouter()

    def _get_caller_identity(request: Request) -> str | None:
        """Extract the Tailscale identity stashed by auth middleware."""
        return getattr(request.state, "tailscale_identity", None)

    def _can_access_session(session, identity: str | None) -> bool:
        """Check if the caller can access a CCR session."""
        if identity is None:
            return True  # Auth disabled (--no-auth)
        if not session.owner or session.owner == identity:
            return True
        if hasattr(session, "collaborators") and identity in session.collaborators:
            return True
        return False

    def _ccr_summary_to_dashboard(summary) -> DashboardSessionSummary:
        """Convert a CCR SessionSummary to DashboardSessionSummary.

        Works with SessionSummary from list_sessions() (no messages/owner fields).
        """
        return DashboardSessionSummary(
            id=summary.id,
            name=summary.name,
            project_dir=summary.project_dir,
            source="ccr",
            status=summary.status.value
            if hasattr(summary.status, "value")
            else summary.status,
            current_model=summary.current_model,
            total_cost_usd=summary.total_cost_usd,
            cost_is_estimated=False,
            message_count=summary.message_count,
            context_percent=summary.context_percent,
            git_branch=summary.git_branch,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            cron_job_id=summary.cron_job_id,
        )

    def _ccr_session_to_dashboard(session) -> DashboardSessionSummary:
        """Convert a full CCR Session to DashboardSessionSummary."""
        return DashboardSessionSummary(
            id=session.id,
            name=session.name,
            project_dir=session.project_dir,
            source="ccr",
            status=session.status.value
            if hasattr(session.status, "value")
            else session.status,
            current_model=session.current_model,
            total_cost_usd=session.total_cost_usd,
            cost_is_estimated=False,
            message_count=len(session.messages),
            context_percent=session.context_percent,
            git_branch=session.git_branch,
            created_at=session.created_at,
            updated_at=session.updated_at,
            owner=session.owner,
            claude_session_id=session.claude_session_id,
            cron_job_id=session.cron_job_id,
        )

    @router.get("/sessions")
    async def list_sessions(
        request: Request,
        source: str | None = None,
        status: str | None = None,
        project: str | None = None,
        q: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ):
        """List sessions from both CCR and native sources."""
        identity = _get_caller_identity(request)
        all_sessions: list[DashboardSessionSummary] = []

        # CCR sessions (filtered by caller identity)
        if source is None or source == "ccr":
            if q:
                # search_sessions returns list[dict] with session_id keys
                seen_ids: set[str] = set()
                for result in session_mgr.search_sessions(q):
                    sid = result["session_id"]
                    if sid not in seen_ids:
                        seen_ids.add(sid)
                        s = session_mgr.get_session(sid)
                        if s and _can_access_session(s, identity):
                            all_sessions.append(_ccr_session_to_dashboard(s))
            else:
                # list_sessions returns list[SessionSummary] (no messages)
                for s in session_mgr.list_sessions():
                    # Need full session for owner check
                    full = session_mgr.get_session(s.id)
                    if full and _can_access_session(full, identity):
                        all_sessions.append(_ccr_summary_to_dashboard(s))

        # Native sessions (visible to all authenticated users)
        if source is None or source == "native":
            native = native_reader.list_sessions()
            if q:
                q_lower = q.lower()
                native = [
                    s
                    for s in native
                    if q_lower in s.name.lower() or q_lower in s.project_dir.lower()
                ]
            all_sessions.extend(native)

        # Apply filters
        if status:
            all_sessions = [s for s in all_sessions if s.status == status]
        if project:
            project_lower = project.lower()
            all_sessions = [
                s for s in all_sessions if project_lower in s.project_dir.lower()
            ]

        # Sort by updated_at descending
        all_sessions.sort(key=lambda s: s.updated_at, reverse=True)

        # Paginate
        total = len(all_sessions)
        start = (page - 1) * page_size
        page_sessions = all_sessions[start : start + page_size]

        return {
            "sessions": [s.model_dump() for s in page_sessions],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @router.get("/sessions/{session_id}")
    async def get_session(
        request: Request,
        session_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=500),
    ):
        """Get session detail with paginated messages."""
        identity = _get_caller_identity(request)

        # Try CCR first
        ccr_session = session_mgr.get_session(session_id)
        if ccr_session:
            if not _can_access_session(ccr_session, identity):
                raise HTTPException(
                    status_code=403,
                    detail="You do not have access to this session.",
                )
            messages = ccr_session.messages
            total = len(messages)
            return DashboardSession(
                **_ccr_session_to_dashboard(ccr_session).model_dump(),
                messages=messages[offset : offset + limit],
                total_messages=total,
            ).model_dump()

        # Try native (visible to all authenticated users)
        native_summary = native_reader.get_session(session_id)
        if native_summary:
            messages, total = native_reader.get_session_messages(
                session_id, offset=offset, limit=limit
            )
            return DashboardSession(
                **native_summary.model_dump(),
                messages=messages,
                total_messages=total,
            ).model_dump()

        raise HTTPException(status_code=404, detail="Session not found")

    @router.get("/analytics")
    async def get_analytics(request: Request):
        """Summary stats for the dashboard header."""
        identity = _get_caller_identity(request)
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        # CCR sessions (filtered by identity)
        ccr_sessions = session_mgr.list_sessions()
        active_ccr = 0
        cost_7d = 0.0
        model_counts: dict[str, int] = {}

        for s in ccr_sessions:
            full = session_mgr.get_session(s.id)
            if full and not _can_access_session(full, identity):
                continue
            if s.status.value in ("running", "idle", "awaiting_approval"):
                active_ccr += 1
            if s.updated_at >= seven_days_ago:
                cost_7d += s.total_cost_usd
            if s.current_model:
                model_counts[s.current_model] = model_counts.get(s.current_model, 0) + 1

        # Native sessions
        native_sessions = native_reader.list_sessions()
        active_native = sum(1 for s in native_sessions if s.status == "active")

        for s in native_sessions:
            if s.updated_at >= seven_days_ago:
                cost_7d += s.total_cost_usd
            if s.current_model:
                model_counts[s.current_model] = model_counts.get(s.current_model, 0) + 1

        top_model = max(model_counts, key=model_counts.get) if model_counts else None

        # Cron jobs
        active_cron = 0
        if cron_mgr:
            active_cron = sum(1 for j in cron_mgr.list() if j.enabled)

        return DashboardAnalytics(
            active_sessions=active_ccr + active_native,
            total_cost_7d=round(cost_7d, 2),
            top_model=top_model,
            active_cron_jobs=active_cron,
            show_cost=show_cost,
        ).model_dump()

    @router.post("/sessions/{session_id}/resume")
    async def resume_native_session(
        session_id: str, req: DashboardResumeRequest, request: Request
    ):
        """Resume a native session by creating a CCR session with --resume."""
        native_summary = native_reader.get_session(session_id)
        if not native_summary:
            raise HTTPException(status_code=404, detail="Native session not found")

        identity = _get_caller_identity(request)

        # Create a CCR session pointing to the native session
        ccr_session = session_mgr.create_session(
            SessionCreate(
                name=f"{native_summary.name} (resumed)",
                project_dir=native_summary.project_dir,
                initial_prompt=req.prompt,
            ),
            owner=identity,
        )
        # Set the claude_session_id so --resume picks up the conversation
        ccr_session.claude_session_id = native_summary.claude_session_id
        session_mgr.persist_session(ccr_session.id)

        # Actually send the prompt to start the session
        await session_mgr.send_prompt(ccr_session.id, req.prompt)

        return {"session_id": ccr_session.id, "status": "created"}

    @router.get("/cron-jobs")
    async def list_cron_jobs_enriched():
        """List all cron jobs with recent runs inlined."""
        if not cron_mgr:
            return []
        jobs = cron_mgr.list()
        result = []
        for job in jobs:
            runs = cron_mgr.get_history(job.id, limit=5)
            enriched = CronJobWithRuns(
                **job.model_dump(),
                recent_runs=runs,
            )
            result.append(enriched.model_dump())
        return result

    return router
