import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from claude_code_remote.native_sessions import NativeSessionReader


def _write_session(projects_dir, project_name, session_id, ts, cwd="/tmp/proj"):
    project_dir = projects_dir / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    jsonl = project_dir / f"{session_id}.jsonl"
    event = json.dumps(
        {
            "type": "user",
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": ts,
            "message": {"role": "user", "content": "hello"},
        }
    )
    jsonl.write_text(event + "\n")
    return jsonl


def test_get_active_pid_no_active(tmp_path):
    reader = NativeSessionReader(claude_dir=tmp_path)
    assert reader.get_active_pid("some-uuid") is None


def test_get_active_pid_with_active(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    pid = os.getpid()
    (sessions_dir / "test.json").write_text(
        json.dumps({"sessionId": "uuid-123", "pid": pid})
    )
    reader = NativeSessionReader(claude_dir=tmp_path)
    assert reader.get_active_pid("uuid-123") == pid


def test_list_sessions_recency_filter(tmp_path):
    projects_dir = tmp_path / "projects"
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat()
    recent_ts = (now - timedelta(hours=1)).isoformat()
    _write_session(projects_dir, "proj", "a" * 36, old_ts, "/Users/test/proj")
    _write_session(projects_dir, "proj", "b" * 36, recent_ts, "/Users/test/proj")
    reader = NativeSessionReader(claude_dir=tmp_path)
    sessions = reader.list_sessions(max_age_days=7)
    ids = [s.id for s in sessions]
    assert "b" * 36 in ids
    assert "a" * 36 not in ids


def test_list_sessions_respects_hidden(tmp_path):
    projects_dir = tmp_path / "projects"
    now = datetime.now(timezone.utc).isoformat()
    _write_session(projects_dir, "proj", "c" * 36, now, "/Users/test/proj")
    _write_session(projects_dir, "proj", "d" * 36, now, "/Users/test/proj")
    reader = NativeSessionReader(claude_dir=tmp_path)
    sessions = reader.list_sessions(hidden_ids={"c" * 36})
    ids = [s.id for s in sessions]
    assert "d" * 36 in ids
    assert "c" * 36 not in ids


def test_list_sessions_hidden_returns_in_archived_mode(tmp_path):
    projects_dir = tmp_path / "projects"
    now = datetime.now(timezone.utc).isoformat()
    _write_session(projects_dir, "proj", "e" * 36, now, "/Users/test/proj")
    reader = NativeSessionReader(claude_dir=tmp_path)
    sessions = reader.list_sessions(hidden_ids={"e" * 36}, archived=True)
    ids = [s.id for s in sessions]
    assert "e" * 36 in ids
