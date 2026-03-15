"""Tests for CronManager CRUD operations."""

import json
from pathlib import Path

import pytest

from claude_code_remote.cron_manager import CronManager
from claude_code_remote.models import (
    CronExecutionMode,
    CronJob,
    CronJobCreate,
    CronJobUpdate,
    CronRunStatus,
    SessionCreate,
)


@pytest.fixture
def tmp_cron_dir(tmp_path):
    cron_dir = tmp_path / "cron"
    cron_dir.mkdir()
    return cron_dir


@pytest.fixture
def tmp_history_file(tmp_path):
    return tmp_path / "cron_history.jsonl"


@pytest.fixture
def session_config():
    """A valid SessionCreate for testing (project_dir must exist)."""
    return SessionCreate(
        name="test-cron-session",
        project_dir="/tmp",
        initial_prompt="Run daily check",
    )


@pytest.fixture
def cron_mgr(tmp_cron_dir, tmp_history_file):
    return CronManager(
        cron_dir=tmp_cron_dir,
        history_file=tmp_history_file,
        session_mgr=None,  # No session_mgr needed for CRUD tests
    )


def test_create_cron_job(cron_mgr, session_config):
    req = CronJobCreate(
        name="Daily Check",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    job = cron_mgr.create(req)
    assert job.name == "Daily Check"
    assert job.schedule == "0 9 * * *"
    assert job.enabled is True
    assert job.execution_mode == CronExecutionMode.SPAWN
    assert job.next_run_at is not None


def test_list_cron_jobs(cron_mgr, session_config):
    assert cron_mgr.list() == []
    req = CronJobCreate(
        name="Job 1",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    cron_mgr.create(req)
    assert len(cron_mgr.list()) == 1


def test_get_cron_job(cron_mgr, session_config):
    req = CronJobCreate(
        name="My Job",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    job = cron_mgr.create(req)
    fetched = cron_mgr.get(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert cron_mgr.get("nonexistent") is None


def test_update_cron_job(cron_mgr, session_config):
    req = CronJobCreate(
        name="Old Name",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    job = cron_mgr.create(req)
    updated = cron_mgr.update(
        job.id, CronJobUpdate(name="New Name", schedule="0 10 * * *")
    )
    assert updated.name == "New Name"
    assert updated.schedule == "0 10 * * *"
    assert updated.next_run_at is not None


def test_update_nonexistent_raises(cron_mgr):
    with pytest.raises(ValueError, match="not found"):
        cron_mgr.update("bad-id", CronJobUpdate(name="x"))


def test_delete_cron_job(cron_mgr, session_config):
    req = CronJobCreate(
        name="To Delete",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    job = cron_mgr.create(req)
    cron_mgr.delete(job.id)
    assert cron_mgr.get(job.id) is None
    assert len(cron_mgr.list()) == 0


def test_toggle_cron_job(cron_mgr, session_config):
    req = CronJobCreate(
        name="Toggle Me",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    job = cron_mgr.create(req)
    assert job.enabled is True
    toggled = cron_mgr.toggle(job.id)
    assert toggled.enabled is False
    toggled2 = cron_mgr.toggle(job.id)
    assert toggled2.enabled is True


def test_invalid_cron_expression_raises(cron_mgr, session_config):
    req = CronJobCreate(
        name="Bad Schedule",
        schedule="not a cron expression",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    with pytest.raises(ValueError, match="Invalid cron"):
        cron_mgr.create(req)


def test_persistence_across_reload(tmp_cron_dir, tmp_history_file, session_config):
    mgr1 = CronManager(
        cron_dir=tmp_cron_dir, history_file=tmp_history_file, session_mgr=None
    )
    req = CronJobCreate(
        name="Persistent",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    job = mgr1.create(req)

    mgr2 = CronManager(
        cron_dir=tmp_cron_dir, history_file=tmp_history_file, session_mgr=None
    )
    assert mgr2.get(job.id) is not None
    assert mgr2.get(job.id).name == "Persistent"
