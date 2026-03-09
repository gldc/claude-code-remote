# tests/test_push.py
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from claude_code_remote.push import PushManager


@pytest.fixture
def push_mgr(tmp_path):
    return PushManager(tmp_path / "push.json")


def test_register_token(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    assert "ExponentPushToken[abc123]" in push_mgr.tokens


def test_register_duplicate_token(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    push_mgr.register_token("ExponentPushToken[abc123]")
    assert len(push_mgr.tokens) == 1


def test_persist_tokens(push_mgr, tmp_path):
    push_mgr.register_token("ExponentPushToken[abc123]")
    mgr2 = PushManager(tmp_path / "push.json")
    assert "ExponentPushToken[abc123]" in mgr2.tokens


def test_default_settings(push_mgr):
    s = push_mgr.get_settings()
    assert s.notify_approvals is True
    assert s.notify_completions is True
    assert s.notify_errors is True


@pytest.mark.asyncio
async def test_send_notification(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch("claude_code_remote.push.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()
        await push_mgr.send("Test Title", "Test body", {"session_id": "123"})
        mock_client.post.assert_called_once()
