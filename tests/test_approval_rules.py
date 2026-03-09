import pytest
from pathlib import Path
from claude_code_remote.approval_rules import ApprovalRulesStore


@pytest.fixture
def store(tmp_path):
    return ApprovalRulesStore(tmp_path / "rules.json")


def test_create_rule(store):
    rule = store.create("Bash*", action="approve")
    assert rule.tool_pattern == "Bash*"
    assert rule.action == "approve"
    assert rule.id is not None


def test_list_rules(store):
    store.create("Bash*")
    store.create("Write")
    assert len(store.list()) == 2


def test_delete_rule(store):
    rule = store.create("Bash*")
    assert store.delete(rule.id) is True
    assert len(store.list()) == 0


def test_delete_nonexistent(store):
    assert store.delete("nope") is False


def test_check_exact_match(store):
    store.create("Write", action="deny")
    result = store.check("Write")
    assert result is not None
    assert result.action == "deny"


def test_check_glob_match(store):
    store.create("Bash*", action="approve")
    result = store.check("Bash")
    assert result is not None
    assert result.action == "approve"

    result = store.check("BashExec")
    assert result is not None


def test_check_no_match(store):
    store.create("Write", action="deny")
    result = store.check("Read")
    assert result is None


def test_check_project_scope(store):
    store.create("Bash*", action="approve", project_dir="/home/user/project")
    # Matching project
    result = store.check("Bash", project_dir="/home/user/project")
    assert result is not None
    # Different project
    result = store.check("Bash", project_dir="/home/user/other")
    assert result is None


def test_persistence(tmp_path):
    path = tmp_path / "rules.json"
    store1 = ApprovalRulesStore(path)
    store1.create("Write", action="deny")

    store2 = ApprovalRulesStore(path)
    assert len(store2.list()) == 1
    assert store2.list()[0].action == "deny"
