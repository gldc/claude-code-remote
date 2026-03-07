# Claude Code Remote — API Server Redesign

## Overview

Replace the existing tmux/ttyd/voice wrapper with a FastAPI server that manages Claude Code subprocesses via `stream-json`, exposes a REST + WebSocket API, authenticates via Tailscale WhoIs, and sends push notifications via Expo Push API.

## Architecture

```
Expo iOS App / Any Client
    | (Tailscale VPN)
    v
FastAPI Server (:8080)
├── REST API (/api/*)
├── WebSocket (/ws/sessions/{id})
├── Tailscale WhoIs auth middleware
├── Session Manager
│   └── Claude Code subprocesses (stream-json)
├── MCP Approval Tool (permission-prompt-tool)
├── Push Notification Module (Expo Push API)
├── Project Scanner
└── Session State (JSON files on disk)
```

## What Gets Removed

- `voice.py` / `voice_server.py` — replaced by API server
- `tmux.py` — no longer using tmux for session management
- `menubar.py` — can be updated later to wrap new server
- `scripts/` — already deprecated
- ttyd dependency — no longer needed
- caffeinate — keep, still useful

## Claude Code Subprocess Management

Each session spawns:
```bash
claude -p \
  --output-format stream-json \
  --input-format stream-json \
  --permission-prompt-tool mcp_approval_tool \
  --project-dir /path/to/project \
  --verbose \
  --no-session-persistence \
  "initial prompt here"
```

Additional per-session flags (from templates):
- `--model` — configurable model
- `--max-budget-usd` — optional spend cap
- `--allowedTools` — optional tool restrictions

### Process I/O

- **stdout**: Read line-by-line, parse as JSON events
- **stdin**: Write structured JSON to send follow-up prompts (input-format stream-json)
- **stderr**: Capture for error reporting

### Event Types (from stdout)

| Event Type | Subtype | Action |
|-----------|---------|--------|
| `system` | `init` | Store session metadata (tools, model, cwd) |
| `system` | `hook_*` | Ignore |
| `assistant` | — | Parse `content[]` for text and tool_use blocks, broadcast via WebSocket |
| `result` | `success`/`error` | Mark session complete, store cost/usage, send push notification |
| `rate_limit_event` | — | Broadcast rate limit warning |

## Session Lifecycle

```
Created → Running → Completed
                 ↘ Awaiting Approval → (approve/deny) → Running
                 ↘ Paused (Ctrl+C interrupt)
                 ↘ Error
```

### State Persistence

- Path: `~/.local/state/claude-code-remote/sessions/{id}.json`
- Contents: metadata, full message history, current status, cost
- Written on every state change (debounced)
- On server restart: load all session files, mark previously-running as `error`

## REST API

### Authentication Middleware

Every request: extract client IP → `tailscale whois <ip>` → verify node belongs to tailnet → 403 if not.

### Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/sessions` | List all sessions. Filters: `?status=running`, `?project_id=X` |
| `POST` | `/api/sessions` | Create session. Body: `{name, project_dir, initial_prompt, template_id}` |
| `GET` | `/api/sessions/{id}` | Session detail + full message history |
| `DELETE` | `/api/sessions/{id}` | Stop and remove session |
| `POST` | `/api/sessions/{id}/send` | Send a follow-up prompt |
| `POST` | `/api/sessions/{id}/approve` | Approve pending tool use |
| `POST` | `/api/sessions/{id}/deny` | Deny pending tool use. Body: `{reason?}` |
| `POST` | `/api/sessions/{id}/pause` | Send interrupt (Ctrl+C) |
| `POST` | `/api/sessions/{id}/resume` | Resume with new prompt |

### Templates

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/templates` | List templates |
| `POST` | `/api/templates` | Create template. Body: `{name, project_dir, initial_prompt, model, max_budget_usd, allowed_tools}` |
| `PUT` | `/api/templates/{id}` | Update template |
| `DELETE` | `/api/templates/{id}` | Delete template |

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/projects` | List projects (triggers scan if stale) |
| `POST` | `/api/projects` | Register project manually. Body: `{path}` |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | Server health, uptime, active session count |
| `POST` | `/api/push/register` | Register device push token. Body: `{expo_push_token}` |
| `GET` | `/api/push/settings` | Get notification preferences |
| `PUT` | `/api/push/settings` | Update notification preferences |

## WebSocket

### Endpoint: `ws/sessions/{id}`

Client connects to receive real-time events for a session.

**Server → Client message format:**
```json
{
  "type": "assistant_text" | "tool_use" | "tool_result" | "status_change" | "approval_request" | "error" | "rate_limit",
  "data": { ... },
  "timestamp": "ISO8601"
}
```

**Mapped from Claude Code stream-json events:**
- `assistant` with `content[].type == "text"` → `assistant_text`
- `assistant` with `content[].type == "tool_use"` → `tool_use`
- Tool result events → `tool_result`
- Permission prompt MCP calls → `approval_request`
- `result` → `status_change` (completed/error)

## MCP Approval Tool

A lightweight MCP server (stdio-based) that Claude Code calls when it needs permission to use a tool.

**How it works:**
1. Claude Code invokes the MCP tool with tool name, arguments, and context
2. MCP tool stores the approval request in the session manager
3. Session status set to `awaiting_approval`
4. WebSocket broadcasts `approval_request` event
5. Push notification sent
6. MCP tool blocks (async wait) until REST endpoint receives approve/deny
7. MCP tool returns approval/denial to Claude Code
8. Session continues

## Push Notifications

**Provider:** Expo Push API (free, no APNs certificates needed)

**Server sends:**
```python
httpx.post("https://exp.host/--/api/v2/push/send", json={
    "to": expo_push_token,
    "title": "Approval Needed",
    "body": "Session X wants to run: Edit foo.py",
    "data": {"session_id": "...", "type": "approval_request"}
})
```

**Events that trigger push:**
| Event | Title | Body |
|-------|-------|------|
| Approval requested | "Approval Needed" | "Session {name} wants to: {tool_name}" |
| Session completed | "Task Complete" | "Session {name} finished ($X.XX)" |
| Session error | "Session Error" | "Session {name}: {error_msg}" |

**Notification preferences** (configurable per device):
- Notify on approvals (default: on)
- Notify on completions (default: on)
- Notify on errors (default: on)

## Project Discovery

**Scan directories:** `~/Developer/*` + configurable additional paths

**Project detection** — directory contains any of:
- `.git/`
- `package.json`
- `pyproject.toml`
- `Cargo.toml`
- `go.mod`

**Project data model:**
```json
{
  "id": "hash-of-path",
  "name": "claude-code-remote",
  "path": "/Users/gldc/Developer/claude-code-remote",
  "type": "python",
  "last_session": "2026-03-07T...",
  "session_count": 3
}
```

Cached in server state, refreshed on `GET /api/projects`.

## Configuration

**Server config:** `~/.config/claude-code-remote/config.json`
```json
{
  "host": "tailscale",
  "port": 8080,
  "max_concurrent_sessions": 5,
  "scan_directories": ["~/Developer"],
  "session_idle_timeout_minutes": null
}
```

**State directories:**
- Sessions: `~/.local/state/claude-code-remote/sessions/`
- Templates: `~/.local/state/claude-code-remote/templates/`
- Projects: `~/.local/state/claude-code-remote/projects.json`
- Push tokens: `~/.local/state/claude-code-remote/push.json`
- Logs: `~/.local/state/claude-code-remote/logs/`
- PIDs: `~/.local/state/claude-code-remote/pids/`

## CLI Updates

The `ccr` CLI commands still work but manage the new server:

| Command | Behavior |
|---------|----------|
| `ccr start [-d]` | Start API server (+ caffeinate) |
| `ccr stop` | Stop API server (sessions are preserved on disk) |
| `ccr status` | Show server health, active sessions |
| `ccr doctor` | Check prerequisites (claude, tailscale, python deps) |

## Resource Limits

- Max concurrent sessions: configurable (default 5)
- Optional per-session budget cap via `--max-budget-usd`
- Session state disk usage: completed sessions can be pruned

## Security

- All endpoints authenticated via Tailscale WhoIs
- Server binds exclusively to Tailscale IP
- No public internet exposure
- Claude Code env vars unset before subprocess spawn
