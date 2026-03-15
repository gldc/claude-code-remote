"""Tests for cron job execution logic."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_code_remote.cron_manager import CronManager
from claude_code_remote.models import (
    CronExecutionMode,
    CronJobCreate,
    CronRunStatus,
    Session,
    SessionCreate,
    SessionStatus,
)


@pytest.fixture
def session_config():
    return SessionCreate(
        name="cron-session",
        project_dir="/tmp",
        initial_prompt="Do something",
    )


@pytest.fixture
def mock_session_mgr():
    mgr = MagicMock()
    session = Session(
        name="cron-session",
        project_dir="/tmp",
        status=SessionStatus.CREATED,
    )
    mgr.create_session.return_value = session
    mgr.send_prompt = AsyncMock()
    mgr.persist_session = MagicMock()
    mgr.sessions = {session.id: session}
    return mgr, session


@pytest.fixture
def cron_mgr_with_session(tmp_path, mock_session_mgr):
    mgr, _ = mock_session_mgr
    return CronManager(
        cron_dir=tmp_path / "cron",
        history_file=tmp_path / "history.jsonl",
        session_mgr=mgr,
    )


@pytest.mark.asyncio
async def test_execute_spawn_mode(
    cron_mgr_with_session, session_config, mock_session_mgr
):
    mgr = cron_mgr_with_session
    session_mgr, session = mock_session_mgr

    req = CronJobCreate(
        name="Spawn Job",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    job = mgr.create(req)
    await mgr.execute_job(job.id)

    session_mgr.create_session.assert_called_once()
    session_mgr.send_prompt.assert_called_once()
    # Check run history recorded
    history = mgr.get_history(job.id)
    assert len(history) == 1


@pytest.mark.asyncio
async def test_execute_with_prompt_template(
    cron_mgr_with_session, session_config, mock_session_mgr
):
    mgr = cron_mgr_with_session
    session_mgr, session = mock_session_mgr

    req = CronJobCreate(
        name="Template Job",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
        prompt_template="Run check on {{date}} for {{project}}",
    )
    job = mgr.create(req)
    await mgr.execute_job(job.id)

    # Verify the prompt was substituted (not the raw template)
    call_args = session_mgr.send_prompt.call_args
    prompt = call_args[0][1]  # second positional arg
    assert "{{date}}" not in prompt
    assert "{{project}}" not in prompt


@pytest.mark.asyncio
async def test_execute_skips_if_already_running(
    cron_mgr_with_session, session_config, mock_session_mgr
):
    mgr = cron_mgr_with_session
    session_mgr, session = mock_session_mgr

    # Make send_prompt hang to simulate a running job
    hang_event = asyncio.Event()

    async def hang(*args, **kwargs):
        await hang_event.wait()

    session_mgr.send_prompt = hang

    req = CronJobCreate(
        name="Slow Job",
        schedule="0 9 * * *",
        execution_mode=CronExecutionMode.SPAWN,
        session_config=session_config,
    )
    job = mgr.create(req)

    # Start first execution (will hang)
    task = asyncio.create_task(mgr.execute_job(job.id))
    await asyncio.sleep(0.05)

    # Second execution should be skipped
    await mgr.execute_job(job.id)

    # Only one session should have been created
    assert session_mgr.create_session.call_count == 1

    # Cleanup
    hang_event.set()
    await task
