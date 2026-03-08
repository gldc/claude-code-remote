"""OAuth-based usage client for Claude Max plan."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from .models import UsageData, UsageWindow, UsageWindowWithReserve, ExtraUsage

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
            return data.get("access_token") or data.get("token")
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
                return data.get("access_token") or data.get("token") or raw
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

    def _parse_usage(self, data: dict) -> UsageData:
        """Parse Anthropic usage API response."""
        usage = UsageData()

        if "five_hour" in data:
            fh = data["five_hour"]
            usage.session = UsageWindow(
                percent_remaining=fh.get("percent_remaining", 0),
                resets_in_seconds=fh.get("resets_in_seconds", 0),
            )

        if "seven_day" in data:
            sd = data["seven_day"]
            usage.weekly = UsageWindowWithReserve(
                percent_remaining=sd.get("percent_remaining", 0),
                reserve_percent=sd.get("reserve_percent", 0),
                resets_in_seconds=sd.get("resets_in_seconds", 0),
            )

        # Sonnet-specific weekly (may be under seven_day_sonnet or similar)
        for key in ("seven_day_sonnet", "sonnet"):
            if key in data:
                s = data[key]
                usage.sonnet = UsageWindow(
                    percent_remaining=s.get("percent_remaining", 0),
                    resets_in_seconds=s.get("resets_in_seconds", 0),
                )
                break

        if "extra_usage" in data:
            eu = data["extra_usage"]
            usage.extra_usage = ExtraUsage(
                monthly_spend=eu.get("monthly_spend", 0),
                monthly_limit=eu.get("monthly_limit", 0),
            )

        usage.plan_tier = data.get("rate_limit_tier", data.get("plan", "unknown"))
        return usage

    async def _append_history(self, usage: UsageData) -> None:
        """Append usage snapshot to JSONL history file."""
        try:
            line = usage.model_dump_json() + "\n"
            await asyncio.to_thread(lambda: self.history_file.open("a").write(line))
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
