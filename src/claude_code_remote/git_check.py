"""Git setup verification for project creation."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


async def check_git_setup() -> dict[str, bool]:
    """Check git and SSH configuration. Returns status dict."""
    result = {
        "git": shutil.which("git") is not None,
        "ssh_key": False,
        "github_ssh": False,
    }

    # Check for SSH keys
    ssh_dir = Path.home() / ".ssh"
    if ssh_dir.is_dir():
        key_files = [
            f
            for f in ssh_dir.iterdir()
            if f.is_file() and f.name.startswith("id_") and not f.suffix == ".pub"
        ]
        result["ssh_key"] = len(key_files) > 0

    # Check GitHub SSH access
    if result["ssh_key"]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh",
                "-T",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-o",
                "ConnectTimeout=5",
                "git@github.com",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            # GitHub returns exit code 1 with "Hi <user>!" on success
            result["github_ssh"] = proc.returncode == 1 and b"Hi " in stderr
        except Exception:
            result["github_ssh"] = False

    return result


def check_git_setup_sync() -> dict[str, bool]:
    """Synchronous wrapper for CLI usage."""
    return asyncio.run(check_git_setup())
