"""OAuth-based usage client for Claude Max plan."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from .models import UsageData, UsageWindow, ExtraUsage

logger = logging.getLogger(__name__)

USAGE_API_URL = "https://api.anthropic.com/api/oauth/usage"
ANTHROPIC_BETA = "oauth-2025-04-20"
CACHE_TTL_SECONDS = 60

# Credential locations
KEYCHAIN_SERVICE = "Claude Code-credentials"
CREDENTIALS_FILE = Path.home() / ".claude" / ".credentials.json"


def _read_credentials_file() -> str | None:
    """Read OAuth token from credentials file."""
    try:
        if CREDENTIALS_FILE.exists():
            data = json.loads(CREDENTIALS_FILE.read_text())
            return (
                data.get("access_token")
                or data.get("token")
                or data.get("claudeAiOauth", {}).get("accessToken")
            )
    except Exception as e:
        logger.debug("Failed to read credentials file: %s", e)
    return None


def _read_keychain() -> str | None:
    """Read OAuth token from macOS Keychain."""
    import subprocess

    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Keychain may store JSON or raw token
            raw = result.stdout.strip()
            try:
                data = json.loads(raw)
                return (
                    data.get("access_token")
                    or data.get("token")
                    or data.get("claudeAiOauth", {}).get("accessToken")
                    or raw
                )
            except json.JSONDecodeError:
                return raw
    except Exception as e:
        logger.debug("Failed to read keychain: %s", e)
    return None


def get_oauth_token() -> str | None:
    """Get OAuth token from keychain (preferred) or credentials file."""
    return _read_keychain() or _read_credentials_file()


class UsageClient:
    """Polls Anthropic OAuth usage API and caches results."""

    def __init__(self, history_file: Path):
        self.history_file = history_file
        self._cache: UsageData | None = None
        self._cache_time: float = 0

    async def get_usage(self) -> UsageData:
        """Get current usage data, from cache if fresh."""
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL_SECONDS:
            return self._cache

        token = await asyncio.to_thread(get_oauth_token)
        if not token:
            logger.warning("No OAuth token found for usage API")
            return self._cache or UsageData()

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    USAGE_API_URL,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "anthropic-beta": ANTHROPIC_BETA,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error("Usage API request failed: %s", e)
            return self._cache or UsageData()

        usage = self._parse_usage(data)
        self._cache = usage
        self._cache_time = now

        # Append to history
        await self._append_history(usage)

        return usage

    def _parse_window(self, raw: dict | None) -> UsageWindow | None:
        """Parse a usage window from the API response."""
        if not raw:
            return None
        return UsageWindow(
            utilization=raw.get("utilization", 0.0),
            resets_at=raw.get("resets_at"),
        )

    def _parse_usage(self, data: dict) -> UsageData:
        """Parse Anthropic usage API response."""
        usage = UsageData()

        if "five_hour" in data and data["five_hour"]:
            usage.five_hour = self._parse_window(data["five_hour"]) or usage.five_hour

        if "seven_day" in data and data["seven_day"]:
            usage.seven_day = self._parse_window(data["seven_day"]) or usage.seven_day

        usage.seven_day_sonnet = self._parse_window(data.get("seven_day_sonnet"))
        usage.seven_day_opus = self._parse_window(data.get("seven_day_opus"))

        if "extra_usage" in data and data["extra_usage"]:
            eu = data["extra_usage"]
            usage.extra_usage = ExtraUsage(
                is_enabled=eu.get("is_enabled", False),
                monthly_limit=eu.get("monthly_limit", 0),
                used_credits=eu.get("used_credits", 0),
            )

        # Infer plan tier from response structure
        has_data = (
            data.get("five_hour") is not None or data.get("seven_day") is not None
        )
        usage.plan_tier = "max" if has_data else "unknown"
        return usage

    async def _append_history(self, usage: UsageData) -> None:
        """Append usage snapshot to JSONL history file."""
        try:
            line = usage.model_dump_json() + "\n"

            def _write():
                with self.history_file.open("a") as f:
                    f.write(line)

            await asyncio.to_thread(_write)
        except Exception as e:
            logger.debug("Failed to write usage history: %s", e)

    async def get_history(self, days: int = 7) -> list[UsageData]:
        """Read usage history from JSONL file, filtered to last N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        results = []
        try:
            if not self.history_file.exists():
                return results
            text = await asyncio.to_thread(self.history_file.read_text)
            for line in text.strip().split("\n"):
                if not line:
                    continue
                try:
                    entry = UsageData.model_validate_json(line)
                    if entry.updated_at >= cutoff:
                        results.append(entry)
                except Exception:
                    continue
        except Exception as e:
            logger.debug("Failed to read usage history: %s", e)
        return results
