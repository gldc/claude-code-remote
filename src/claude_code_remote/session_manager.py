"""Session manager -- spawns and manages Claude Code subprocesses."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from claude_code_remote.models import (
    Session,
    SessionCreate,
    SessionStatus,
    SessionSummary,
    WSMessage,
    WSMessageType,
)
from claude_code_remote.push import PushManager

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(
        self,
        session_dir: Path,
        max_concurrent: int = 5,
        api_url: str = "",
        push_mgr: PushManager | None = None,
    ):
        self.session_dir = session_dir
        self.max_concurrent = max_concurrent
        self.api_url = api_url
        self.push_mgr = push_mgr
        self.sessions: dict[str, Session] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.ws_subscribers: dict[str, list[Callable]] = {}
        # Queue of futures per session — supports multiple concurrent approvals
        self.pending_approvals: dict[str, list[asyncio.Future]] = {}
        self.session_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.session_dir, 0o700)

    def create_session(self, req: SessionCreate, owner: str | None = None) -> Session:
        running = sum(
            1
            for s in self.sessions.values()
            if s.status in (SessionStatus.RUNNING, SessionStatus.AWAITING_APPROVAL)
        )
        if running >= self.max_concurrent:
            raise RuntimeError(
                f"Maximum concurrent sessions ({self.max_concurrent}) reached."
            )

        session = Session(
            name=req.name,
            project_dir=req.project_dir,
            model=req.model,
            max_budget_usd=req.max_budget_usd,
            template_id=req.template_id,
            skip_permissions=req.skip_permissions,
            use_sandbox=req.use_sandbox,
            allowed_tools=req.allowed_tools,
            owner=owner,
        )
        self.sessions[session.id] = session
        self.persist_session(session.id)
        return session

    @staticmethod
    def _to_summary(s: Session) -> SessionSummary:
        preview = None
        if s.messages:
            last = s.messages[-1]
            preview = str(last.get("data", {}).get("text", ""))[:100]
        return SessionSummary(
            id=s.id,
            name=s.name,
            project_dir=s.project_dir,
            status=s.status,
            model=s.model,
            created_at=s.created_at,
            updated_at=s.updated_at,
            total_cost_usd=s.total_cost_usd,
            current_model=s.current_model,
            context_percent=s.context_percent,
            git_branch=s.git_branch,
            message_count=len(s.messages),
            last_message_preview=preview,
            archived=s.archived,
            cron_job_id=s.cron_job_id,
        )

    def list_sessions(
        self,
        status: SessionStatus | None = None,
        project_dir: str | None = None,
        archived: bool | None = None,
    ) -> list[SessionSummary]:
        results = []
        for s in self.sessions.values():
            if status and s.status != status:
                continue
            if project_dir and s.project_dir != project_dir:
                continue
            if archived is not None and s.archived != archived:
                continue
            results.append(self._to_summary(s))
        return results

    def archive_session(self, session_id: str, archived: bool = True) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        session.archived = archived
        session.updated_at = datetime.now(timezone.utc)
        self.persist_session(session_id)

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def rename_session(self, session_id: str, name: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        session.name = name
        session.updated_at = datetime.now(timezone.utc)
        self.persist_session(session_id)

    def get_summary(self, session_id: str) -> SessionSummary | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        return self._to_summary(s)

    def delete_session(self, session_id: str) -> None:
        self._stop_process(session_id)
        self.sessions.pop(session_id, None)
        self.ws_subscribers.pop(session_id, None)
        path = self.session_dir / f"{session_id}.json"
        path.unlink(missing_ok=True)

    def persist_session(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        path = self.session_dir / f"{session_id}.json"
        path.write_text(session.model_dump_json(indent=2))
        os.chmod(path, 0o600)

    def load_sessions(self) -> None:
        for path in self.session_dir.glob("*.json"):
            try:
                session = Session.model_validate_json(path.read_text())
                if session.status in (
                    SessionStatus.RUNNING,
                    SessionStatus.AWAITING_APPROVAL,
                ):
                    session.status = SessionStatus.ERROR
                    session.error_message = "Server restarted while session was active"
                # Migrate tool_result messages: rename "content" → "output"
                migrated = False
                for msg in session.messages:
                    if msg.get("type") == "tool_result" and "content" in msg.get(
                        "data", {}
                    ):
                        data = msg["data"]
                        data["output"] = data.pop("content")
                        migrated = True
                self.sessions[session.id] = session
                if migrated:
                    self.persist_session(session.id)
            except Exception as e:
                logger.error(f"Failed to load session {path}: {e}")

    def _stop_process(self, session_id: str) -> None:
        proc = self.processes.pop(session_id, None)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    # --- Search & Export ---

    def search_sessions(self, query: str) -> list[dict]:
        """Full-text search across session messages."""
        query_lower = query.lower()
        results = []
        for sid, session in self.sessions.items():
            for msg in session.messages:
                text = ""
                data = msg.get("data", {})
                if msg.get("type") == "assistant_text":
                    text = data.get("text", "")
                elif msg.get("type") == "user_message":
                    text = data.get("text", "")
                elif msg.get("type") == "tool_result":
                    text = str(data.get("output", ""))

                if query_lower in text.lower():
                    # Extract snippet around match
                    idx = text.lower().index(query_lower)
                    start = max(0, idx - 50)
                    end = min(len(text), idx + len(query) + 50)
                    snippet = text[start:end]
                    results.append(
                        {
                            "session_id": sid,
                            "session_name": session.name,
                            "snippet": snippet,
                            "message_type": msg.get("type"),
                            "timestamp": msg.get("timestamp"),
                        }
                    )
                    break  # One match per session is enough for listing
        return results

    def export_session(self, session_id: str) -> dict | None:
        """Export full session data as dict."""
        session = self.sessions.get(session_id)
        if not session:
            return None
        return session.model_dump(mode="json")

    async def send_prompt(self, session_id: str, prompt: str) -> None:
        """Send a prompt by spawning a per-turn claude process.

        Uses `-p` for single-turn execution and `--resume` to carry
        conversation context from previous turns.
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Record the user message so it persists across reconnects
        user_ws_msg = WSMessage(
            type=WSMessageType.USER_MESSAGE,
            data={"text": prompt},
        )
        session.messages.append(user_ws_msg.model_dump(mode="json"))
        await self._broadcast(session_id, user_ws_msg)

        # Stop any existing process for this session
        self._stop_process(session_id)

        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("Claude Code CLI not found in PATH")

        cmd = [
            claude_bin,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
        ]

        if session.skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        elif session.allowed_tools:
            cmd.extend(["--allowedTools", ",".join(session.allowed_tools)])
        else:
            cmd.extend(
                [
                    "--allowedTools",
                    "Read,Write,Edit,MultiEdit,Bash,Glob,Grep,WebFetch,WebSearch,"
                    "Agent,Task,TaskOutput,NotebookEdit",
                ]
            )
        if session.use_sandbox:
            cmd.append("--sandbox")

        # Resume previous conversation if we have a Claude session ID
        if session.claude_session_id:
            cmd.extend(["--resume", session.claude_session_id])

        if session.model:
            cmd.extend(["--model", session.model])
        if session.max_budget_usd:
            cmd.extend(["--max-budget-usd", str(session.max_budget_usd)])

        env = os.environ.copy()
        for key in [
            "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT",
            "CLAUDE_CODE_ENTRY_VERSION",
            "CLAUDE_CODE_ENV_VERSION",
        ]:
            env.pop(key, None)
        if session.skip_permissions:
            env["CLAUDE_APPROVAL_FAIL_MODE"] = "allow"
            env["CCR_SKIP_APPROVAL"] = "1"

        # Set env vars for the CCR approval hook and statusline
        env["CCR_SESSION_ID"] = session_id
        if self.api_url:
            env["CCR_API_URL"] = self.api_url

        logger.info(f"[session {session_id}] CMD: {' '.join(cmd)}")
        logger.info(f"[session {session_id}] CWD: {session.project_dir}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session.project_dir,
            env=env,
            limit=10 * 1024 * 1024,  # 10 MB — Claude can emit large JSON lines
        )
        self.processes[session_id] = proc
        session.status = SessionStatus.RUNNING
        session.updated_at = datetime.now(timezone.utc)

        # Capture git branch
        try:
            branch = subprocess.run(
                ["git", "-C", session.project_dir, "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            if branch:
                session.git_branch = branch
        except Exception:
            pass

        self.persist_session(session_id)

        logger.info(
            f"[session {session_id}] PID={proc.pid} "
            f"(claude_session={session.claude_session_id or 'new'})"
        )

        asyncio.create_task(self._read_output(session_id, proc))
        asyncio.create_task(self._read_stderr(session_id, proc))

    async def _read_output(
        self,
        session_id: str,
        proc: asyncio.subprocess.Process,
    ) -> None:
        session = self.sessions.get(session_id)
        if not session or not proc.stdout:
            logger.error(f"[session {session_id}] No session or stdout")
            return

        logger.info(f"[session {session_id}] Starting output reader")
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode().strip()
                if not text:
                    continue
                logger.info(f"[session {session_id}] STDOUT: {text[:200]}")
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    logger.warning(f"[session {session_id}] Bad JSON: {text[:200]}")
                    continue

                parsed = self._parse_event(event)
                if parsed:
                    ws_msgs = parsed if isinstance(parsed, list) else [parsed]
                    for ws_msg in ws_msgs:
                        session.messages.append(ws_msg.model_dump(mode="json"))
                        await self._broadcast(session_id, ws_msg)
                    session.updated_at = datetime.now(timezone.utc)
                else:
                    logger.debug(
                        f"[session {session_id}] Skipped event type: {event.get('type')}"
                    )

                # Extract model name from assistant events
                if event.get("type") == "assistant":
                    msg = event.get("message", {})
                    model_id = msg.get("model")
                    if model_id:
                        session.current_model = model_id

                # Capture session ID, cost, and context from result event
                if event.get("type") == "result":
                    claude_sid = event.get("session_id")
                    if claude_sid:
                        session.claude_session_id = claude_sid
                        logger.info(
                            f"[session {session_id}] Captured claude session: {claude_sid}"
                        )

                    cost = event.get("total_cost_usd", 0)
                    session.total_cost_usd = cost

                    # Calculate context usage from modelUsage
                    model_usage = event.get("modelUsage", {})
                    for model_id, usage in model_usage.items():
                        ctx_window = usage.get("contextWindow", 0)
                        if ctx_window > 0:
                            total_tokens = (
                                usage.get("inputTokens", 0)
                                + usage.get("outputTokens", 0)
                                + usage.get("cacheReadInputTokens", 0)
                                + usage.get("cacheCreationInputTokens", 0)
                            )
                            session.context_percent = int(
                                (total_tokens / ctx_window) * 100
                            )

                        # Capture cache token counts
                        session.cache_read_tokens = usage.get("cacheReadInputTokens", 0)
                        session.cache_write_tokens = usage.get(
                            "cacheCreationInputTokens", 0
                        )

                    session.updated_at = datetime.now(timezone.utc)
                    self.persist_session(session_id)
        except Exception as e:
            logger.error(
                f"[session {session_id}] Output reader error: {e}", exc_info=True
            )

        await proc.wait()
        logger.info(
            f"[session {session_id}] Process exited with code {proc.returncode}"
        )

        # Process exit = turn complete
        if session.status == SessionStatus.RUNNING:
            if proc.returncode == 0:
                session.status = SessionStatus.IDLE
                # Send push notification for successful completion
                if self.push_mgr:
                    try:
                        await self.push_mgr.notify_completion(
                            session.name, session.total_cost_usd, session.id
                        )
                    except Exception as e:
                        logger.error(
                            f"[session {session_id}] Push notification error: {e}"
                        )
            else:
                session.status = SessionStatus.ERROR
                session.error_message = f"Process exited with code {proc.returncode}"
                # Send push notification for error
                if self.push_mgr:
                    try:
                        await self.push_mgr.notify_error(
                            session.name, session.error_message, session.id
                        )
                    except Exception as e:
                        logger.error(
                            f"[session {session_id}] Push notification error: {e}"
                        )
            session.updated_at = datetime.now(timezone.utc)
            self.persist_session(session_id)
        self.processes.pop(session_id, None)

    async def _read_stderr(
        self,
        session_id: str,
        proc: asyncio.subprocess.Process,
    ) -> None:
        if not proc.stderr:
            logger.info(f"[session {session_id}] No stderr pipe")
            return
        logger.info(f"[session {session_id}] Stderr reader started")
        async for line in proc.stderr:
            text = line.decode().strip()
            if text:
                logger.info(f"[session {session_id}] STDERR: {text}")

    def _parse_event(self, event: dict) -> list[WSMessage] | WSMessage | None:
        etype = event.get("type")

        if etype == "assistant":
            msg = event.get("message", {})
            content = msg.get("content", [])
            messages = []
            for block in content:
                if block.get("type") == "text":
                    messages.append(
                        WSMessage(
                            type=WSMessageType.ASSISTANT_TEXT,
                            data={"text": block["text"]},
                        )
                    )
                elif block.get("type") == "tool_use":
                    messages.append(
                        WSMessage(
                            type=WSMessageType.TOOL_USE,
                            data={
                                "tool_name": block.get("name", ""),
                                "tool_input": block.get("input", {}),
                                "tool_use_id": block.get("id", ""),
                            },
                        )
                    )
            if not messages:
                return None
            return messages if len(messages) > 1 else messages[0]

        elif etype == "tool_result":
            content = event.get("content", "")
            tool_use_id = event.get("tool_use_id", "")
            is_error = event.get("is_error", False)

            # Detect content type
            content_type = "text"
            if isinstance(content, str) and (
                content.startswith("diff --git") or content.startswith("---")
            ):
                content_type = "diff"

            return WSMessage(
                type=WSMessageType.TOOL_RESULT,
                data={
                    "tool_use_id": tool_use_id,
                    "output": content,
                    "content_type": content_type,
                    "is_error": is_error,
                },
            )

        elif etype == "result":
            return WSMessage(
                type=WSMessageType.STATUS_CHANGE,
                data={
                    "status": "idle" if event.get("subtype") == "success" else "error",
                    "cost_usd": event.get("total_cost_usd", 0),
                    "duration_ms": event.get("duration_ms", 0),
                    "result": event.get("result", ""),
                },
            )

        elif etype == "rate_limit_event":
            return WSMessage(
                type=WSMessageType.RATE_LIMIT,
                data=event.get("rate_limit_info", {}),
            )

        return None

    async def request_approval(
        self,
        session_id: str,
        tool_name: str,
        tool_input: dict,
    ) -> dict:
        """Called by the hook script. Blocks until user approves/denies."""
        session = self.sessions.get(session_id)
        if not session:
            return {"approved": True}

        session.status = SessionStatus.AWAITING_APPROVAL
        session.updated_at = datetime.now(timezone.utc)
        self.persist_session(session_id)

        # Broadcast approval request to connected clients
        ws_msg = WSMessage(
            type=WSMessageType.APPROVAL_REQUEST,
            data={
                "tool_name": tool_name,
                "tool_input": tool_input,
                "description": f"{tool_name} wants to run",
            },
        )
        session.messages.append(ws_msg.model_dump(mode="json"))
        await self._broadcast(session_id, ws_msg)

        # Send push notification for approval request
        if self.push_mgr:
            try:
                await self.push_mgr.notify_approval(
                    session.name, tool_name, tool_input, session.id
                )
            except Exception as e:
                logger.error(f"[session {session_id}] Push notification error: {e}")

        # Create a future and wait for the user's decision
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self.pending_approvals.setdefault(session_id, []).append(future)

        try:
            result = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            result = {"approved": False, "reason": "Approval timed out"}
        finally:
            queue = self.pending_approvals.get(session_id, [])
            if future in queue:
                queue.remove(future)
            if not queue:
                self.pending_approvals.pop(session_id, None)

        # Restore running status
        if session.status == SessionStatus.AWAITING_APPROVAL:
            session.status = SessionStatus.RUNNING
            session.updated_at = datetime.now(timezone.utc)
            self.persist_session(session_id)

        return result

    def _resolve_last_approval(self, session_id: str, approved: bool) -> None:
        """Mark the last pending approval_request message as resolved."""
        session = self.sessions.get(session_id)
        if not session:
            return
        for msg in reversed(session.messages):
            if msg.get("type") == "approval_request" and not msg.get("data", {}).get(
                "resolved"
            ):
                msg["data"]["resolved"] = True
                msg["data"]["approved"] = approved
                break
        self.persist_session(session_id)

    def _get_pending_tool_name(self, session_id: str) -> str:
        """Extract tool_name from the last unresolved approval_request message."""
        session = self.sessions.get(session_id)
        if not session:
            return "Unknown"
        for msg in reversed(session.messages):
            if msg.get("type") == "approval_request":
                return msg.get("data", {}).get("tool_name", "Unknown")
        return "Unknown"

    async def approve_tool_use(self, session_id: str) -> None:
        queue = self.pending_approvals.get(session_id, [])
        for future in queue:
            if not future.done():
                future.set_result({"approved": True})
                self._resolve_last_approval(session_id, approved=True)
                if self.push_mgr:
                    session = self.sessions.get(session_id)
                    tool_name = self._get_pending_tool_name(session_id)
                    try:
                        await self.push_mgr.notify_action_confirmed(
                            session.name, tool_name, True, session.id
                        )
                    except Exception as e:
                        logger.error(
                            f"[session {session_id}] Push confirmation error: {e}"
                        )
                return

    async def deny_tool_use(self, session_id: str, reason: str | None = None) -> None:
        queue = self.pending_approvals.get(session_id, [])
        for future in queue:
            if not future.done():
                future.set_result(
                    {"approved": False, "reason": reason or "Denied by user"}
                )
                self._resolve_last_approval(session_id, approved=False)
                if self.push_mgr:
                    session = self.sessions.get(session_id)
                    tool_name = self._get_pending_tool_name(session_id)
                    try:
                        await self.push_mgr.notify_action_confirmed(
                            session.name, tool_name, False, session.id
                        )
                    except Exception as e:
                        logger.error(
                            f"[session {session_id}] Push confirmation error: {e}"
                        )
                return

    async def pause_session(self, session_id: str) -> None:
        proc = self.processes.get(session_id)
        session = self.sessions.get(session_id)
        if proc and proc.returncode is None:
            proc.terminate()
            if session:
                session.status = SessionStatus.PAUSED
                session.updated_at = datetime.now(timezone.utc)
                self.persist_session(session_id)

    def subscribe(self, session_id: str, callback: Callable) -> None:
        self.ws_subscribers.setdefault(session_id, []).append(callback)

    def unsubscribe(self, session_id: str, callback: Callable) -> None:
        subs = self.ws_subscribers.get(session_id, [])
        if callback in subs:
            subs.remove(callback)

    async def _broadcast(self, session_id: str, msg: WSMessage) -> None:
        for cb in self.ws_subscribers.get(session_id, []):
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(msg)
                else:
                    cb(msg)
            except Exception as e:
                logger.error(f"WebSocket broadcast error: {e}")

    def update_statusline(
        self,
        session_id: str,
        model: str | None = None,
        context_percent: int = 0,
        git_branch: str | None = None,
    ) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        if model:
            session.current_model = model
        session.context_percent = context_percent
        if git_branch:
            session.git_branch = git_branch
        session.updated_at = datetime.now(timezone.utc)

    async def shutdown(self) -> None:
        for session_id in list(self.processes.keys()):
            self._stop_process(session_id)
