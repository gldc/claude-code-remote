# Claude Code Remote

Manage Claude Code sessions from your phone -- or anywhere -- over a secure Tailscale VPN connection.

## What This Is

A Python package that runs a FastAPI server on your Mac, managing Claude Code CLI as subprocesses. A companion Expo app connects to this server over Tailscale, giving you full session management from your phone: create sessions, stream output live, approve tool use, and get push notifications.

```
Expo App (Phone) --> Tailscale VPN --> Mac --> FastAPI Server --> Claude Code CLI
                                               |
                                          Port 8080
                                       REST + WebSocket API
```

## Cost

| Tool | Cost |
|------|------|
| [Tailscale](https://tailscale.com/pricing) | Free for personal use |
| [FastAPI](https://fastapi.tiangolo.com) + [Uvicorn](https://www.uvicorn.org) | Free and open-source |
| Claude Code CLI | Any plan that includes Claude Code ([Max](https://www.anthropic.com/pricing), [Pro](https://www.anthropic.com/pricing), or [API](https://www.anthropic.com/pricing)) |

You can also run Claude Code with local models via [Ollama](https://ollama.com) for a fully free setup.

## Prerequisites

- macOS (Apple Silicon or Intel)
- Python 3.10+
- [Tailscale](https://tailscale.com) account + app installed on Mac and phone
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated

## Quick Start

### 1. Install

```bash
pip install -e ".[dev]"
ccr doctor
```

### 2. Set up Tailscale

Install Tailscale on your Mac and phone, sign in with the same account:

```bash
tailscale ip -4   # Should print your Mac's Tailscale IP (100.x.y.z)
```

### 3. Install the approval hook

```bash
ccr install   # Registers PreToolUse hook in ~/.claude/settings.json
```

### 4. Start the server

```bash
ccr start         # Foreground mode, binds to Tailscale IP
ccr start -d      # Daemon mode (background)
ccr start --no-auth  # Local dev mode (127.0.0.1, no auth)
```

The server starts on port 8080 by default. Open `http://<tailscale-ip>:8080/api/status` to verify.

### 5. Connect the Expo app

Install the companion Expo app on your phone and point it at your server's Tailscale address.

## CLI Commands

| Command | Description |
|---------|-------------|
| `ccr start` | Start the API server |
| `ccr start -d` | Start in background (daemon mode) |
| `ccr start --no-auth` | Start without Tailscale auth (local dev) |
| `ccr start --menubar` | Start with macOS menubar status indicator |
| `ccr stop` | Stop the API server |
| `ccr status` | Show server and Tailscale status |
| `ccr doctor` | Check all prerequisites |
| `ccr install` | Install the CCR approval hook into Claude Code |
| `ccr uninstall` | Remove the CCR approval hook |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Server health check |
| `/api/sessions` | GET, POST | List or create sessions |
| `/api/sessions/search` | GET | Full-text search across sessions |
| `/api/sessions/{id}` | GET, DELETE, PATCH | Get, delete, or update (rename) a session |
| `/api/sessions/{id}/export` | GET | Export session data |
| `/api/sessions/{id}/send` | POST | Send a prompt to a session |
| `/api/sessions/{id}/approve` | POST | Approve tool use |
| `/api/sessions/{id}/deny` | POST | Deny tool use |
| `/api/sessions/{id}/pause` | POST | Pause a session |
| `/api/sessions/{id}/resume` | POST | Resume a paused session |
| `/api/sessions/{id}/archive` | POST | Archive a session |
| `/api/sessions/{id}/unarchive` | POST | Unarchive a session |
| `/api/sessions/{id}/git/status` | GET | Git status for session project |
| `/api/sessions/{id}/git/diff` | GET | Git diff for session project |
| `/api/sessions/{id}/git/branches` | GET | Git branches for session project |
| `/api/sessions/{id}/git/log` | GET | Git log for session project |
| `/api/sessions/{id}/collaborators` | POST, DELETE | Add or remove collaborators |
| `/api/templates` | GET, POST | List or create templates |
| `/api/templates/{id}` | PUT, DELETE | Update or delete a template |
| `/api/projects` | GET, POST | Scan for or register projects |
| `/api/projects/create` | POST | Create blank project (git init) |
| `/api/projects/clone` | POST | Clone a git repo (background) |
| `/api/projects/git-check` | GET | Check git/SSH setup |
| `/api/push/register` | POST | Register Expo push token |
| `/api/push/settings` | GET, PUT | Manage push settings |
| `/api/approval-rules` | GET, POST | List or create auto-approval rules |
| `/api/approval-rules/{id}` | DELETE | Delete an approval rule |
| `/api/approval-rules/check` | GET | Check if tool is auto-approved |
| `/api/mcp/servers` | GET, POST, DELETE | List, add, or remove MCP servers |
| `/api/mcp/servers/{name}/health` | GET | MCP server health check |
| `/api/usage` | GET | Claude API usage data |
| `/api/usage/history` | GET | Usage history over time |
| `/api/skills` | GET | List available skills |
| `/api/workflows` | GET, POST | List or create workflows |
| `/api/workflows/{id}` | GET, DELETE | Get or delete a workflow |
| `/api/workflows/{id}/run` | POST | Run a workflow |
| `/api/workflows/{id}/steps` | POST | Add step to a workflow |
| `/api/internal/approval-request` | POST | Hook: request tool approval |
| `/api/internal/statusline` | POST | Hook: receive statusline data |
| `/ws/sessions/{id}` | WS | Live session event stream |
| `/ws/terminal/{project_id}` | WS | Interactive PTY terminal |

## Tool Approval

The server includes a PreToolUse hook that routes Claude Code's tool calls to your phone for approval:

```bash
ccr install    # Register the hook in ~/.claude/settings.json
ccr uninstall  # Remove the hook
```

- **Safe tools** (Read, Glob, Grep, etc.) are auto-approved
- **Dangerous tools** (Write, Edit, Bash) are routed to the mobile app for approval/denial
- **Skip permissions mode** auto-approves everything (per-session toggle)

## Session Info

Each session tracks real-time metadata extracted from Claude Code's stream-json output:

- **Model** -- current model name (e.g., `claude-opus-4-6`)
- **Context %** -- estimated context window usage from token counts
- **Git branch** -- current branch of the project directory
- **Cost** -- cumulative API cost in USD

## Security

The server binds exclusively to the Tailscale interface IP and authenticates requests via `tailscale whois`. Nothing is exposed to the public internet or local network. Tailscale creates a peer-to-peer WireGuard encrypted tunnel between your devices.

## Configuration

Config file: `~/.config/claude-code-remote/config.json`

```json
{
  "port": 8080,
  "max_concurrent_sessions": 5,
  "scan_directories": ["~/Developer"]
}
```

## Recommended Server Setup

### SSH Keys for Unattended Use

If your SSH keys are managed by 1Password (or another agent that requires interactive approval), Claude Code sessions run via CCR will hang waiting for approval when git operations need SSH access. Set up a dedicated local key:

```bash
# Generate a passphrase-less key for unattended use
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_local -N "" -C "$(whoami)@ccr-local"

# Add to GitHub (requires gh CLI authenticated)
gh ssh-key add ~/.ssh/id_ed25519_local.pub --title "CCR local key"
```

Then add a `Host github.com` block in `~/.ssh/config` **above** the `Host *` catch-all:

```
Host github.com
    IdentityFile ~/.ssh/id_ed25519_local
    IdentityAgent none
    IdentitiesOnly yes

Host *
    IdentityAgent "~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock"
```

This ensures GitHub SSH uses the local key while everything else continues through 1Password.

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```
