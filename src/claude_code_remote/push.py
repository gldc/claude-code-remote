"""Push notifications via Expo Push API."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from claude_code_remote.models import PushSettings

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_TOKEN_RE = re.compile(r"^ExponentPushToken\[.+\]$")

# Maximum lengths for push notification fields to prevent abuse
_MAX_TITLE_LEN = 100
_MAX_BODY_LEN = 500


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
        # Push tokens are sensitive — restrict to owner only
        os.chmod(self.push_file, 0o600)

    @staticmethod
    def validate_token(token: str) -> None:
        """Validate that the token matches Expo push token format."""
        if not EXPO_TOKEN_RE.match(token):
            raise ValueError(
                f"Invalid Expo push token format: {token!r}. "
                "Expected format: ExponentPushToken[...]"
            )

    def register_token(self, token: str) -> None:
        self.validate_token(token)
        self.tokens.add(token)
        self._save()

    def get_settings(self) -> PushSettings:
        return self.settings

    def update_settings(self, settings: PushSettings) -> None:
        self.settings = settings
        self._save()

    @staticmethod
    def _sanitize_text(text: str, max_len: int) -> str:
        """Truncate and strip control characters from notification text."""
        # Remove control characters (except newline which is useful in bodies)
        cleaned = re.sub(r"[\x00-\x09\x0b-\x1f\x7f]", "", text)
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len] + "..."
        return cleaned

    async def send(
        self,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        *,
        category: str | None = None,
        thread_id: str | None = None,
        sound: str | None = "default",
    ) -> None:
        if not self.tokens:
            return

        # Sanitize text fields
        title = self._sanitize_text(title, _MAX_TITLE_LEN)
        body = self._sanitize_text(body, _MAX_BODY_LEN)

        # Strip any sensitive keys from data payload
        safe_data = {}
        if data:
            allowed_keys = {"session_id", "type", "tool_name"}
            safe_data = {k: v for k, v in data.items() if k in allowed_keys}

        base_msg: dict[str, Any] = {
            "title": title,
            "body": body,
            "data": safe_data,
        }
        if sound is not None:
            base_msg["sound"] = sound
        if category:
            base_msg["categoryIdentifier"] = category
        if thread_id:
            base_msg["threadId"] = thread_id

        messages = [{"to": token, **base_msg} for token in self.tokens]

        try:
            async with httpx.AsyncClient() as client:
                await client.post(EXPO_PUSH_URL, json=messages, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send push notification: {e}")

    def _summarize_tool_input(self, tool_name: str, tool_input: dict) -> str:
        """Build a one-line summary of tool input for notification body.

        Only exposes the minimum info needed (base command name, filename)
        to avoid leaking full paths or command arguments.
        """
        if tool_name == "Bash" and "command" in tool_input:
            # Show only the base command name (first word, basename only)
            first_word = (
                tool_input["command"].split()[0]
                if tool_input["command"].strip()
                else "bash"
            )
            base_cmd = Path(first_word).name[:50]
            return f"Bash: {base_cmd}"
        if tool_name in ("Edit", "Write", "Read") and "file_path" in tool_input:
            # Show only the filename, not the full path
            filename = Path(tool_input["file_path"]).name
            return f"{tool_name}: {filename}"
        # Generic fallback: just show the tool name, do NOT dump raw input
        return tool_name

    async def notify_approval(
        self, session_name: str, tool_name: str, tool_input: dict, session_id: str
    ) -> None:
        if self.settings.notify_approvals:
            summary = self._summarize_tool_input(tool_name, tool_input)
            body = f"Session '{session_name}' wants to run:\n{summary}"
            await self.send(
                "Approval Needed",
                body,
                {
                    "session_id": session_id,
                    "type": "approval_request",
                    "tool_name": tool_name,
                },
                category="approval_request",
                thread_id=session_id,
            )

    async def notify_action_confirmed(
        self, session_name: str, tool_name: str, approved: bool, session_id: str
    ) -> None:
        title = "Approved" if approved else "Denied"
        body = f"{tool_name} in '{session_name}'"
        await self.send(
            title,
            body,
            {"session_id": session_id, "type": "action_confirmed"},
            thread_id=session_id,
            sound=None,
        )

    async def notify_completion(
        self, session_name: str, cost: float, session_id: str
    ) -> None:
        if self.settings.notify_completions:
            await self.send(
                "Task Complete",
                f"Session '{session_name}' finished (${cost:.2f})",
                {"session_id": session_id, "type": "session_completed"},
                thread_id=session_id,
            )

    async def notify_error(
        self, session_name: str, error: str, session_id: str
    ) -> None:
        if self.settings.notify_errors:
            await self.send(
                "Session Error",
                f"Session '{session_name}': {error[:100]}",
                {"session_id": session_id, "type": "session_error"},
                thread_id=session_id,
            )
