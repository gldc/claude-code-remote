# tests/test_projects.py
import pytest
from pathlib import Path
from claude_code_remote.projects import scan_directory, detect_project_type
from claude_code_remote.models import ProjectType


def test_detect_python_project(tmp_path):
    (tmp_path / "pyproject.toml").touch()
    assert detect_project_type(tmp_path) == ProjectType.PYTHON


def test_detect_node_project(tmp_path):
    (tmp_path / "package.json").touch()
    assert detect_project_type(tmp_path) == ProjectType.NODE


def test_detect_rust_project(tmp_path):
    (tmp_path / "Cargo.toml").touch()
    assert detect_project_type(tmp_path) == ProjectType.RUST


def test_detect_go_project(tmp_path):
    (tmp_path / "go.mod").touch()
    assert detect_project_type(tmp_path) == ProjectType.GO


def test_detect_unknown_project(tmp_path):
    assert detect_project_type(tmp_path) == ProjectType.UNKNOWN


def test_scan_directory(tmp_path):
    proj1 = tmp_path / "project-a"
    proj1.mkdir()
    (proj1 / ".git").mkdir()
    (proj1 / "package.json").touch()

    proj2 = tmp_path / "project-b"
    proj2.mkdir()
    (proj2 / "pyproject.toml").touch()

    not_a_project = tmp_path / "random-dir"
    not_a_project.mkdir()

    projects = scan_directory(tmp_path)
    assert len(projects) == 2
    names = {p.name for p in projects}
    assert "project-a" in names
    assert "project-b" in names
