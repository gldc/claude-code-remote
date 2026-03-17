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
- **SSH for unattended git:** If the server host uses 1Password SSH agent, git operations in Claude Code sessions will hang waiting for interactive approval. A dedicated local SSH key (`~/.ssh/id_ed25519_local`) with `IdentityAgent none` for `Host github.com` in `~/.ssh/config` bypasses this. See the README for setup.
- **Statusline forwarding:** If `~/.claude/statusline-command.sh` detects `CCR_SESSION_ID` and `CCR_API_URL` env vars, it POSTs model name, context %, and git branch to the server. The server also extracts this data directly from stream-json events (assistant event `message.model`, result event `modelUsage`).
- **Cron jobs:** APScheduler-based cron scheduling with SPAWN (new session per run) and PERSISTENT (reuse session) modes. Jobs persist to `~/.local/state/claude-code-remote/cron/`, history to `cron_history.jsonl`. Prompts support template variables (`{{date}}`, `{{branch}}`, etc.).
- **Dashboard:** A React SPA at `/dashboard/` shows unified CCR + native Claude Code sessions, analytics, and cron management. Native sessions are discovered from `~/.claude/projects/` and `~/.claude/sessions/` with model-specific cost estimation.
- **File uploads:** `POST /api/sessions/{id}/upload` saves files to `claude-uploads/` in the project root with filename sanitization and automatic `.gitignore` management.
- **Orphan process cleanup:** `ccr stop` and `ccr start` detect orphaned server processes via `lsof` and offer SIGTERM → SIGKILL escalation.
- **Menubar:** Shows MagicDNS hostname, live session list with status badges (● running, ◉ awaiting approval, ○ down), and an "Open Dashboard" button.
- **Native event format:** The server passes Claude Code's stream-json events through to clients without translation. Messages stored in `session.messages` use the native format (`assistant`, `tool_result`, `user`, `result`). The only CCR-specific event type is `approval_request`. Old WSMessage-format sessions are migrated on load.
- **Native session interop:** The `/api/sessions` endpoints merge native Claude Code sessions (from `~/.claude/projects/`) with CCR sessions. Native sessions from the last 7 days appear automatically (configurable via `native_max_age_days` in config). Users can hide/unhide native sessions non-destructively. Sending a message to a native session "adopts" it as a CCR session. Active native processes (checked via PID) block concurrent access from the app.

## CLI Commands

- `ccr start` -- Start the API server (add `--menubar` for menubar indicator)
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
| `src/claude_code_remote/terminal.py` | Interactive PTY terminal via WebSocket |
| `src/claude_code_remote/menubar.py` | macOS menubar status indicator (rumps) |
| `src/claude_code_remote/session_manager.py` | Core session lifecycle and Claude Code subprocess management |
| `src/claude_code_remote/models.py` | Pydantic data models |
| `src/claude_code_remote/auth.py` | Tailscale WhoIs authentication middleware |
| `src/claude_code_remote/config.py` | Configuration and state directory paths |
| `src/claude_code_remote/tailscale.py` | Tailscale IP and MagicDNS resolution |
| `src/claude_code_remote/projects.py` | Project discovery and scanning |
| `src/claude_code_remote/project_store.py` | JSON persistence for created/cloned projects |
| `src/claude_code_remote/templates.py` | Template CRUD persistence |
| `src/claude_code_remote/push.py` | Expo Push API notifications |
| `src/claude_code_remote/git.py` | Git operations (status, branches, log, diff) for project directories |
| `src/claude_code_remote/git_check.py` | Git and SSH setup verification for project creation |
| `src/claude_code_remote/approval_rules.py` | Auto-approval rule CRUD and pattern matching |
| `src/claude_code_remote/mcp.py` | MCP server discovery and health checks |
| `src/claude_code_remote/usage.py` | Claude API usage tracking and rate limit parsing |
| `src/claude_code_remote/workflows.py` | Workflow engine -- multi-step session orchestration with DAG execution |
| `src/claude_code_remote/cron_manager.py` | Cron job scheduling with APScheduler, persistence, template substitution |
| `src/claude_code_remote/dashboard.py` | Dashboard API routes -- unified session views, analytics, cron management |
| `src/claude_code_remote/native_sessions.py` | Native Claude Code session discovery from `~/.claude/` with cost estimation |
| `src/claude_code_remote/uploads.py` | File upload utilities -- sanitization, storage, gitignore management |
| `src/claude_code_remote/hidden_sessions.py` | Non-destructive hidden sessions store for native session visibility |
| `src/claude_code_remote/dashboard/` | React + TypeScript + Vite dashboard SPA (session list, detail, cron views) |
| `src/claude_code_remote/hooks/ccr_approval.py` | PreToolUse hook script for tool approval routing |
| `pyproject.toml` | Package configuration |

## API Endpoints

- `GET /api/status` -- Server health
- `GET/POST /api/sessions` -- List/create sessions
- `GET/DELETE/PATCH /api/sessions/{id}` -- Get/delete/update (rename) session
- `POST /api/sessions/{id}/send` -- Send prompt
- `POST /api/sessions/{id}/approve` -- Approve tool use
- `POST /api/sessions/{id}/deny` -- Deny tool use
- `POST /api/sessions/{id}/pause` -- Pause session
- `POST /api/sessions/{id}/resume` -- Resume paused session
- `POST /api/sessions/{id}/archive` -- Archive session
- `POST /api/sessions/{id}/unarchive` -- Unarchive session
- `GET/POST /api/templates` -- List/create templates
- `PUT/DELETE /api/templates/{id}` -- Update/delete template
- `GET /api/projects` -- List projects (scanned + stored)
- `POST /api/projects` -- Register a project directory
- `POST /api/projects/create` -- Create blank project (git init)
- `POST /api/projects/clone` -- Clone a git repo (background)
- `GET /api/projects/git-check` -- Check git/SSH setup
- `GET /api/sessions/search` -- Full-text search across sessions
- `GET /api/sessions/{id}/export` -- Export session data
- `GET /api/sessions/{id}/git/status` -- Git status for session project
- `GET /api/sessions/{id}/git/diff` -- Git diff for session project
- `GET /api/sessions/{id}/git/branches` -- Git branches for session project
- `GET /api/sessions/{id}/git/log` -- Git log for session project
- `POST/DELETE /api/sessions/{id}/collaborators` -- Add/remove collaborators
- `POST /api/push/register` -- Register push token
- `GET/PUT /api/push/settings` -- Push notification settings
- `GET/POST /api/approval-rules` -- List/create auto-approval rules
- `DELETE /api/approval-rules/{id}` -- Delete approval rule
- `GET /api/approval-rules/check` -- Check if tool is auto-approved
- `GET/POST/DELETE /api/mcp/servers` -- List/add/remove MCP servers
- `GET /api/mcp/servers/{name}/health` -- MCP server health check
- `GET /api/usage` -- Claude API usage data
- `GET /api/usage/history` -- Usage history over time
- `GET /api/skills` -- List available skills
- `GET/POST /api/workflows` -- List/create workflows
- `GET/DELETE /api/workflows/{id}` -- Get/delete workflow
- `POST /api/workflows/{id}/run` -- Run a workflow
- `POST /api/workflows/{id}/steps` -- Add step to workflow
- `POST /api/sessions/{id}/upload` -- Upload file attachments to a session
- `POST /api/sessions/{id}/hide` -- Hide native session (add `?permanent=true` for permanent)
- `POST /api/sessions/{id}/unhide` -- Unhide a hidden native session
- `GET/POST /api/cron-jobs` -- List/create cron jobs
- `GET/PATCH/DELETE /api/cron-jobs/{id}` -- Get/update/delete cron job
- `POST /api/cron-jobs/{id}/toggle` -- Enable/disable cron job
- `POST /api/cron-jobs/{id}/trigger` -- Manually trigger cron job
- `GET /api/cron-jobs/{id}/history` -- Cron job run history
- `GET /api/dashboard/sessions` -- Unified CCR + native session list (paginated, searchable)
- `GET /api/dashboard/sessions/{id}` -- Full session detail with paginated messages
- `POST /api/dashboard/sessions/{id}/resume` -- Resume native session as new CCR session
- `GET /api/dashboard/analytics` -- Dashboard summary stats
- `GET /api/dashboard/cron-jobs` -- Cron jobs with recent run history
- `POST /api/internal/approval-request` -- Hook: request tool approval (blocks until user decides)
- `POST /api/internal/statusline` -- Hook: receive statusline data (model, context %, git branch)
- `WS /ws/sessions/{id}` -- Live session stream
- `WS /ws/terminal/{project_id}` -- Interactive PTY terminal

## Session Lifecycle

```
CREATED → (send_prompt) → RUNNING [process spawned]
RUNNING → (result event) → IDLE [process exited, ready for next prompt]
RUNNING → (result event, final) → COMPLETED [session finished]
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
