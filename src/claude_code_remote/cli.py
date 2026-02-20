"""CLI entry point — the `ccr` command."""

import shutil
import click

from claude_code_remote import __version__


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__, prog_name="ccr")
def cli():
    """Claude Code Remote — access Claude Code CLI from any device over Tailscale."""


@cli.command()
@click.option("-d", "--daemon", is_flag=True, help="Run in background.")
def start(daemon):
    """Start all remote CLI services."""
    from claude_code_remote import services
    if daemon:
        services.daemonize(services.start_all)
    else:
        services.start_all()


@cli.command()
def stop():
    """Stop all remote CLI services."""
    from claude_code_remote import services
    services.stop_all()


@cli.command()
def status():
    """Show service status."""
    from claude_code_remote import tailscale, services

    ip = tailscale.get_ip()
    dns = tailscale.get_dns_name()
    host = dns or ip

    click.echo(f"Tailscale IP:  {ip or 'Not connected'}")
    click.echo(f"MagicDNS:      {dns or 'Not available'}")
    click.echo()

    svc = services.get_status()
    for name, alive in svc.items():
        dot = click.style("●", fg="green") if alive else click.style("○", fg="red")
        click.echo(f"  {dot} {name}")

    if host and any(svc.values()):
        click.echo()
        click.echo(f"  Voice UI:  http://{host}:8080")
        click.echo(f"  Terminal:  http://{host}:7681")


@cli.command()
def doctor():
    """Check prerequisites and dependencies."""
    checks = [
        ("tmux", "brew install tmux"),
        ("ttyd", "brew install ttyd"),
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

    # Python packages
    packages = ["fastapi", "uvicorn", "rumps", "click"]
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


@cli.command()
@click.option("-d", "--daemon", is_flag=True, help="Run in background.")
def menubar(daemon):
    """Launch the macOS menu bar app."""
    if daemon:
        import subprocess, sys
        subprocess.Popen(
            [sys.executable, "-m", "claude_code_remote.menubar"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        click.echo("Menubar app launched in background.")
    else:
        from claude_code_remote.menubar import RemoteCLIApp
        RemoteCLIApp().run()
