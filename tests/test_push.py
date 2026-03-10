# tests/test_push.py
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from claude_code_remote.push import PushManager
from claude_code_remote.session_manager import SessionManager
from claude_code_remote.models import Session, SessionStatus


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


@pytest.mark.asyncio
async def test_send_with_category_and_thread_id(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch("claude_code_remote.push.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()
        await push_mgr.send(
            "Test",
            "Body",
            {"key": "val"},
            category="approval_request",
            thread_id="sess123",
        )
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"][0]
        assert payload["categoryIdentifier"] == "approval_request"
        assert payload["threadId"] == "sess123"


@pytest.mark.asyncio
async def test_send_without_category_omits_fields(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch("claude_code_remote.push.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock()
        await push_mgr.send("Test", "Body")
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"][0]
        assert "categoryIdentifier" not in payload
        assert "threadId" not in payload


@pytest.mark.asyncio
async def test_notify_approval_rich_body_bash(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch.object(push_mgr, "send", new_callable=AsyncMock) as mock_send:
        await push_mgr.notify_approval(
            "my-session",
            "Bash",
            {"command": "rm -rf node_modules && npm install"},
            "sess123",
        )
        mock_send.assert_called_once()
        args = mock_send.call_args
        body = args[0][1]
        assert "Bash: rm" in body  # only base command name, no arguments
        assert "node_modules" not in body  # arguments must not leak
        assert args[1]["category"] == "approval_request"
        assert args[1]["thread_id"] == "sess123"


@pytest.mark.asyncio
async def test_notify_approval_rich_body_edit(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch.object(push_mgr, "send", new_callable=AsyncMock) as mock_send:
        await push_mgr.notify_approval(
            "my-session",
            "Edit",
            {"file_path": "/src/main.py", "old_string": "x", "new_string": "y"},
            "sess123",
        )
        args = mock_send.call_args
        body = args[0][1]
        assert "main.py" in body  # only filename, not full path
        assert "/src/" not in body  # full path must not leak


@pytest.mark.asyncio
async def test_notify_approval_rich_body_truncates(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch.object(push_mgr, "send", new_callable=AsyncMock) as mock_send:
        await push_mgr.notify_approval(
            "my-session",
            "Bash",
            {"command": "x" * 500},
            "sess123",
        )
        args = mock_send.call_args
        body = args[0][1]
        # Only the base command name is shown, so body is always short
        assert "Bash:" in body
        assert len(body) <= 350  # reasonable max


@pytest.mark.asyncio
async def test_notify_action_confirmed_approve(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch.object(push_mgr, "send", new_callable=AsyncMock) as mock_send:
        await push_mgr.notify_action_confirmed("my-session", "Bash", True, "sess123")
        args = mock_send.call_args
        assert args[0][0] == "Approved"  # title
        assert "Bash" in args[0][1]
        assert args[1]["sound"] is None
        assert args[1]["thread_id"] == "sess123"


@pytest.mark.asyncio
async def test_notify_action_confirmed_deny(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch.object(push_mgr, "send", new_callable=AsyncMock) as mock_send:
        await push_mgr.notify_action_confirmed("my-session", "Bash", False, "sess123")
        args = mock_send.call_args
        assert args[0][0] == "Denied"


@pytest.mark.asyncio
async def test_notify_approval_empty_tool_input(push_mgr):
    push_mgr.register_token("ExponentPushToken[abc123]")
    with patch.object(push_mgr, "send", new_callable=AsyncMock) as mock_send:
        await push_mgr.notify_approval("my-session", "Bash", {}, "sess123")
        mock_send.assert_called_once()
        body = mock_send.call_args[0][1]
        assert "Bash" in body


def test_summarize_tool_input_read(push_mgr):
    result = push_mgr._summarize_tool_input("Read", {"file_path": "/foo/bar.py"})
    assert "Read: bar.py" in result  # only filename, not full path
    assert "/foo/" not in result


def test_summarize_tool_input_generic(push_mgr):
    result = push_mgr._summarize_tool_input("SomeCustomTool", {"arg1": "val1"})
    # Fallback shows only tool name, no raw input
    assert result == "SomeCustomTool"
    assert "arg1" not in result
    assert "val1" not in result


def test_get_pending_tool_name_no_messages(tmp_path):
    mgr = SessionManager(session_dir=tmp_path / "sessions")
    session = Session(
        name="test",
        project_dir="/tmp",
        status=SessionStatus.AWAITING_APPROVAL,
        messages=[],
    )
    mgr.sessions[session.id] = session
    assert mgr._get_pending_tool_name(session.id) == "Unknown"
