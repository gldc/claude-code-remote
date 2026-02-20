"""Configuration loading and saving."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "claude-code-remote"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DIR = Path.home() / ".local" / "state" / "claude-code-remote"
LOG_DIR = STATE_DIR / "logs"
PID_DIR = STATE_DIR / "pids"

DEFAULT_CONFIG = {
    "auto_start_services": False,
}


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PID_DIR.mkdir(parents=True, exist_ok=True)


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
