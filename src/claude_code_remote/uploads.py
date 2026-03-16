"""File upload utilities — storage, sanitization, and gitignore management."""

from __future__ import annotations

import os
import re
from pathlib import Path

UPLOAD_DIR_NAME = "claude-uploads"


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename: strip directories, replace unsafe chars.

    Raises ValueError if filename is empty after sanitization.
    """
    # Strip to basename only
    name = os.path.basename(filename)
    # Replace unsafe characters
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    # Strip leading dots (hidden files)
    name = name.lstrip(".")
    if not name:
        raise ValueError("Filename is empty after sanitization")
    return name


def _resolve_collision(upload_dir: Path, name: str) -> str:
    """Generate a unique filename by appending -1, -2, etc."""
    if not (upload_dir / name).exists():
        return name

    stem, _, ext = name.rpartition(".")
    if not stem:
        # No extension (e.g., "README")
        stem = name
        ext = ""

    counter = 1
    while True:
        if ext:
            candidate = f"{stem}-{counter}.{ext}"
        else:
            candidate = f"{stem}-{counter}"
        if not (upload_dir / candidate).exists():
            return candidate
        counter += 1


def save_upload(project_dir: str, filename: str, content: bytes) -> dict:
    """Save an uploaded file to claude-uploads/ in the project directory.

    Returns dict with name, path (relative), and size.
    """
    safe_name = sanitize_filename(filename)
    upload_dir = Path(project_dir) / UPLOAD_DIR_NAME
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Resolve collisions
    final_name = _resolve_collision(upload_dir, safe_name)
    dest = upload_dir / final_name

    # Verify path stays within upload_dir (defense in depth)
    if not dest.resolve().is_relative_to(upload_dir.resolve()):
        raise ValueError(f"Path traversal detected: {final_name}")

    dest.write_bytes(content)

    return {
        "name": final_name,
        "path": f"./{UPLOAD_DIR_NAME}/{final_name}",
        "size": len(content),
    }


def ensure_gitignore(project_dir: str) -> None:
    """Ensure claude-uploads/ is in the project's .gitignore."""
    gitignore_path = Path(project_dir) / ".gitignore"
    entry = f"{UPLOAD_DIR_NAME}/"

    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if entry in content:
            return
        # Ensure we start on a new line
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore_path.write_text(content)
    else:
        gitignore_path.write_text(f"{entry}\n")
