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
    WSMessage,
    WSMessageType,
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


def test_ws_message_serialization():
    msg = WSMessage(type=WSMessageType.ASSISTANT_TEXT, data={"text": "hello"})
    d = msg.model_dump()
    assert d["type"] == "assistant_text"
    assert "timestamp" in d


def test_project_type_detection():
    assert ProjectType.PYTHON == "python"
    assert ProjectType.NODE == "node"
