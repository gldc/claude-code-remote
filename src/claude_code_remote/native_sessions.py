"""Discover and parse native Claude Code sessions from ~/.claude/projects/."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from claude_code_remote.models import DashboardSessionSummary

logger = logging.getLogger(__name__)

# Directories whose sessions are hidden (temp/throwaway work)
_HIDDEN_PROJECT_DIRS = {"/tmp", "/private/tmp"}

# Model pricing: (input_per_1m, output_per_1m)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
}
DEFAULT_PRICING = MODEL_PRICING["claude-sonnet-4-6"]

# Cache token pricing relative to base input price
CACHE_READ_MULTIPLIER = 0.1  # 90% discount
CACHE_CREATION_MULTIPLIER = 1.25  # 25% surcharge


def _estimate_cost(
    model: str | None,
    input_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
    output_tokens: int,
) -> float:
    """Estimate cost from token counts using model-specific pricing."""
    input_price, output_price = MODEL_PRICING.get(model or "", DEFAULT_PRICING)
    return (
        input_tokens * input_price
        + cache_read_tokens * input_price * CACHE_READ_MULTIPLIER
        + cache_creation_tokens * input_price * CACHE_CREATION_MULTIPLIER
        + output_tokens * output_price
    ) / 1_000_000


class _CachedMetadata:
    """Cached metadata for a single JSONL session file."""

    __slots__ = ("summary", "mtime")

    def __init__(self, summary: DashboardSessionSummary, mtime: float):
        self.summary = summary
        self.mtime = mtime


class NativeSessionReader:
    """Reads native Claude Code sessions from the local filesystem."""

    DISPLAYED_TYPES = {"user", "assistant", "tool_result"}

    def __init__(self, claude_dir: Path | None = None):
        self._claude_dir = claude_dir or Path.home() / ".claude"
        self._projects_dir = self._claude_dir / "projects"
        self._sessions_dir = self._claude_dir / "sessions"
        self._cache: dict[str, _CachedMetadata] = {}
        # Map session_id -> jsonl file path (built during scans)
        self._session_paths: dict[str, Path] = {}

    def _parse_metadata(self, jsonl_path: Path) -> DashboardSessionSummary | None:
        """Parse a JSONL file to extract session metadata."""
        session_id: str | None = None
        project_dir: str | None = None
        git_branch: str | None = None
        model: str | None = None
        total_input = 0
        total_cache_read = 0
        total_cache_creation = 0
        total_output = 0
        message_count = 0
        first_ts: str | None = None
        last_ts: str | None = None

        try:
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    ts = event.get("timestamp")

                    if session_id is None:
                        session_id = event.get("sessionId")
                    if project_dir is None:
                        project_dir = event.get("cwd")
                    if event.get("gitBranch"):
                        git_branch = event["gitBranch"]
                    if ts:
                        if first_ts is None:
                            first_ts = ts
                        last_ts = ts

                    if event_type in self.DISPLAYED_TYPES:
                        message_count += 1

                    if event_type == "assistant":
                        msg = event.get("message", {})
                        if msg.get("model"):
                            model = msg["model"]
                        usage = msg.get("usage", {})
                        total_input += usage.get("input_tokens", 0)
                        total_cache_read += usage.get("cache_read_input_tokens", 0)
                        total_cache_creation += usage.get(
                            "cache_creation_input_tokens", 0
                        )
                        total_output += usage.get("output_tokens", 0)
        except OSError:
            return None

        if session_id is None:
            return None

        cost = _estimate_cost(
            model, total_input, total_cache_read, total_cache_creation, total_output
        )

        # Determine status from pre-loaded active sessions lookup
        status = (
            "active"
            if session_id in getattr(self, "_active_sessions", {})
            else "completed"
        )

        now = datetime.now(timezone.utc)
        created = (
            datetime.fromisoformat(first_ts.replace("Z", "+00:00")) if first_ts else now
        )
        updated = (
            datetime.fromisoformat(last_ts.replace("Z", "+00:00")) if last_ts else now
        )

        # Derive name from project dir basename
        name = Path(project_dir).name if project_dir else session_id[:12]

        return DashboardSessionSummary(
            id=session_id,
            name=name,
            project_dir=project_dir or "",
            source="native",
            status=status,
            current_model=model,
            total_cost_usd=round(cost, 5),
            cost_is_estimated=True,
            message_count=message_count,
            git_branch=git_branch,
            created_at=created,
            updated_at=updated,
            claude_session_id=session_id,
        )

    def _load_active_sessions(self) -> dict[str, int]:
        """Load all active session files once into a sessionId -> pid lookup."""
        active: dict[str, int] = {}
        if not self._sessions_dir.exists():
            return active
        for sf in self._sessions_dir.glob("*.json"):
            try:
                data = json.loads(sf.read_text())
                sid = data.get("sessionId")
                pid = data.get("pid")
                if sid and pid:
                    try:
                        os.kill(pid, 0)
                        active[sid] = pid
                    except (ProcessLookupError, PermissionError):
                        pass
            except (json.JSONDecodeError, OSError):
                continue
        return active

    def load_active_pids(self) -> dict[str, int]:
        """Return a map of session_id -> PID for all currently active native sessions."""
        return self._load_active_sessions()

    def get_active_pid(self, session_id: str) -> int | None:
        """Return the PID if this session is currently running natively, else None."""
        active = self._load_active_sessions()
        return active.get(session_id)

    def _scan_sessions(self) -> None:
        """Scan projects directory and update cache."""
        if not self._projects_dir.exists():
            return

        # Load active session pids once for the entire scan
        self._active_sessions = self._load_active_sessions()

        seen: set[str] = set()
        for project_dir in self._projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                # Session ID is the filename without extension
                session_id_candidate = jsonl_file.stem
                # Skip files that don't look like UUIDs
                if len(session_id_candidate) < 30:
                    continue

                try:
                    mtime = jsonl_file.stat().st_mtime
                except OSError:
                    continue

                cached = self._cache.get(session_id_candidate)
                if cached and cached.mtime == mtime:
                    seen.add(session_id_candidate)
                    self._session_paths[session_id_candidate] = jsonl_file
                    continue

                summary = self._parse_metadata(jsonl_file)
                if summary:
                    self._cache[summary.id] = _CachedMetadata(summary, mtime)
                    self._session_paths[summary.id] = jsonl_file
                    seen.add(summary.id)

        # Remove stale entries
        for stale_id in set(self._cache.keys()) - seen:
            del self._cache[stale_id]
            self._session_paths.pop(stale_id, None)

    def list_sessions(
        self,
        max_age_days: int | None = None,
        hidden_ids: set[str] | None = None,
        archived: bool = False,
    ) -> list[DashboardSessionSummary]:
        """List native sessions with optional recency and visibility filters."""
        self._scan_sessions()

        now = datetime.now(timezone.utc)
        results = []
        for c in self._cache.values():
            s = c.summary
            if s.project_dir in _HIDDEN_PROJECT_DIRS:
                continue

            is_hidden = hidden_ids and s.id in hidden_ids

            if archived:
                if not is_hidden:
                    continue
            else:
                if is_hidden:
                    continue
                if max_age_days is not None:
                    age = now - s.updated_at
                    if age.days > max_age_days:
                        continue

            results.append(s)
        return results

    def get_session(self, session_id: str) -> DashboardSessionSummary | None:
        """Get metadata for a single session."""
        self._scan_sessions()
        cached = self._cache.get(session_id)
        return cached.summary if cached else None

    def get_session_messages(
        self, session_id: str, offset: int = 0, limit: int = 100
    ) -> tuple[list[dict], int]:
        """Get paginated messages for a session.

        Returns (messages, total_count) where messages are only displayed types.
        """
        self._scan_sessions()
        jsonl_path = self._session_paths.get(session_id)
        if not jsonl_path or not jsonl_path.exists():
            return [], 0

        messages: list[dict] = []
        try:
            with open(jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") in self.DISPLAYED_TYPES:
                        messages.append(event)
        except OSError:
            return [], 0

        total = len(messages)
        return messages[offset : offset + limit], total
