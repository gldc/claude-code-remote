"""Non-destructive hidden sessions store for native Claude Code sessions."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class HiddenSessionsStore:
    """Tracks native session UUIDs that the user has hidden from the app.

    Two tiers:
    - hidden (archived): visible in archive view, can be unhidden
    - permanently hidden (deleted): not shown anywhere in app
    """

    def __init__(self, path: Path):
        self._path = path
        self._hidden: set[str] = set()
        self._permanent: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._hidden = set(data.get("hidden", []))
            self._permanent = set(data.get("permanent", []))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load hidden sessions: %s", e)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {"hidden": sorted(self._hidden), "permanent": sorted(self._permanent)},
                indent=2,
            )
        )
        os.chmod(self._path, 0o600)

    def hide(self, session_id: str, permanent: bool = False) -> None:
        if permanent:
            self._permanent.add(session_id)
            self._hidden.discard(session_id)
        else:
            if session_id not in self._permanent:
                self._hidden.add(session_id)
        self._save()

    def unhide(self, session_id: str) -> None:
        if session_id in self._permanent:
            return
        self._hidden.discard(session_id)
        self._save()

    def is_hidden(self, session_id: str) -> bool:
        return session_id in self._hidden or session_id in self._permanent

    def is_permanently_hidden(self, session_id: str) -> bool:
        return session_id in self._permanent

    def list_hidden(self, include_permanent: bool = True) -> list[str]:
        if include_permanent:
            return sorted(self._hidden | self._permanent)
        return sorted(self._hidden)
