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
| Claude Code CLI | Requires an [Anthropic API plan](https://www.anthropic.com/pricing) (usage-based) |

The only ongoing cost is your Claude Code API usage.

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

### 3. Start the server

```bash
ccr start         # Foreground mode, binds to Tailscale IP
ccr start -d      # Daemon mode (background)
ccr start --no-auth  # Local dev mode (127.0.0.1, no auth)
```

The server starts on port 8080 by default. Open `http://<tailscale-ip>:8080/api/status` to verify.

### 4. Connect the Expo app

Install the companion Expo app on your phone and point it at your server's Tailscale address.

## CLI Commands

| Command | Description |
|---------|-------------|
| `ccr start` | Start the API server |
| `ccr start -d` | Start in background (daemon mode) |
| `ccr start --no-auth` | Start without Tailscale auth (local dev) |
| `ccr stop` | Stop the API server |
| `ccr status` | Show server and Tailscale status |
| `ccr doctor` | Check all prerequisites |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Server health check |
| `/api/sessions` | GET, POST | List or create sessions |
| `/api/sessions/{id}` | GET, DELETE | Get or delete a session |
| `/api/sessions/{id}/send` | POST | Send a prompt to a session |
| `/api/sessions/{id}/approve` | POST | Approve tool use |
| `/api/sessions/{id}/deny` | POST | Deny tool use |
| `/api/sessions/{id}/pause` | POST | Pause a session |
| `/api/templates` | GET, POST | List or create templates |
| `/api/templates/{id}` | PUT, DELETE | Update or delete a template |
| `/api/projects` | GET | Scan for projects |
| `/api/push/register` | POST | Register Expo push token |
| `/api/push/settings` | GET, PUT | Manage push settings |
| `/ws/sessions/{id}` | WS | Live session event stream |

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

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```
