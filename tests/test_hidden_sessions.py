from pathlib import Path
from claude_code_remote.hidden_sessions import HiddenSessionsStore


def test_hide_and_list(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-1")
    assert store.is_hidden("uuid-1")
    assert not store.is_permanently_hidden("uuid-1")


def test_permanently_hide(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-2", permanent=True)
    assert store.is_hidden("uuid-2")
    assert store.is_permanently_hidden("uuid-2")


def test_unhide(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-3")
    store.unhide("uuid-3")
    assert not store.is_hidden("uuid-3")


def test_unhide_permanent_not_allowed(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-4", permanent=True)
    store.unhide("uuid-4")
    assert store.is_hidden("uuid-4")


def test_list_hidden_non_permanent(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-a")
    store.hide("uuid-b", permanent=True)
    store.hide("uuid-c")
    archived = store.list_hidden(include_permanent=False)
    assert set(archived) == {"uuid-a", "uuid-c"}


def test_persistence(tmp_path: Path):
    path = tmp_path / "hidden.json"
    store1 = HiddenSessionsStore(path)
    store1.hide("uuid-5")
    store1.hide("uuid-6", permanent=True)
    store2 = HiddenSessionsStore(path)
    assert store2.is_hidden("uuid-5")
    assert store2.is_permanently_hidden("uuid-6")


def test_empty_file(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "nonexistent.json")
    assert not store.is_hidden("anything")
    assert store.list_hidden() == []
