# tests/test_session_manager.py
import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from claude_code_remote.session_manager import SessionManager
from claude_code_remote.models import SessionCreate, SessionStatus


@pytest.fixture
def tmp_session_dir(tmp_path):
    return tmp_path / "sessions"


@pytest.fixture
def manager(tmp_session_dir):
    return SessionManager(session_dir=tmp_session_dir, max_concurrent=5)


def test_create_session(manager):
    req = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    session = manager.create_session(req)
    assert session.name == "test"
    assert session.status == SessionStatus.CREATED
    assert session.id in manager.sessions


def test_list_sessions_empty(manager):
    assert manager.list_sessions() == []


def test_list_sessions_with_filter(manager):
    req1 = SessionCreate(name="a", project_dir="/tmp", initial_prompt="x")
    req2 = SessionCreate(name="b", project_dir="/tmp", initial_prompt="y")
    s1 = manager.create_session(req1)
    s2 = manager.create_session(req2)
    s1.status = SessionStatus.RUNNING
    s2.status = SessionStatus.COMPLETED
    running = manager.list_sessions(status=SessionStatus.RUNNING)
    assert len(running) == 1
    assert running[0].id == s1.id


def test_get_session(manager):
    req = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    session = manager.create_session(req)
    found = manager.get_session(session.id)
    assert found is not None
    assert found.id == session.id


def test_get_session_not_found(manager):
    assert manager.get_session("nonexistent") is None


def test_delete_session(manager):
    req = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    session = manager.create_session(req)
    manager.delete_session(session.id)
    assert manager.get_session(session.id) is None


def test_max_concurrent_sessions(manager):
    manager.max_concurrent = 2
    for i in range(2):
        req = SessionCreate(name=f"s{i}", project_dir="/tmp", initial_prompt="x")
        s = manager.create_session(req)
        s.status = SessionStatus.RUNNING
    req = SessionCreate(name="s3", project_dir="/tmp", initial_prompt="x")
    with pytest.raises(RuntimeError, match="Maximum concurrent"):
        manager.create_session(req)


def test_persist_and_load(manager, tmp_session_dir):
    req = SessionCreate(name="persist", project_dir="/tmp", initial_prompt="hello")
    session = manager.create_session(req)
    manager.persist_session(session.id)
    assert (tmp_session_dir / f"{session.id}.json").exists()

    manager2 = SessionManager(session_dir=tmp_session_dir, max_concurrent=5)
    manager2.load_sessions()
    loaded = manager2.get_session(session.id)
    assert loaded is not None
    assert loaded.name == "persist"
