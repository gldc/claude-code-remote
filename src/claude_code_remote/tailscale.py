"""Tailscale integration — IP and MagicDNS resolution."""

import json
import shutil
import subprocess


def _find_binary() -> str:
    return shutil.which("tailscale") or "/usr/local/bin/tailscale"


def get_ip() -> str | None:
    """Return the Tailscale IPv4 address, or None."""
    try:
        result = subprocess.run(
            [_find_binary(), "ip", "-4"],
            capture_output=True, text=True, timeout=5,
        )
        ip = result.stdout.strip()
        return ip if result.returncode == 0 and ip else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_dns_name() -> str | None:
    """Return the MagicDNS name (without trailing dot), or None."""
    try:
        result = subprocess.run(
            [_find_binary(), "status", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            dns_name = data.get("Self", {}).get("DNSName", "")
            return dns_name.rstrip(".") if dns_name else None
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def get_host() -> str | None:
    """Return MagicDNS name with IP fallback, or None."""
    return get_dns_name() or get_ip()


def require_ip() -> str:
    """Return Tailscale IP or exit with a helpful message."""
    ip = get_ip()
    if not ip:
        raise SystemExit(
            "ERROR: Tailscale not running or no IPv4 address.\n"
            "Start Tailscale and try again."
        )
    return ip
