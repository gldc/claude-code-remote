# tests/test_config.py
from claude_code_remote.config import (
    STATE_DIR,
    SESSION_DIR,
    TEMPLATE_DIR,
    DEFAULT_CONFIG,
    load_config,
)


def test_default_config_has_new_keys():
    cfg = DEFAULT_CONFIG
    assert "port" in cfg
    assert cfg["port"] == 8080
    assert "max_concurrent_sessions" in cfg
    assert cfg["max_concurrent_sessions"] == 5
    assert "scan_directories" in cfg


def test_state_subdirs_exist():
    assert SESSION_DIR.name == "sessions"
    assert TEMPLATE_DIR.name == "templates"
