# CLI Packaging Design

**Date:** 2026-02-19
**Goal:** Turn claude-code-remote into a pip-installable CLI tool (`pip install -e .`) with a single `ccr` command.

## CLI Commands

```
ccr start [-d]     # Start all services. -d to daemonize.
ccr stop           # Stop all services, preserve tmux session.
ccr status         # Show service health.
ccr doctor         # Check system deps and guide install.
ccr menubar [-d]   # Launch menu bar app. -d to daemonize.
```

## Package Structure

```
claude-code-remote/
├── pyproject.toml
├── src/
│   └── claude_code_remote/
│       ├── __init__.py
│       ├── cli.py          # Click CLI entry point
│       ├── services.py     # Start/stop ttyd, voice-wrapper, caffeinate
│       ├── tmux.py         # tmux session management
│       ├── tailscale.py    # Tailscale IP + MagicDNS helpers
│       ├── voice.py        # FastAPI voice wrapper app
│       ├── menubar.py      # rumps menu bar app
│       └── config.py       # Config loading/saving
├── README.md
└── CLAUDE.md
```

## Module Responsibilities

- **cli.py** — Click group with subcommands. Thin routing layer.
- **services.py** — Process lifecycle for ttyd, voice-wrapper, caffeinate. PID file management. Watchdog loop for ttyd auto-restart. Daemon mode via fork.
- **tmux.py** — Create/attach to `claude` tmux session. Unset Claude Code env vars.
- **tailscale.py** — Get Tailscale IP and MagicDNS name. Shared by services, menubar, CLI.
- **voice.py** — FastAPI app (from voice-wrapper.py). Run with uvicorn programmatically.
- **menubar.py** — rumps app (from menubar.py). Imports from tailscale.py and services.py.
- **config.py** — Load/save ~/.config/claude-code-remote/config.json.

## Dependencies

```toml
[project]
name = "claude-code-remote"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "click",
    "fastapi",
    "uvicorn",
    "rumps",
]

[project.scripts]
ccr = "claude_code_remote.cli:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

## System Dependencies (checked by `ccr doctor`)

- ttyd (brew install ttyd)
- tmux (brew install tmux)
- tailscale (standalone installer)
- claude CLI (standalone installer)

## State Directory

PID files and logs stored in `~/.local/state/claude-code-remote/` (XDG-compliant).

## Shell Script Migration

| Shell script | Python replacement | Approach |
|---|---|---|
| start-remote-cli.sh | services.py:start_all() | subprocess.Popen for ttyd/caffeinate, uvicorn.run() for voice-wrapper |
| stop-remote-cli.sh | services.py:stop_all() | Read PID files, os.kill(), cleanup |
| tmux-attach.sh | tmux.py:ensure_session() | subprocess.run for tmux commands, env var unsetting |
| PATH fix | Not needed | Python uses shutil.which() to resolve binaries |

## Daemon Mode

`ccr start -d` and `ccr menubar -d` fork a background process, write the daemon PID, and return immediately. `ccr stop` kills the daemon.

## Key Decisions

- Click for CLI framework (industry standard, clean subcommands)
- Hatchling build backend (simple, modern, no setup.py)
- Python 3.10+ minimum (match/case, modern typing)
- rumps included as core dependency (not optional)
- src/ layout (modern Python packaging standard)
