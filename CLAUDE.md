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

The server manages Claude Code as subprocesses using `-p <prompt> --output-format stream-json --verbose`, spawning one process per turn with `--resume` for conversation continuity. It exposes REST endpoints for CRUD operations, WebSocket for live streaming, Tailscale WhoIs auth, and Expo push notifications.

## Setup

### 1. Check prerequisites

```bash
tailscale ip -4         # Tailscale running and connected?
claude --version        # Claude Code CLI installed?
pip install -e ".[dev]" # Install package with dev dependencies
ccr doctor              # Verify all prerequisites
```

### 2. Install the approval hook

```bash
ccr install             # Registers PreToolUse hook in ~/.claude/settings.json
```

### 3. Start the server

```bash
ccr start               # Foreground, binds to Tailscale IP
ccr start -d            # Background daemon mode
ccr start --no-auth     # Local dev mode (127.0.0.1, no Tailscale auth)
```

## Important Notes

- **Tailscale-only binding:** Server binds to Tailscale IP by default. Use `--no-auth` for local development.
- **Environment vars:** The server unsets `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_ENTRY_VERSION`, `CLAUDE_CODE_ENV_VERSION` before spawning Claude Code subprocesses. It sets `CCR_SESSION_ID` and `CCR_API_URL` for the approval hook and statusline forwarding.
- **Session persistence:** Sessions are persisted to `~/.local/state/claude-code-remote/sessions/` as JSON files.
- **Per-turn subprocess:** Each prompt spawns a new `claude -p` process. The `--resume <session_id>` flag carries conversation context between turns. Do NOT use `--input-format stream-json` — it does not work with `-p` mode (process hangs).
- **Approval hook:** The PreToolUse hook (`ccr_approval.py`) auto-approves safe read-only tools (Read, Glob, Grep, etc.) and routes dangerous tools (Write, Edit, Bash) to the mobile app for approval. When `skip_permissions` is enabled, all tools are auto-approved.
- **Statusline forwarding:** If `~/.claude/statusline-command.sh` detects `CCR_SESSION_ID` and `CCR_API_URL` env vars, it POSTs model name, context %, and git branch to the server. The server also extracts this data directly from stream-json events (assistant event `message.model`, result event `modelUsage`).

## CLI Commands

- `ccr start` -- Start the API server
- `ccr stop` -- Stop the API server
- `ccr status` -- Show server status
- `ccr doctor` -- Check prerequisites
- `ccr install` -- Install the CCR approval hook into Claude Code
- `ccr uninstall` -- Remove the CCR approval hook

## File Overview

| File | Purpose |
|------|---------|
| `src/claude_code_remote/cli.py` | Click CLI entry point -- `ccr` command, hook install/uninstall |
| `src/claude_code_remote/server.py` | FastAPI application factory |
| `src/claude_code_remote/server_main.py` | Entry point for daemon mode subprocess |
| `src/claude_code_remote/routes.py` | REST API routes (sessions, templates, projects, push, internal) |
| `src/claude_code_remote/websocket.py` | WebSocket endpoint for session streaming |
| `src/claude_code_remote/session_manager.py` | Core session lifecycle and Claude Code subprocess management |
| `src/claude_code_remote/models.py` | Pydantic data models |
| `src/claude_code_remote/auth.py` | Tailscale WhoIs authentication middleware |
| `src/claude_code_remote/config.py` | Configuration and state directory paths |
| `src/claude_code_remote/tailscale.py` | Tailscale IP and MagicDNS resolution |
| `src/claude_code_remote/projects.py` | Project discovery and scanning |
| `src/claude_code_remote/templates.py` | Template CRUD persistence |
| `src/claude_code_remote/push.py` | Expo Push API notifications |
| `src/claude_code_remote/hooks/ccr_approval.py` | PreToolUse hook script for tool approval routing |
| `pyproject.toml` | Package configuration |

## API Endpoints

- `GET /api/status` -- Server health
- `GET/POST /api/sessions` -- List/create sessions
- `GET/DELETE /api/sessions/{id}` -- Get/delete session
- `POST /api/sessions/{id}/send` -- Send prompt
- `POST /api/sessions/{id}/approve` -- Approve tool use
- `POST /api/sessions/{id}/deny` -- Deny tool use
- `POST /api/sessions/{id}/pause` -- Pause session
- `POST /api/sessions/{id}/resume` -- Resume paused session
- `POST /api/sessions/{id}/archive` -- Archive session
- `POST /api/sessions/{id}/unarchive` -- Unarchive session
- `GET/POST /api/templates` -- List/create templates
- `PUT/DELETE /api/templates/{id}` -- Update/delete template
- `GET /api/projects` -- Scan for projects
- `POST /api/projects` -- Register a project directory
- `POST /api/push/register` -- Register push token
- `GET/PUT /api/push/settings` -- Push notification settings
- `POST /api/internal/approval-request` -- Hook: request tool approval (blocks until user decides)
- `POST /api/internal/statusline` -- Hook: receive statusline data (model, context %, git branch)
- `WS /ws/sessions/{id}` -- Live session stream

## Session Lifecycle

```
CREATED → (send_prompt) → RUNNING [process spawned]
RUNNING → (result event) → IDLE [process exited, ready for next prompt]
IDLE → (send_prompt) → RUNNING [new process with --resume]
RUNNING → (approval needed) → AWAITING_APPROVAL → (approved/denied) → RUNNING
RUNNING → (pause) → PAUSED → (resume with prompt) → RUNNING
RUNNING → (process error) → ERROR → (send_prompt) → RUNNING [retry with --resume]
```

## Session Model Fields

Key fields tracked per session:
- `claude_session_id` -- Claude Code's internal session ID (used for `--resume`)
- `current_model` -- Model name from the last assistant event (e.g., `claude-opus-4-6`)
- `context_percent` -- Estimated context window usage from modelUsage token counts
- `git_branch` -- Current git branch of the project directory
- `total_cost_usd` -- Cumulative API cost from result events
- `skip_permissions` -- Whether tool approvals are bypassed
- `use_sandbox` -- Whether to run in sandboxed mode
