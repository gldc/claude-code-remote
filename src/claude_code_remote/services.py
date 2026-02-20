"""Service lifecycle — start, stop, status, watchdog."""

import os
import signal
import shutil
import stat
import subprocess
import sys
import time

from claude_code_remote import tailscale, tmux
from claude_code_remote.config import ensure_dirs, LOG_DIR, PID_DIR

SERVICES = ["ttyd", "voice-wrapper", "caffeinate"]
TTYD_PORT = 7681
WRAPPER_PORT = 8080
TTYD_OPTIONS = [
    "--writable",
    "-t", "fontSize=14",
    "-t", "lineHeight=1.2",
    "-t", "cursorBlink=true",
    "-t", "cursorStyle=block",
    "-t", "scrollback=10000",
    "-t", 'fontFamily="Menlo, Monaco, Consolas, monospace, Apple Color Emoji, Segoe UI Emoji"',
]


# ── PID helpers ──────────────────────────────────────────────────────────

def _write_pid(name: str, pid: int) -> None:
    (PID_DIR / f"{name}.pid").write_text(str(pid))


def _read_pid(name: str) -> int | None:
    try:
        return int((PID_DIR / f"{name}.pid").read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _kill_service(name: str) -> bool:
    pid = _read_pid(name)
    if pid and _is_alive(pid):
        os.kill(pid, signal.SIGTERM)
        (PID_DIR / f"{name}.pid").unlink(missing_ok=True)
        return True
    (PID_DIR / f"{name}.pid").unlink(missing_ok=True)
    return False


# ── tmux attach script (for ttyd) ───────────────────────────────────────

def _create_tmux_attach_script() -> str:
    """Write a small shell script that ttyd will exec."""
    script_path = PID_DIR / "tmux-attach.sh"
    tmux_bin = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
    script_path.write_text(
        "#!/bin/bash\n"
        "unset CLAUDECODE\n"
        "unset CLAUDE_CODE_ENTRYPOINT\n"
        "unset CLAUDE_CODE_ENTRY_VERSION\n"
        "unset CLAUDE_CODE_ENV_VERSION\n"
        'export LANG="en_US.UTF-8"\n'
        'export LC_ALL="en_US.UTF-8"\n'
        f'exec "{tmux_bin}" new-session -A -s claude -c "$HOME"\n'
    )
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(script_path)


# ── Start / Stop ─────────────────────────────────────────────────────────

def start_all() -> None:
    ensure_dirs()
    ip = tailscale.require_ip()
    host = tailscale.get_host() or ip

    # Kill existing services (PID files + pkill fallback)
    for name in SERVICES:
        _kill_service(name)
    # Fallback: SIGKILL processes that might have stale/missing PID files
    for pattern in ["ttyd --port", "claude_code_remote.voice_server"]:
        try:
            subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True, timeout=5)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    time.sleep(1)

    # Ensure tmux session
    tmux.ensure_session()

    # Caffeinate
    caff = subprocess.Popen(["caffeinate", "-d", "-i", "-s"])
    _write_pid("caffeinate", caff.pid)
    print(f"caffeinate running (PID: {caff.pid})")

    # ttyd (note: ttyd forks internally, so Popen parent exits quickly)
    attach_script = _create_tmux_attach_script()
    ttyd_bin = shutil.which("ttyd") or "ttyd"
    ttyd_log = open(LOG_DIR / "ttyd.log", "a")
    ttyd_proc = subprocess.Popen(
        [ttyd_bin, "--port", str(TTYD_PORT), "--interface", ip] + TTYD_OPTIONS + [attach_script],
        stdout=ttyd_log, stderr=ttyd_log,
    )
    # Wait for fork, then find the real child PID via lsof
    time.sleep(1)
    _update_ttyd_pid(ip)
    print(f"ttyd running on http://{host}:{TTYD_PORT}")

    # Voice wrapper
    voice_log = open(LOG_DIR / "voice-wrapper.log", "a")
    voice_proc = subprocess.Popen(
        [sys.executable, "-m", "claude_code_remote.voice_server", ip],
        stdout=voice_log, stderr=voice_log,
    )
    _write_pid("voice-wrapper", voice_proc.pid)
    print(f"voice wrapper running (PID: {voice_proc.pid}) on http://{host}:{WRAPPER_PORT}")

    print()
    print("=== Remote CLI Ready ===")
    print(f"Terminal:  http://{host}:{TTYD_PORT}")
    print(f"Voice UI:  http://{host}:{WRAPPER_PORT}")
    print()
    print("Press Ctrl+C to stop.")

    # Watchdog
    _watchdog(ttyd_proc, ttyd_bin, ip, attach_script, ttyd_log)


def _port_in_use(port: int, ip: str) -> bool:
    """Check if a port is in use (ttyd may fork, so parent exits but child holds port)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((ip, port)) == 0
    except OSError:
        return False


def _watchdog(ttyd_proc, ttyd_bin, ip, attach_script, ttyd_log) -> None:
    keep_running = True

    def _handle_signal(sig, frame):
        nonlocal keep_running
        keep_running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # ttyd forks internally — the Popen parent exits immediately.
    # Wait briefly for the fork, then find the real child PID.
    try:
        ttyd_proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass  # ttyd didn't fork (unlikely), Popen PID is correct

    # Update PID file with the actual listening process
    _update_ttyd_pid(ip)

    # Poll-based watchdog: check if port is alive every 10s
    while keep_running:
        time.sleep(10)
        if not keep_running:
            break
        if not _port_in_use(TTYD_PORT, ip):
            print("ttyd exited, restarting in 5s...")
            time.sleep(5)
            if not keep_running:
                break
            new_proc = subprocess.Popen(
                [ttyd_bin, "--port", str(TTYD_PORT), "--interface", ip] + TTYD_OPTIONS + [attach_script],
                stdout=ttyd_log, stderr=ttyd_log,
            )
            try:
                new_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            _update_ttyd_pid(ip)


def _update_ttyd_pid(ip: str) -> None:
    """Find the actual ttyd PID listening on the port and update the PID file."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{TTYD_PORT}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip():
            _write_pid("ttyd", int(result.stdout.strip().split()[0]))
    except (subprocess.TimeoutExpired, ValueError):
        pass


def stop_all() -> None:
    print("Stopping remote CLI services...")
    # Kill ALL daemon/watchdog processes FIRST to prevent ttyd auto-restart
    daemon_pid = _read_pid("daemon")
    if daemon_pid and _is_alive(daemon_pid):
        os.kill(daemon_pid, signal.SIGKILL)
        (PID_DIR / "daemon.pid").unlink(missing_ok=True)
    # Also kill any other ccr start daemons from previous runs
    try:
        subprocess.run(["pkill", "-9", "-f", "ccr start"], capture_output=True, timeout=5)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    time.sleep(0.5)
    # Kill services via PID files
    for name in SERVICES:
        if _kill_service(name):
            print(f"{name} stopped")
        else:
            print(f"{name} was not running")
    # Fallback: SIGKILL processes that might have stale/missing PID files
    # Run twice with delay to catch anything restarted by a dying watchdog
    for _ in range(2):
        for pattern in ["ttyd --port", "claude_code_remote.voice_server"]:
            try:
                subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True, timeout=5)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        time.sleep(0.5)
    print()
    print("Services stopped. tmux session 'claude' is still alive.")
    print("To kill it too: tmux kill-session -t claude")


def get_status() -> dict[str, bool]:
    result = {}
    for name in SERVICES:
        pid = _read_pid(name)
        result[name] = pid is not None and _is_alive(pid)
    # ttyd forks, so PID file may be stale — also check if port is in use
    if not result.get("ttyd"):
        ip = tailscale.get_ip()
        if ip and _port_in_use(TTYD_PORT, ip):
            result["ttyd"] = True
    return result


def daemonize(target) -> None:
    """Fork into background, parent returns, child runs target()."""
    ensure_dirs()
    pid = os.fork()
    if pid > 0:
        # Parent — write daemon PID and exit
        _write_pid("daemon", pid)
        print(f"Daemonized (PID: {pid})")
        return
    # Child
    os.setsid()
    target()
