"""Git operations for session project directories."""

from __future__ import annotations

import asyncio
import logging

from .models import GitStatus, GitFileStatus, GitBranch, GitLogEntry

logger = logging.getLogger(__name__)


async def _run_git(project_dir: str, *args: str, timeout: float = 10) -> str:
    """Run a git command and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        project_dir,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"git {args[0]} timed out after {timeout}s")
    if proc.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {stderr.decode().strip()}")
    return stdout.decode().strip()


async def git_status(project_dir: str) -> GitStatus:
    """Get git status for a project directory."""
    branch = await _run_git(project_dir, "branch", "--show-current")
    raw = await _run_git(project_dir, "status", "--porcelain=v1")

    modified, staged, untracked = [], [], []
    for line in raw.split("\n"):
        if not line:
            continue
        index_status = line[0]
        work_status = line[1]
        filepath = line[3:]

        if index_status == "?":
            untracked.append(filepath)
        elif index_status != " ":
            staged.append(GitFileStatus(path=filepath, status=index_status))
        if work_status not in (" ", "?"):
            modified.append(GitFileStatus(path=filepath, status=work_status))

    return GitStatus(
        branch=branch,
        modified=modified,
        staged=staged,
        untracked=untracked,
        counts={
            "modified": len(modified),
            "staged": len(staged),
            "untracked": len(untracked),
        },
    )


async def git_diff(project_dir: str, file: str | None = None) -> str:
    """Get unified diff output."""
    args = ["diff"]
    if file:
        args.extend(["--", file])
    return await _run_git(project_dir, *args)


async def git_branches(project_dir: str) -> list[GitBranch]:
    """List all branches with current marked."""
    raw = await _run_git(project_dir, "branch", "--format=%(refname:short)|%(HEAD)")
    branches = []
    for line in raw.split("\n"):
        if not line or "|" not in line:
            continue
        name, head = line.split("|", 1)
        branches.append(GitBranch(name=name.strip(), is_current=head.strip() == "*"))
    return branches


async def git_log(project_dir: str, n: int = 10) -> list[GitLogEntry]:
    """Get recent commit log."""
    fmt = "%H|%s|%an|%ci"
    raw = await _run_git(project_dir, "log", f"-{n}", f"--format={fmt}")
    entries = []
    for line in raw.split("\n"):
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            entries.append(
                GitLogEntry(
                    hash=parts[0], message=parts[1], author=parts[2], date=parts[3]
                )
            )
    return entries
