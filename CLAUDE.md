# Claude Code Remote

## What This Is

This repo is a pip-installable Python package (`ccr` CLI) for remote access to Claude Code CLI from a phone (or any device) over a Tailscale VPN connection. The user has cloned this repo and wants help getting it running on their Mac.

## Architecture

```
iPhone (Browser) → Tailscale VPN → Mac → tmux → Claude Code
                                    |
                              ┌─────┴─────┐
                              Port 8080    Port 7681
                              Voice UI     Raw Terminal
```

## Helping the User Set Up

When the user asks for help installing or setting up this project, walk them through these steps in order. **Verify each step before moving to the next.**

### 1. Check prerequisites

Run these checks and report what's missing:

```bash
brew --version          # Homebrew installed?
ttyd --version          # ttyd installed?
tmux -V                 # tmux installed?
python3 -c "import fastapi; import uvicorn; print('ok')"  # Python packages?
tailscale ip -4         # Tailscale running and connected?
claude --version        # Claude Code CLI installed?
```

Install anything missing:
- `brew install ttyd tmux` for ttyd and tmux
- `pip install -e .` to install the `ccr` CLI and all Python dependencies
- Run `ccr doctor` to verify all prerequisites are met
- Tailscale and Claude Code CLI must be installed manually by the user

### 2. Verify Tailscale

- Confirm `tailscale ip -4` returns an IP (like `100.x.y.z`)
- Remind the user to install Tailscale on their phone too and sign in with the same account

### 3. Test the setup

- Run `ccr start` and verify it starts without errors
- Confirm the output shows the Tailscale IP and both port URLs
- Tell the user to open the Voice UI URL on their phone

### 4. Set up auto-start (if the user wants it)

- Run `ccr menubar` to launch the menu bar app
- Click "Auto-start on Login" in the menu to install a launchd agent automatically

## Important Gotchas

- **tmux env vars:** The `ccr` CLI unsets Claude Code environment variables before creating the tmux session. This prevents conflicts when Claude Code tries to launch inside an existing Claude Code session.
- **ttyd forks:** ttyd forks internally, so `ccr` uses port-based health checks and `lsof` to track the real process. PID files alone aren't reliable for ttyd.
- **ttyd auth:** The `--credential` flag for ttyd basic auth is not currently enabled. It was causing connection failures. Tailscale network-level security is the primary access control.
- **Apple Silicon vs Intel:** The tmux and tailscale modules use `shutil.which()` to auto-detect binary paths, with fallbacks for both architectures.
- **Services bind to Tailscale IP only.** If Tailscale isn't running, `ccr start` will fail. This is intentional — never bind to `0.0.0.0`.
- **macOS Cocoa and fork():** The menubar daemon uses `subprocess.Popen` instead of `os.fork()` because macOS AppKit crashes in forked processes.

## File Overview

| File | Purpose |
|------|---------|
| `src/claude_code_remote/cli.py` | Click CLI entry point — `ccr` command with start/stop/status/doctor/menubar subcommands |
| `src/claude_code_remote/config.py` | Configuration loading/saving with XDG-compliant paths |
| `src/claude_code_remote/tailscale.py` | Tailscale IP and MagicDNS resolution |
| `src/claude_code_remote/tmux.py` | tmux session management — replaces tmux-attach.sh |
| `src/claude_code_remote/voice.py` | FastAPI voice wrapper with mobile-optimized UI |
| `src/claude_code_remote/voice_server.py` | Entry point for running voice wrapper as subprocess |
| `src/claude_code_remote/services.py` | Service lifecycle — start, stop, status, watchdog |
| `src/claude_code_remote/menubar.py` | macOS menu bar app (rumps) |
| `pyproject.toml` | Package configuration with pip install support |

Legacy scripts (replaced by `ccr` CLI):

| File | Purpose |
|------|---------|
| `scripts/start-remote-cli.sh` | Starts ttyd, voice wrapper, and caffeinate. Includes watchdog for auto-restart. |
| `scripts/stop-remote-cli.sh` | Stops all services. Preserves the tmux session. |
| `scripts/tmux-attach.sh` | Wrapper that clears env vars and attaches to (or creates) the tmux session. |
| `scripts/voice-wrapper.py` | FastAPI app serving the mobile-optimized UI with dictation support. |
| `scripts/remote-cli.plist` | launchd plist for auto-start on boot. Requires `YOUR_USERNAME` replacement. |
| `scripts/menubar.py` | macOS menu bar app wrapping start/stop scripts. Provides status, URLs, logs, auto-start. Launch in background with `nohup python3 scripts/menubar.py &>/dev/null &`. |
