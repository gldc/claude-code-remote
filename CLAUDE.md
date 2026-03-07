# Claude Code Remote

## What This Is

This repo is a pip-installable Python package (`ccr` CLI) that provides a FastAPI server for managing Claude Code sessions remotely from a phone (or any device) over a Tailscale VPN connection. A companion Expo app connects to this server.

## Architecture

```
Expo App (Phone) --> Tailscale VPN --> Mac --> FastAPI Server --> Claude Code CLI
                                               |
                                          Port 8080
                                       REST + WebSocket API
```

The server manages Claude Code as subprocesses using `--output-format stream-json`, exposes REST endpoints for CRUD operations, WebSocket for live streaming, Tailscale WhoIs auth, and Expo push notifications.

## Setup

### 1. Check prerequisites

```bash
tailscale ip -4         # Tailscale running and connected?
claude --version        # Claude Code CLI installed?
pip install -e ".[dev]" # Install package with dev dependencies
ccr doctor              # Verify all prerequisites
```

### 2. Start the server

```bash
ccr start               # Foreground, binds to Tailscale IP
ccr start -d            # Background daemon mode
ccr start --no-auth     # Local dev mode (127.0.0.1, no Tailscale auth)
```

### 3. CLI Commands

- `ccr start` -- Start the API server
- `ccr stop` -- Stop the API server
- `ccr status` -- Show server status
- `ccr doctor` -- Check prerequisites

## Important Notes

- **Tailscale-only binding:** Server binds to Tailscale IP by default. Use `--no-auth` for local development.
- **Environment vars:** The server unsets `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_ENTRY_VERSION`, `CLAUDE_CODE_ENV_VERSION` before spawning Claude Code subprocesses.
- **Session persistence:** Sessions are persisted to `~/.local/state/claude-code-remote/sessions/` as JSON files.

## File Overview

| File | Purpose |
|------|---------|
| `src/claude_code_remote/cli.py` | Click CLI entry point -- `ccr` command |
| `src/claude_code_remote/server.py` | FastAPI application factory |
| `src/claude_code_remote/server_main.py` | Entry point for daemon mode subprocess |
| `src/claude_code_remote/routes.py` | REST API routes (sessions, templates, projects, push) |
| `src/claude_code_remote/websocket.py` | WebSocket endpoint for session streaming |
| `src/claude_code_remote/session_manager.py` | Core session lifecycle and Claude Code subprocess management |
| `src/claude_code_remote/models.py` | Pydantic data models |
| `src/claude_code_remote/auth.py` | Tailscale WhoIs authentication middleware |
| `src/claude_code_remote/config.py` | Configuration and state directory paths |
| `src/claude_code_remote/tailscale.py` | Tailscale IP and MagicDNS resolution |
| `src/claude_code_remote/projects.py` | Project discovery and scanning |
| `src/claude_code_remote/templates.py` | Template CRUD persistence |
| `src/claude_code_remote/push.py` | Expo Push API notifications |
| `pyproject.toml` | Package configuration |

## API Endpoints

- `GET /api/status` -- Server health
- `GET/POST /api/sessions` -- List/create sessions
- `GET/DELETE /api/sessions/{id}` -- Get/delete session
- `POST /api/sessions/{id}/send` -- Send prompt
- `POST /api/sessions/{id}/approve` -- Approve tool use
- `POST /api/sessions/{id}/deny` -- Deny tool use
- `POST /api/sessions/{id}/pause` -- Pause session
- `GET/POST /api/templates` -- List/create templates
- `PUT/DELETE /api/templates/{id}` -- Update/delete template
- `GET /api/projects` -- Scan for projects
- `POST /api/push/register` -- Register push token
- `GET/PUT /api/push/settings` -- Push notification settings
- `WS /ws/sessions/{id}` -- Live session stream
