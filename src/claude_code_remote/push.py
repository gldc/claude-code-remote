"""Push notifications via Expo Push API."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from claude_code_remote.models import PushSettings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


class PushManager:
    def __init__(self, push_file: Path):
        self.push_file = push_file
        self.tokens: set[str] = set()
        self.settings = PushSettings()
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.push_file.read_text())
            self.tokens = set(data.get("tokens", []))
            if "settings" in data:
                self.settings = PushSettings(**data["settings"])
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        self.push_file.parent.mkdir(parents=True, exist_ok=True)
        self.push_file.write_text(
            json.dumps(
                {
                    "tokens": list(self.tokens),
                    "settings": self.settings.model_dump(),
                },
                indent=2,
            )
        )

    def register_token(self, token: str) -> None:
        self.tokens.add(token)
        self._save()

    def get_settings(self) -> PushSettings:
        return self.settings

    def update_settings(self, settings: PushSettings) -> None:
        self.settings = settings
        self._save()

    async def send(
        self,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self.tokens:
            return

        messages = [
            {
                "to": token,
                "title": title,
                "body": body,
                "data": data or {},
                "sound": "default",
            }
            for token in self.tokens
        ]

        try:
            async with httpx.AsyncClient() as client:
                await client.post(EXPO_PUSH_URL, json=messages, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")

    async def notify_approval(
        self, session_name: str, tool_name: str, session_id: str
    ) -> None:
        if self.settings.notify_approvals:
            await self.send(
                "Approval Needed",
                f"Session '{session_name}' wants to: {tool_name}",
                {"session_id": session_id, "type": "approval_request"},
            )

    async def notify_completion(
        self, session_name: str, cost: float, session_id: str
    ) -> None:
        if self.settings.notify_completions:
            await self.send(
                "Task Complete",
                f"Session '{session_name}' finished (${cost:.2f})",
                {"session_id": session_id, "type": "session_completed"},
            )

    async def notify_error(
        self, session_name: str, error: str, session_id: str
    ) -> None:
        if self.settings.notify_errors:
            await self.send(
                "Session Error",
                f"Session '{session_name}': {error[:100]}",
                {"session_id": session_id, "type": "session_error"},
            )
