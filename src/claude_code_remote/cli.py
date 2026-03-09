"""CLI entry point -- the `ccr` command."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click

from claude_code_remote import __version__


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__, prog_name="ccr")
def cli():
    """Claude Code Remote -- manage Claude Code sessions from any device over Tailscale."""


@cli.command()
@click.option("-d", "--daemon", is_flag=True, help="Run in background.")
@click.option("--no-auth", is_flag=True, help="Disable Tailscale auth (for local dev).")
def start(daemon, no_auth):
    """Start the API server."""
    from claude_code_remote import tailscale
    from claude_code_remote.config import load_config, PID_DIR, LOG_DIR, ensure_dirs

    ensure_dirs()
    config = load_config()
    port = config.get("port", 8080)

    if no_auth:
        host = "127.0.0.1"
        click.echo(f"Starting server on {host}:{port} (auth disabled)")
    else:
        host = tailscale.require_ip()
        click.echo(f"Starting server on {host}:{port}")

    if daemon:
        log_file = LOG_DIR / "server.log"
        pid_file = PID_DIR / "server.pid"
        with open(log_file, "a") as log:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "claude_code_remote.server_main",
                    "--host",
                    host,
                    "--port",
                    str(port),
                ]
                + (["--no-auth"] if no_auth else []),
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            pid_file.write_text(str(proc.pid))
        click.echo(f"Server running in background (PID {proc.pid})")
        click.echo(f"  API: http://{host}:{port}/api/status")
        click.echo(f"  Log: {log_file}")

        # Start caffeinate
        try:
            caf = subprocess.Popen(
                ["caffeinate", "-di", "-w", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            (PID_DIR / "caffeinate.pid").write_text(str(caf.pid))
        except FileNotFoundError:
            pass
    else:
        from claude_code_remote.server import run_server

        run_server(host=host, port=port, skip_auth=no_auth)


@cli.command()
def stop():
    """Stop the API server."""
    from claude_code_remote.config import PID_DIR
    import signal
    import os

    for name in ["server", "caffeinate"]:
        pid_file = PID_DIR / f"{name}.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                click.echo(f"Stopped {name} (PID {pid})")
            except (ProcessLookupError, ValueError):
                click.echo(f"{name} was not running")
            pid_file.unlink(missing_ok=True)
        else:
            click.echo(f"{name} is not running")


@cli.command()
def status():
    """Show server status."""
    from claude_code_remote import tailscale
    from claude_code_remote.config import PID_DIR, load_config
    import os

    ip = tailscale.get_ip()
    dns = tailscale.get_dns_name()
    host = dns or ip
    config = load_config()
    port = config.get("port", 8080)

    click.echo(f"Tailscale IP:  {ip or 'Not connected'}")
    click.echo(f"MagicDNS:      {dns or 'Not available'}")
    click.echo()

    pid_file = PID_DIR / "server.pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            click.echo(click.style("  ● ", fg="green") + f"server (PID {pid})")
            if host:
                click.echo(f"  API: http://{host}:{port}/api/status")
        except (ProcessLookupError, ValueError):
            click.echo(click.style("  ○ ", fg="red") + "server (stale PID)")
    else:
        click.echo(click.style("  ○ ", fg="red") + "server")


@cli.command()
def doctor():
    """Check prerequisites and dependencies."""
    checks = [
        ("tailscale", "Install from https://tailscale.com"),
        ("claude", "npm install -g @anthropic-ai/claude-code"),
    ]
    all_ok = True
    for binary, hint in checks:
        found = shutil.which(binary)
        if found:
            click.echo(click.style("  ✓ ", fg="green") + f"{binary} ({found})")
        else:
            click.echo(click.style("  ✗ ", fg="red") + f"{binary} — {hint}")
            all_ok = False

    packages = ["fastapi", "uvicorn", "httpx", "pydantic", "click"]
    for pkg in packages:
        try:
            __import__(pkg)
            click.echo(click.style("  ✓ ", fg="green") + f"{pkg}")
        except ImportError:
            click.echo(click.style("  ✗ ", fg="red") + f"{pkg} — pip install {pkg}")
            all_ok = False

    # Git setup checks
    click.echo()
    click.echo("Git Setup")
    from claude_code_remote.git_check import check_git_setup_sync

    git_info = check_git_setup_sync()

    if git_info["git"]:
        click.echo(click.style("  ✓ ", fg="green") + f"git ({shutil.which('git')})")
    else:
        click.echo(click.style("  ✗ ", fg="red") + "git — install git")
        all_ok = False

    if git_info["ssh_key"]:
        click.echo(click.style("  ✓ ", fg="green") + "SSH key found")
    else:
        click.echo(
            click.style("  ✗ ", fg="yellow") + "No SSH key — private repos won't work"
        )

    if git_info["github_ssh"]:
        click.echo(click.style("  ✓ ", fg="green") + "GitHub SSH access verified")
    else:
        click.echo(
            click.style("  ✗ ", fg="yellow")
            + "GitHub SSH — add key to GitHub for private repos"
        )

    if all_ok:
        click.echo()
        click.echo(click.style("All dependencies satisfied!", fg="green"))


# --- Hook installation ---

CLAUDE_SETTINGS_FILE = Path.home() / ".claude" / "settings.json"
HOOK_DEST_DIR = Path.home() / ".claude" / "hooks" / "permission"
HOOK_NAME = "ccr-approval.py"

CCR_HOOK_ENTRY = {
    "matcher": "",
    "hooks": [
        {
            "type": "command",
            "command": str(HOOK_DEST_DIR / HOOK_NAME),
        }
    ],
}


def _get_hook_source() -> Path:
    """Get the path to the bundled hook script."""
    return Path(__file__).parent / "hooks" / "ccr_approval.py"


def _read_settings() -> dict:
    if CLAUDE_SETTINGS_FILE.exists():
        return json.loads(CLAUDE_SETTINGS_FILE.read_text())
    return {}


def _write_settings(settings: dict) -> None:
    CLAUDE_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS_FILE.write_text(json.dumps(settings, indent=2) + "\n")


def _hook_is_installed(settings: dict) -> bool:
    """Check if CCR hook is already registered in settings."""
    hook_path = str(HOOK_DEST_DIR / HOOK_NAME)
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        for h in entry.get("hooks", []):
            if h.get("command", "") == hook_path:
                return True
    return False


CONFLICTING_HOOKS = [
    "telegram-approve.py",
]


@cli.command()
def install():
    """Install the CCR approval hook into Claude Code settings."""
    # 1. Copy hook script
    HOOK_DEST_DIR.mkdir(parents=True, exist_ok=True)
    src = _get_hook_source()
    dest = HOOK_DEST_DIR / HOOK_NAME
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    click.echo(click.style("  ✓ ", fg="green") + f"Hook script → {dest}")

    # 2. Disable conflicting permission hooks
    for hook_name in CONFLICTING_HOOKS:
        hook_path = HOOK_DEST_DIR / hook_name
        disabled_path = hook_path.with_suffix(hook_path.suffix + ".disabled")
        if hook_path.exists():
            hook_path.rename(disabled_path)
            click.echo(
                click.style("  ✓ ", fg="yellow")
                + f"Disabled conflicting hook: {hook_name} → {disabled_path.name}"
            )

    # 3. Register in settings.json
    settings = _read_settings()
    if _hook_is_installed(settings):
        click.echo(
            click.style("  ✓ ", fg="green") + "Already registered in settings.json"
        )
    else:
        hooks = settings.setdefault("hooks", {})
        pre_tool = hooks.setdefault("PreToolUse", [])
        pre_tool.append(CCR_HOOK_ENTRY)
        _write_settings(settings)
        click.echo(
            click.style("  ✓ ", fg="green")
            + "Registered PreToolUse hook in settings.json"
        )

    click.echo()
    click.echo("Approval routing is ready.")
    click.echo("  • Sessions with 'Skip Permissions' ON  → all tools auto-approved")
    click.echo(
        "  • Sessions with 'Skip Permissions' OFF → routed to your phone for approval"
    )
    click.echo("  • Non-CCR Claude sessions → hook is transparent (no effect)")


@cli.command()
def uninstall():
    """Remove the CCR approval hook from Claude Code settings."""
    # 1. Remove hook script
    dest = HOOK_DEST_DIR / HOOK_NAME
    if dest.exists():
        dest.unlink()
        click.echo(click.style("  ✓ ", fg="green") + f"Removed {dest}")
    else:
        click.echo(
            click.style("  - ", fg="yellow") + "Hook script not found (already removed)"
        )

    # 2. Re-enable previously disabled hooks
    for hook_name in CONFLICTING_HOOKS:
        disabled_path = (HOOK_DEST_DIR / hook_name).with_suffix(
            (HOOK_DEST_DIR / hook_name).suffix + ".disabled"
        )
        if disabled_path.exists():
            disabled_path.rename(HOOK_DEST_DIR / hook_name)
            click.echo(click.style("  ✓ ", fg="green") + f"Re-enabled {hook_name}")

    # 3. Remove from settings.json
    settings = _read_settings()
    hook_path = str(HOOK_DEST_DIR / HOOK_NAME)
    pre_tool = settings.get("hooks", {}).get("PreToolUse", [])
    filtered = [
        entry
        for entry in pre_tool
        if not any(h.get("command") == hook_path for h in entry.get("hooks", []))
    ]
    if len(filtered) != len(pre_tool):
        settings["hooks"]["PreToolUse"] = filtered
        if not filtered:
            del settings["hooks"]["PreToolUse"]
        if not settings["hooks"]:
            del settings["hooks"]
        _write_settings(settings)
        click.echo(click.style("  ✓ ", fg="green") + "Removed from settings.json")
    else:
        click.echo(
            click.style("  - ", fg="yellow")
            + "Not found in settings.json (already removed)"
        )
