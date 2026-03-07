"""CLI entry point -- the `ccr` command."""

import shutil
import subprocess
import sys
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

    if all_ok:
        click.echo()
        click.echo(click.style("All dependencies satisfied!", fg="green"))
