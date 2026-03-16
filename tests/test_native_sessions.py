"""Tests for native Claude Code session discovery and parsing."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_code_remote.native_sessions import NativeSessionReader


@pytest.fixture
def claude_dir(tmp_path):
    """Set up a fake ~/.claude directory structure."""
    projects_dir = tmp_path / "projects"
    sessions_dir = tmp_path / "sessions"
    projects_dir.mkdir()
    sessions_dir.mkdir()
    return tmp_path


@pytest.fixture
def sample_jsonl(claude_dir):
    """Create a sample JSONL conversation file."""
    project_hash = "-Users-test-Developer-myproject"
    project_dir = claude_dir / "projects" / project_hash
    project_dir.mkdir()

    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    jsonl_file = project_dir / f"{session_id}.jsonl"

    events = [
        {
            "type": "user",
            "message": {"role": "user", "content": "Hello"},
            "uuid": "u1",
            "timestamp": "2026-03-15T10:00:00.000Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/myproject",
            "gitBranch": "main",
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-6",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hi!"}],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
            "uuid": "a1",
            "timestamp": "2026-03-15T10:00:01.000Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/myproject",
            "gitBranch": "main",
        },
        {
            "type": "progress",
            "data": {"type": "hook_progress"},
            "uuid": "p1",
            "timestamp": "2026-03-15T10:00:00.500Z",
            "sessionId": session_id,
            "cwd": "/Users/test/Developer/myproject",
        },
    ]
    with open(jsonl_file, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return jsonl_file, session_id


@pytest.fixture
def history_jsonl(claude_dir):
    """Create a sample history.jsonl."""
    history_file = claude_dir / "history.jsonl"
    entries = [
        {
            "display": "Hello",
            "timestamp": 1741950000000,
            "project": "/Users/test/Developer/myproject",
            "sessionId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
    ]
    with open(history_file, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return history_file


def test_list_sessions(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    sessions = reader.list_sessions()
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "native"
    assert s.project_dir == "/Users/test/Developer/myproject"
    assert s.current_model == "claude-sonnet-4-6"
    assert s.message_count == 2  # user + assistant, not progress
    assert s.git_branch == "main"
    assert s.cost_is_estimated is True
    assert s.total_cost_usd > 0


def test_get_session_messages(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    session_id = sample_jsonl[1]
    messages, total = reader.get_session_messages(session_id, offset=0, limit=100)
    assert total == 2  # user + assistant
    assert messages[0]["type"] == "user"
    assert messages[1]["type"] == "assistant"


def test_get_session_messages_pagination(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    session_id = sample_jsonl[1]
    messages, total = reader.get_session_messages(session_id, offset=0, limit=1)
    assert len(messages) == 1
    assert total == 2


def test_get_session(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    session_id = sample_jsonl[1]
    s = reader.get_session(session_id)
    assert s is not None
    assert s.id == session_id
    assert s.source == "native"


def test_get_session_not_found(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    s = reader.get_session("nonexistent-session-id")
    assert s is None


def test_malformed_jsonl_skipped(claude_dir):
    """Malformed lines should be skipped, not crash."""
    project_dir = claude_dir / "projects" / "-Users-test-Developer-broken"
    project_dir.mkdir()
    session_id = "11111111-2222-3333-4444-555555555555"
    jsonl_file = project_dir / f"{session_id}.jsonl"
    with open(jsonl_file, "w") as f:
        f.write("NOT VALID JSON\n")
        f.write(
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "test"},
                    "uuid": "u1",
                    "timestamp": "2026-03-15T10:00:00.000Z",
                    "sessionId": session_id,
                    "cwd": "/Users/test/Developer/broken",
                }
            )
            + "\n"
        )

    reader = NativeSessionReader(claude_dir)
    sessions = reader.list_sessions()
    assert len(sessions) == 1
    assert sessions[0].message_count == 1


def test_cost_estimation(claude_dir, sample_jsonl):
    reader = NativeSessionReader(claude_dir)
    sessions = reader.list_sessions()
    s = sessions[0]
    # sonnet: $3/1M input, $15/1M output
    # 100 input + 10 output = $0.0003 + $0.00015 = $0.00045
    assert abs(s.total_cost_usd - 0.00045) < 0.0001


def test_cache_invalidation(claude_dir, sample_jsonl):
    """Metadata should update when file changes."""
    reader = NativeSessionReader(claude_dir)
    sessions = reader.list_sessions()
    assert sessions[0].message_count == 2

    # Append another user message
    jsonl_file = sample_jsonl[0]
    with open(jsonl_file, "a") as f:
        f.write(
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "Another message"},
                    "uuid": "u2",
                    "timestamp": "2026-03-15T10:01:00.000Z",
                    "sessionId": sample_jsonl[1],
                    "cwd": "/Users/test/Developer/myproject",
                }
            )
            + "\n"
        )

    sessions = reader.list_sessions()
    assert sessions[0].message_count == 3
