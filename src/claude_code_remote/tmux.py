"""tmux session management — replaces tmux-attach.sh."""

import os
import shutil
import subprocess

SESSION_NAME = "claude"
CLAUDE_ENV_VARS = [
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_ENTRY_VERSION",
    "CLAUDE_CODE_ENV_VERSION",
]


def _find_binary() -> str:
    return shutil.which("tmux") or "/opt/homebrew/bin/tmux"


def _clean_env() -> dict[str, str]:
    """Return a copy of os.environ without Claude env vars, with UTF-8 locale."""
    env = {k: v for k, v in os.environ.items() if k not in CLAUDE_ENV_VARS}
    env["LANG"] = "en_US.UTF-8"
    env["LC_ALL"] = "en_US.UTF-8"
    return env


def ensure_session() -> None:
    """Create the tmux session if it doesn't already exist."""
    tmux = _find_binary()
    result = subprocess.run(
        [tmux, "has-session", "-t", SESSION_NAME],
        capture_output=True, env=_clean_env(),
    )
    if result.returncode != 0:
        subprocess.run(
            [tmux, "new-session", "-d", "-s", SESSION_NAME, "-c", os.path.expanduser("~")],
            env=_clean_env(),
        )


def send_keys(keys: str, literal: bool = False) -> None:
    """Send keys to the tmux session."""
    tmux = _find_binary()
    cmd = [tmux, "send-keys", "-t", SESSION_NAME]
    if literal:
        cmd.append("-l")
    cmd.append(keys)
    subprocess.run(cmd, timeout=5, env=_clean_env())


def capture_pane() -> str:
    """Capture the full scrollback of the tmux pane."""
    tmux = _find_binary()
    result = subprocess.run(
        [tmux, "capture-pane", "-t", SESSION_NAME, "-p", "-S", "-"],
        capture_output=True, text=True, timeout=5, env=_clean_env(),
    )
    return result.stdout


def attach_exec() -> None:
    """Replace the current process with tmux attach (used by ttyd)."""
    tmux = _find_binary()
    env = _clean_env()
    os.execve(
        tmux,
        [tmux, "new-session", "-A", "-s", SESSION_NAME, "-c", os.path.expanduser("~")],
        env,
    )
