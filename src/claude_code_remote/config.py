"""Configuration loading and saving."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "claude-code-remote"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DIR = Path.home() / ".local" / "state" / "claude-code-remote"
LOG_DIR = STATE_DIR / "logs"
PID_DIR = STATE_DIR / "pids"
SESSION_DIR = STATE_DIR / "sessions"
TEMPLATE_DIR = STATE_DIR / "templates"
PUSH_FILE = STATE_DIR / "push.json"
PROJECTS_FILE = STATE_DIR / "projects.json"

DEFAULT_CONFIG = {
    "port": 8080,
    "max_concurrent_sessions": 5,
    "scan_directories": ["~/Developer"],
    "session_idle_timeout_minutes": None,
}


def ensure_dirs() -> None:
    for d in [LOG_DIR, PID_DIR, SESSION_DIR, TEMPLATE_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    try:
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
