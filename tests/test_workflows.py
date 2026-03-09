import pytest
from pathlib import Path
from claude_code_remote.workflows import WorkflowEngine
from claude_code_remote.models import (
    Workflow,
    WorkflowStep,
    WorkflowStatus,
    WorkflowStepStatus,
    SessionCreate,
)


@pytest.fixture
def engine(tmp_path):
    return WorkflowEngine(tmp_path / "workflows")


def test_create_workflow(engine):
    wf = engine.create("test-wf", steps=[])
    assert wf.name == "test-wf"
    assert wf.status == WorkflowStatus.CREATED
    assert wf.id is not None


def test_list_workflows(engine):
    engine.create("wf1", steps=[])
    engine.create("wf2", steps=[])
    assert len(engine.list()) == 2


def test_get_workflow(engine):
    wf = engine.create("test", steps=[])
    found = engine.get(wf.id)
    assert found is not None
    assert found.name == "test"


def test_delete_workflow(engine):
    wf = engine.create("del-me", steps=[])
    assert engine.delete(wf.id) is True
    assert engine.get(wf.id) is None


def test_delete_nonexistent(engine):
    assert engine.delete("nope") is False


def test_persistence(tmp_path):
    wf_dir = tmp_path / "workflows"
    engine1 = WorkflowEngine(wf_dir)
    engine1.create("persistent", steps=[])

    engine2 = WorkflowEngine(wf_dir)
    assert len(engine2.list()) == 1
    assert engine2.list()[0].name == "persistent"
