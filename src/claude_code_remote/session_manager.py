"""Session manager -- spawns and manages Claude Code subprocesses."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
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

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, session_dir: Path, max_concurrent: int = 5):
        self.session_dir = session_dir
        self.max_concurrent = max_concurrent
        self.sessions: dict[str, Session] = {}
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.ws_subscribers: dict[str, list[Callable]] = {}
        self._approval_events: dict[str, asyncio.Event] = {}
        self._approval_responses: dict[str, bool] = {}
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, req: SessionCreate) -> Session:
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
        )
        self.sessions[session.id] = session
        self.persist_session(session.id)
        return session

    def list_sessions(
        self,
        status: SessionStatus | None = None,
        project_dir: str | None = None,
    ) -> list[SessionSummary]:
        results = []
        for s in self.sessions.values():
            if status and s.status != status:
                continue
            if project_dir and s.project_dir != project_dir:
                continue
            preview = None
            if s.messages:
                last = s.messages[-1]
                preview = str(last.get("data", {}).get("text", ""))[:100]
            results.append(
                SessionSummary(
                    id=s.id,
                    name=s.name,
                    project_dir=s.project_dir,
                    status=s.status,
                    model=s.model,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                    total_cost_usd=s.total_cost_usd,
                    last_message_preview=preview,
                )
            )
        return results

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

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
                self.sessions[session.id] = session
            except Exception as e:
                logger.error(f"Failed to load session {path}: {e}")

    def _stop_process(self, session_id: str) -> None:
        proc = self.processes.pop(session_id, None)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    async def start_session(
        self,
        session_id: str,
        initial_prompt: str,
        on_event: Callable[[WSMessage], Any] | None = None,
    ) -> None:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        claude_bin = shutil.which("claude")
        if not claude_bin:
            raise RuntimeError("Claude Code CLI not found in PATH")

        cmd = [
            claude_bin,
            "-p",
            "--output-format",
            "stream-json",
            "--input-format",
            "stream-json",
            "--verbose",
            "--no-session-persistence",
        ]
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

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            initial_prompt,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session.project_dir,
            env=env,
        )
        self.processes[session_id] = proc
        session.status = SessionStatus.RUNNING
        session.updated_at = datetime.now(timezone.utc)
        self.persist_session(session_id)

        asyncio.create_task(self._read_output(session_id, proc, on_event))

    async def _read_output(
        self,
        session_id: str,
        proc: asyncio.subprocess.Process,
        on_event: Callable[[WSMessage], Any] | None,
    ) -> None:
        session = self.sessions.get(session_id)
        if not session or not proc.stdout:
            return

        async for line in proc.stdout:
            text = line.decode().strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue

            ws_msg = self._parse_event(event)
            if ws_msg:
                session.messages.append(ws_msg.model_dump(mode="json"))
                session.updated_at = datetime.now(timezone.utc)
                if on_event:
                    await on_event(ws_msg) if asyncio.iscoroutinefunction(
                        on_event
                    ) else on_event(ws_msg)
                await self._broadcast(session_id, ws_msg)

            if event.get("type") == "result":
                cost = event.get("total_cost_usd", 0)
                session.total_cost_usd = cost
                subtype = event.get("subtype", "")
                if subtype == "success":
                    session.status = SessionStatus.COMPLETED
                else:
                    session.status = SessionStatus.ERROR
                    session.error_message = event.get("result", "Unknown error")
                session.updated_at = datetime.now(timezone.utc)
                self.persist_session(session_id)

        await proc.wait()
        if session.status == SessionStatus.RUNNING:
            session.status = SessionStatus.ERROR
            session.error_message = f"Process exited with code {proc.returncode}"
            session.updated_at = datetime.now(timezone.utc)
            self.persist_session(session_id)

    def _parse_event(self, event: dict) -> WSMessage | None:
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
            return (
                messages[0] if len(messages) == 1 else messages[0] if messages else None
            )

        elif etype == "result":
            return WSMessage(
                type=WSMessageType.STATUS_CHANGE,
                data={
                    "status": "completed"
                    if event.get("subtype") == "success"
                    else "error",
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

    async def send_prompt(self, session_id: str, prompt: str) -> None:
        proc = self.processes.get(session_id)
        if not proc or not proc.stdin:
            raise ValueError(f"No active process for session {session_id}")
        msg = json.dumps({"type": "user", "content": prompt}) + "\n"
        proc.stdin.write(msg.encode())
        await proc.stdin.drain()

    async def pause_session(self, session_id: str) -> None:
        proc = self.processes.get(session_id)
        session = self.sessions.get(session_id)
        if proc and proc.returncode is None:
            proc.send_signal(signal.SIGINT)
            if session:
                session.status = SessionStatus.PAUSED
                session.updated_at = datetime.now(timezone.utc)
                self.persist_session(session_id)

    async def approve_tool_use(self, session_id: str) -> None:
        event = self._approval_events.get(session_id)
        if event:
            self._approval_responses[session_id] = True
            event.set()

    async def deny_tool_use(self, session_id: str, reason: str | None = None) -> None:
        event = self._approval_events.get(session_id)
        if event:
            self._approval_responses[session_id] = False
            event.set()

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

    async def shutdown(self) -> None:
        for session_id in list(self.processes.keys()):
            self._stop_process(session_id)
