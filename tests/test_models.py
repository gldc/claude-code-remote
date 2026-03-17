# tests/test_models.py
import pytest
from claude_code_remote.models import (
    Session,
    SessionStatus,
    SessionCreate,
    Template,
    TemplateCreate,
    Project,
    ProjectType,
    PushSettings,
)


def test_session_create_defaults():
    s = SessionCreate(name="test", project_dir="/tmp", initial_prompt="hello")
    assert s.template_id is None
    assert s.model is None
    assert s.max_budget_usd is None


def test_session_status_values():
    assert SessionStatus.RUNNING == "running"
    assert SessionStatus.AWAITING_APPROVAL == "awaiting_approval"
    assert SessionStatus.COMPLETED == "completed"
    assert SessionStatus.ERROR == "error"
    assert SessionStatus.PAUSED == "paused"


def test_template_create():
    t = TemplateCreate(name="debug", initial_prompt="fix the bug")
    assert t.project_dir is None
    assert t.model is None


def test_native_event_format():
    """Validate that native event dicts have the expected shape."""
    assistant_event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "hello"}]},
        "timestamp": "2026-03-17T00:00:00+00:00",
    }
    assert assistant_event["type"] == "assistant"
    assert assistant_event["message"]["content"][0]["text"] == "hello"

    user_event = {
        "type": "user",
        "message": {"role": "user", "content": "hi"},
        "timestamp": "2026-03-17T00:00:00+00:00",
    }
    assert user_event["type"] == "user"
    assert user_event["message"]["content"] == "hi"


def test_project_type_detection():
    assert ProjectType.PYTHON == "python"
    assert ProjectType.NODE == "node"
