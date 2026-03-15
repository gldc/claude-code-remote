# Orphan Process Cleanup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ccr stop` and `ccr start` handle orphaned server processes that outlive their PID files.

**Architecture:** Add `lsof`-based port scanning as a fallback when PID files are missing. Both `stop` and `start` share a kill-with-escalation helper. Only `cli.py` is modified.

**Tech Stack:** Python, `lsof` (macOS system utility), Click CLI framework

**Spec:** `docs/superpowers/specs/2026-03-14-orphan-process-cleanup-design.md`

---

## File Map

- Modify: `src/claude_code_remote/cli.py` — add 3 helper functions, modify `stop` and `start` commands

No new files. No test files (CLI commands are tested manually per the spec — this project has no CLI test infrastructure).

---

## Chunk 1: Implementation

### Task 1: Add `_find_pids_on_port` helper

**Files:**
- Modify: `src/claude_code_remote/cli.py` (insert after line 16, before the `@click.group` decorator)

- [ ] **Step 1: Add the helper function**

Insert after the `CONTEXT_SETTINGS` line (line 16) and before `@click.group`:

```python
def _find_pids_on_port(port: int) -> list[int]:
    """Find PIDs with listening sockets on the given port using lsof."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f"TCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = []
            for line in result.stdout.strip().splitlines():
                try:
                    pids.append(int(line.strip()))
                except ValueError:
                    continue
            return pids
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []
```

- [ ] **Step 2: Verify no syntax errors**

Run: `python -c "from claude_code_remote.cli import _find_pids_on_port; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/cli.py
git commit -m "feat: add _find_pids_on_port helper for orphan detection"
```

---

### Task 2: Add `_wait_for_port_free` helper

**Files:**
- Modify: `src/claude_code_remote/cli.py` (insert right after `_find_pids_on_port`)

- [ ] **Step 1: Add the helper function**

Insert immediately after `_find_pids_on_port`:

```python
def _wait_for_port_free(port: int, timeout: float = 2.0) -> bool:
    """Poll until no process is listening on port. Returns True if freed."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _find_pids_on_port(port):
            return True
        time.sleep(0.2)
    return False
```

- [ ] **Step 2: Commit**

```bash
git add src/claude_code_remote/cli.py
git commit -m "feat: add _wait_for_port_free helper"
```

---

### Task 3: Add `_kill_pids` helper

**Files:**
- Modify: `src/claude_code_remote/cli.py` (insert right after `_wait_for_port_free`)

- [ ] **Step 1: Add the helper function**

Insert immediately after `_wait_for_port_free`:

```python
def _kill_pids(pids: list[int], port: int) -> bool:
    """SIGTERM the given PIDs, wait for port release, escalate to SIGKILL if needed.

    Returns True if port was freed, False otherwise.
    Raises PermissionError if all PIDs fail with PermissionError.
    """
    import signal

    def _signal_pids(sig):
        permission_errors = 0
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                permission_errors += 1
        if permission_errors == len(pids):
            raise PermissionError(f"Cannot signal PIDs {pids}: permission denied")

    _signal_pids(signal.SIGTERM)

    if _wait_for_port_free(port):
        return True

    # Escalate to SIGKILL
    _signal_pids(signal.SIGKILL)

    return _wait_for_port_free(port, timeout=1.0)
```

- [ ] **Step 2: Verify no syntax errors**

Run: `python -c "from claude_code_remote.cli import _kill_pids; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/cli.py
git commit -m "feat: add _kill_pids helper with SIGTERM/SIGKILL escalation"
```

---

### Task 4: Modify `stop` command to use lsof fallback

**Files:**
- Modify: `src/claude_code_remote/cli.py` (the `stop` function — find `def stop():`)

> **Note:** Line numbers below refer to the original file. After Tasks 1-3 insert helpers, all lines shift down ~45 lines. Use text anchors (`def stop():`, `except OSError`) to locate edit points.

- [ ] **Step 1: Replace the `stop` function**

Replace the entire `stop` function (from `@cli.command()` above `def stop():` through the end of the function) with:

```python
@cli.command()
def stop():
    """Stop the API server."""
    from claude_code_remote.config import PID_DIR, load_config
    import signal

    server_killed_via_pid = False

    for name in ["server", "menubar", "caffeinate"]:
        pid_file = PID_DIR / f"{name}.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, signal.SIGTERM)
                click.echo(f"Stopped {name} (PID {pid})")
                if name == "server":
                    server_killed_via_pid = True
            except (ProcessLookupError, PermissionError, ValueError):
                click.echo(f"{name} was not running")
            pid_file.unlink(missing_ok=True)
        else:
            if name == "server":
                pass  # Don't print "not running" yet — check port fallback first

    if not server_killed_via_pid:
        # Fallback: check if something is listening on the configured port
        config = load_config()
        port = config.get("port", 8080)
        pids = _find_pids_on_port(port)
        if pids:
            try:
                if _kill_pids(pids, port):
                    click.echo(
                        f"Stopped orphaned server process "
                        f"(PID {', '.join(str(p) for p in pids)}) on port {port}"
                    )
                else:
                    click.echo(
                        click.style("WARNING: ", fg="yellow")
                        + f"Process on port {port} did not exit after SIGKILL"
                    )
            except PermissionError:
                click.echo(
                    click.style("ERROR: ", fg="red")
                    + f"Port {port} is in use by another user's process"
                )
        else:
            click.echo("server is not running")
```

- [ ] **Step 2: Verify no syntax errors**

Run: `python -c "from claude_code_remote.cli import stop; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Smoke test — stop with nothing running**

Run: `ccr stop`
Expected: `server is not running` (same behavior as before)

- [ ] **Step 4: Commit**

```bash
git add src/claude_code_remote/cli.py
git commit -m "feat: ccr stop falls back to lsof when PID file is missing"
```

---

### Task 5: Modify `start` command to offer orphan kill on port conflict

**Files:**
- Modify: `src/claude_code_remote/cli.py` (the `except OSError` block inside `start` — find `except OSError as e:` after `test_sock.bind`)

- [ ] **Step 1: Replace the port-conflict catch block**

Replace the `except OSError as e:` block (from `except OSError` through `sys.exit(1)` / `raise`) with:

```python
    except OSError as e:
        if e.errno in (48, 98):  # EADDRINUSE: 48 on macOS, 98 on Linux
            pids = _find_pids_on_port(port)
            if pids:
                pid_str = ", ".join(str(p) for p in pids)
                if click.confirm(
                    f"Port {port} in use by PID {pid_str}. Kill and continue?",
                    default=False,
                ):
                    try:
                        if _kill_pids(pids, port):
                            click.echo(f"Killed process(es) on port {port}")
                        else:
                            click.echo(
                                click.style("ERROR: ", fg="red")
                                + f"Could not free port {port}"
                            )
                            sys.exit(1)
                    except PermissionError:
                        click.echo(
                            click.style("ERROR: ", fg="red")
                            + f"Port {port} is in use by another user's process"
                        )
                        sys.exit(1)
                else:
                    sys.exit(1)
            else:
                click.echo(
                    click.style("ERROR: ", fg="red")
                    + f"Port {port} already in use on {host}"
                )
                click.echo(
                    f"  Run `ccr stop` or find the process with `lsof -i :{port}`"
                )
                sys.exit(1)
        raise
```

- [ ] **Step 2: Verify no syntax errors**

Run: `python -c "from claude_code_remote.cli import start; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/cli.py
git commit -m "feat: ccr start offers to kill orphan process on port conflict"
```

---

### Task 6: Final verification

- [ ] **Step 1: Full import check**

Run: `python -c "from claude_code_remote.cli import cli; print('OK')"`
Expected: `OK`

- [ ] **Step 2: Verify ccr --help still works**

Run: `ccr --help`
Expected: Normal help output with all commands listed

- [ ] **Step 3: Verify ccr start (happy path)**

Run: `ccr start -d --menubar` then `ccr stop`
Expected: Server starts and stops normally

- [ ] **Step 4: Final commit (if any formatting/cleanup needed)**

Only if adjustments were needed during verification.
