"""Tests for file upload utilities."""

import os
from pathlib import Path

import pytest

from claude_code_remote.uploads import sanitize_filename, save_upload, ensure_gitignore


def test_sanitize_filename_basic():
    assert sanitize_filename("screenshot.png") == "screenshot.png"


def test_sanitize_filename_strips_directory():
    # basename("../../.env") = ".env", lstrip(".") = "env"
    assert sanitize_filename("../../.env") == "env"


def test_sanitize_filename_replaces_unsafe_chars():
    assert sanitize_filename("my file (1).png") == "my_file__1_.png"


def test_sanitize_filename_preserves_safe_chars():
    assert sanitize_filename("my-file_v2.3.pdf") == "my-file_v2.3.pdf"


def test_sanitize_filename_rejects_empty():
    with pytest.raises(ValueError):
        sanitize_filename("")


def test_sanitize_filename_rejects_dots_only():
    with pytest.raises(ValueError):
        sanitize_filename("...")


def test_save_upload(tmp_path):
    result = save_upload(str(tmp_path), "test.png", b"fake image data")
    assert result["name"] == "test.png"
    assert result["path"] == "./claude-uploads/test.png"
    assert result["size"] == len(b"fake image data")
    assert (tmp_path / "claude-uploads" / "test.png").exists()
    assert (tmp_path / "claude-uploads" / "test.png").read_bytes() == b"fake image data"


def test_save_upload_collision(tmp_path):
    save_upload(str(tmp_path), "test.png", b"first")
    result = save_upload(str(tmp_path), "test.png", b"second")
    assert result["name"] == "test-1.png"
    assert result["path"] == "./claude-uploads/test-1.png"
    assert (tmp_path / "claude-uploads" / "test-1.png").read_bytes() == b"second"


def test_save_upload_multiple_collisions(tmp_path):
    save_upload(str(tmp_path), "test.png", b"1")
    save_upload(str(tmp_path), "test.png", b"2")
    result = save_upload(str(tmp_path), "test.png", b"3")
    assert result["name"] == "test-2.png"


def test_save_upload_no_extension_collision(tmp_path):
    save_upload(str(tmp_path), "README", b"1")
    result = save_upload(str(tmp_path), "README", b"2")
    assert result["name"] == "README-1"


def test_save_upload_creates_directory(tmp_path):
    assert not (tmp_path / "claude-uploads").exists()
    save_upload(str(tmp_path), "test.txt", b"data")
    assert (tmp_path / "claude-uploads").is_dir()


def test_save_upload_path_traversal_blocked(tmp_path):
    """Filenames that resolve outside claude-uploads/ should be sanitized."""
    result = save_upload(str(tmp_path), "../../../etc/passwd", b"data")
    assert "etc" not in result["path"] or "claude-uploads" in result["path"]
    # File must be inside claude-uploads
    saved_path = tmp_path / "claude-uploads" / result["name"]
    assert saved_path.exists()


def test_ensure_gitignore_creates(tmp_path):
    ensure_gitignore(str(tmp_path))
    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert "claude-uploads/" in gitignore.read_text()


def test_ensure_gitignore_appends(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    ensure_gitignore(str(tmp_path))
    content = (tmp_path / ".gitignore").read_text()
    assert "node_modules/" in content
    assert "claude-uploads/" in content


def test_ensure_gitignore_idempotent(tmp_path):
    ensure_gitignore(str(tmp_path))
    ensure_gitignore(str(tmp_path))
    content = (tmp_path / ".gitignore").read_text()
    assert content.count("claude-uploads/") == 1
