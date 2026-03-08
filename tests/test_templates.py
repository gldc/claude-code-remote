# tests/test_templates.py
import pytest
from pathlib import Path
from claude_code_remote.templates import TemplateStore, BUILTIN_TEMPLATES
from claude_code_remote.models import TemplateCreate


@pytest.fixture
def store(tmp_path):
    return TemplateStore(tmp_path / "templates")


def test_create_template(store):
    req = TemplateCreate(name="debug", initial_prompt="fix it")
    t = store.create(req)
    assert t.name == "debug"
    assert t.id is not None


def test_list_templates(store):
    store.create(TemplateCreate(name="a", initial_prompt="x"))
    store.create(TemplateCreate(name="b", initial_prompt="y"))
    # 2 user-created + built-in templates
    assert len(store.list()) == 2 + len(BUILTIN_TEMPLATES)


def test_builtin_templates_seeded(store):
    templates = store.list()
    builtin_ids = {t.id for t in templates if t.is_builtin}
    assert len(builtin_ids) == len(BUILTIN_TEMPLATES)


def test_get_template(store):
    t = store.create(TemplateCreate(name="test", initial_prompt="hi"))
    found = store.get(t.id)
    assert found is not None
    assert found.name == "test"


def test_update_template(store):
    t = store.create(TemplateCreate(name="old", initial_prompt="x"))
    updated = store.update(t.id, TemplateCreate(name="new", initial_prompt="y"))
    assert updated.name == "new"
    assert updated.id == t.id


def test_delete_template(store):
    t = store.create(TemplateCreate(name="del", initial_prompt="x"))
    store.delete(t.id)
    assert store.get(t.id) is None


def test_template_tags(store):
    req = TemplateCreate(name="tagged", initial_prompt="x", tags=["test", "debug"])
    t = store.create(req)
    assert t.tags == ["test", "debug"]


def test_filter_by_tag(store):
    templates = store.list()
    review_templates = [t for t in templates if "review" in t.tags]
    assert len(review_templates) >= 1
