# Orphan Process Cleanup for `ccr stop` and `ccr start`

## Problem

When the CCR server process outlives its PID file (crash, manual deletion, etc.), both `stop` and `start` become stuck:
- `stop` reports "server is not running" because no PID file exists
- `start` fails with "Port 8080 already in use" and tells the user to run `ccr stop` (which won't help)

The user must manually run `lsof -i :8080` and `kill` the orphaned process.

## Solution

Add a port-based fallback using `lsof` to find and kill orphaned processes when PID files are missing.

### New helper: `_find_pids_on_port(port) -> list[int]`

- Runs `lsof -ti TCP:{port} -sTCP:LISTEN` to find PIDs with listening sockets on the port (not ephemeral client connections)
- Port-only search (no host filtering) avoids DNS resolution issues with Tailscale IPs and handles both `--no-auth` localhost and normal Tailscale modes
- Returns a list of PIDs (may be multiple due to parent/child or IPv4/IPv6)
- Returns empty list if `lsof` fails, is not installed, or finds nothing
- Lives in `cli.py` alongside existing helpers

### `stop` command changes

After the existing PID-file loop, if the server PID file was missing or the process was already dead:
1. Import and call `load_config()` to get the configured port
2. Call `_find_pids_on_port(port)`
3. If PIDs found, SIGTERM all of them
4. Wait up to 2 seconds for port release (poll every 0.2s); escalate to SIGKILL if still occupied
5. Report: `"Stopped orphaned server process (PID {pid}) on port {port}"`
6. Handle `PermissionError` -- report that the port is in use by another user's process

Note: if a stale PID file points to a dead process (existing code handles this, reports "was not running", deletes PID file), the fallback then catches any actual orphan on the port with a different PID.

No user confirmation -- `stop` should just stop things.

### `start` command changes

The existing pre-flight `socket.bind()` check (lines 53-67) catches `EADDRINUSE` and exits. Modify this catch block to offer recovery instead of just exiting:

1. Call `_find_pids_on_port(port)`
2. If PIDs found, prompt: `"Port {port} in use by PID {pid}. Kill it and continue? [y/N]"` (show first PID)
3. If confirmed, SIGTERM all PIDs, wait up to 2 seconds for port release (poll every 0.2s)
4. If port still occupied after 2s, escalate to SIGKILL, wait 1 more second
5. If still occupied, exit with error
6. If declined or no PIDs found, exit with the existing error message
7. Handle `PermissionError` -- report that the port is in use by another user's process and exit

### Shared kill logic

Both `stop` and `start` use the same SIGTERM -> wait -> SIGKILL escalation. Extract a helper `_kill_pids(pids, port, host) -> bool` that returns True if the port was freed.

## Out of scope

- **`status` command:** Could show orphaned processes, deferred to keep this change minimal
- **Linux `lsof` availability:** This tool targets macOS; `lsof` missing is handled gracefully (returns empty list)
- **Concurrent `ccr start` race conditions:** Unlikely for a single-user CLI tool

## Scope

- Only `src/claude_code_remote/cli.py` is modified
- No new dependencies (`lsof` is standard on macOS)
- No changes to server, config, or other modules

## Testing

Manual verification:
1. Start server, delete PID file, run `ccr stop` -- should find and kill orphan
2. Start server, delete PID file, run `ccr start -d` -- should offer to kill and restart
3. Run `ccr stop` with no server running -- should behave as before
4. Run `ccr start` with port free -- should behave as before
5. Start a non-CCR process on port 8080 as another user -- `stop`/`start` should report permission error gracefully
6. Stale PID file (dead process) + orphan on port -- `stop` should clean up both
