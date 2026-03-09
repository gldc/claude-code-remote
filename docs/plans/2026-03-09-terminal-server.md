# Terminal Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a PTY WebSocket endpoint to the CCR server so the mobile app can open interactive terminal sessions scoped to a project directory.

**Architecture:** New `terminal.py` module manages one PTY per project. A FastAPI WebSocket endpoint at `/ws/terminal/{project_id}` spawns a shell in the project's working directory, pipes stdin/stdout bidirectionally, and supports resize. Follows the existing pattern in `websocket.py`.

**Tech Stack:** Python 3.10+, FastAPI, asyncio, `pty` module (Unix), `fcntl`/`struct` for resize

---

### Task 1: Create the TerminalManager class

**Files:**
- Create: `src/claude_code_remote/terminal.py`

**Step 1: Write the TerminalManager with PTY spawn and cleanup**

```python
"""Interactive terminal (PTY) management for project-scoped shells."""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import signal
import struct
import termios
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

REPLAY_BUFFER_SIZE = 16 * 1024  # 16 KB
IDLE_TIMEOUT_SECONDS = 2 * 60 * 60  # 2 hours


@dataclass
class TerminalSession:
    """A running PTY process for a project."""

    project_id: str
    pid: int
    fd: int  # PTY master file descriptor
    output_buffer: bytearray = field(default_factory=bytearray)
    last_output_time: float = field(default_factory=time.monotonic)
    connected_clients: int = 0
    _closed: bool = False

    def write_input(self, data: str) -> None:
        """Write user input to the PTY."""
        if not self._closed:
            os.write(self.fd, data.encode())

    def resize(self, cols: int, rows: int) -> None:
        """Send SIGWINCH to resize the PTY."""
        if not self._closed:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
            os.kill(self.pid, signal.SIGWINCH)

    def close(self) -> None:
        """Terminate the PTY process."""
        if self._closed:
            return
        self._closed = True
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            pass


class TerminalManager:
    """Manages one PTY per project with idle timeout."""

    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._subscribers: dict[str, list[asyncio.Queue[bytes]]] = {}
        self._read_tasks: dict[str, asyncio.Task] = {}
        self._timeout_tasks: dict[str, asyncio.Task] = {}

    def get_or_create(self, project_id: str, cwd: str) -> TerminalSession:
        """Get existing terminal or spawn a new one for the project."""
        if project_id in self._sessions and not self._sessions[project_id]._closed:
            return self._sessions[project_id]

        shell = os.environ.get("SHELL", "/bin/zsh")
        pid, fd = pty.openpty()

        # Fork the shell process
        child_pid = os.fork()
        if child_pid == 0:
            # Child process
            os.close(fd)  # close master in child
            os.setsid()
            # Open slave PTY
            slave_fd = os.open(os.ttyname(pid), os.O_RDWR)
            os.close(pid)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.chdir(cwd)
            os.execvp(shell, [shell, "-l"])

        # Parent process
        os.close(pid)  # close slave in parent

        session = TerminalSession(project_id=project_id, pid=child_pid, fd=fd)
        self._sessions[project_id] = session
        self._subscribers[project_id] = []

        # Start reading PTY output
        self._read_tasks[project_id] = asyncio.get_event_loop().create_task(
            self._read_output(project_id)
        )

        logger.info(f"Terminal spawned for project {project_id} (pid={child_pid})")
        return session

    async def _read_output(self, project_id: str) -> None:
        """Read PTY output and broadcast to subscribers."""
        session = self._sessions[project_id]
        loop = asyncio.get_event_loop()

        while not session._closed:
            try:
                data = await loop.run_in_executor(None, self._blocking_read, session.fd)
                if not data:
                    break
            except OSError:
                break

            # Update replay buffer (keep last 16KB)
            session.output_buffer.extend(data)
            if len(session.output_buffer) > REPLAY_BUFFER_SIZE:
                session.output_buffer = session.output_buffer[-REPLAY_BUFFER_SIZE:]

            session.last_output_time = time.monotonic()

            # Reset idle timeout on output
            self._reset_idle_timeout(project_id)

            # Broadcast to all subscribers
            for queue in self._subscribers.get(project_id, []):
                try:
                    queue.put_nowait(data)
                except asyncio.QueueFull:
                    pass  # Drop if subscriber is slow

        # PTY died
        logger.info(f"Terminal output ended for project {project_id}")
        self._cleanup(project_id)

    @staticmethod
    def _blocking_read(fd: int) -> bytes:
        """Blocking read from PTY fd (run in executor)."""
        return os.read(fd, 4096)

    def subscribe(self, project_id: str) -> asyncio.Queue[bytes]:
        """Subscribe to terminal output. Returns a queue."""
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=256)
        if project_id not in self._subscribers:
            self._subscribers[project_id] = []
        self._subscribers[project_id].append(queue)
        if project_id in self._sessions:
            self._sessions[project_id].connected_clients += 1
        return queue

    def unsubscribe(self, project_id: str, queue: asyncio.Queue[bytes]) -> None:
        """Unsubscribe from terminal output."""
        if project_id in self._subscribers:
            self._subscribers[project_id] = [
                q for q in self._subscribers[project_id] if q is not queue
            ]
        if project_id in self._sessions:
            self._sessions[project_id].connected_clients -= 1
            # Start idle timeout if no clients
            if self._sessions[project_id].connected_clients <= 0:
                self._start_idle_timeout(project_id)

    def _start_idle_timeout(self, project_id: str) -> None:
        """Start idle timeout when last client disconnects."""
        self._cancel_idle_timeout(project_id)
        self._timeout_tasks[project_id] = asyncio.get_event_loop().create_task(
            self._idle_timeout(project_id)
        )

    def _cancel_idle_timeout(self, project_id: str) -> None:
        task = self._timeout_tasks.pop(project_id, None)
        if task:
            task.cancel()

    def _reset_idle_timeout(self, project_id: str) -> None:
        """Reset idle timeout if running (PTY had output)."""
        if project_id in self._timeout_tasks:
            self._start_idle_timeout(project_id)

    async def _idle_timeout(self, project_id: str) -> None:
        """Kill terminal after idle timeout."""
        await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
        logger.info(f"Terminal idle timeout for project {project_id}")
        self._cleanup(project_id)

    def _cleanup(self, project_id: str) -> None:
        """Close terminal and clean up resources."""
        session = self._sessions.pop(project_id, None)
        if session:
            session.close()
        self._subscribers.pop(project_id, None)
        self._cancel_idle_timeout(project_id)
        task = self._read_tasks.pop(project_id, None)
        if task:
            task.cancel()

    async def shutdown(self) -> None:
        """Shut down all terminals (called on server exit)."""
        for project_id in list(self._sessions):
            self._cleanup(project_id)
```

**Step 2: Commit**

```bash
git add src/claude_code_remote/terminal.py
git commit -m "feat: add TerminalManager with PTY spawn, resize, replay buffer, and idle timeout"
```

---

### Task 2: Create the WebSocket endpoint

**Files:**
- Modify: `src/claude_code_remote/terminal.py` (append to file)

**Step 1: Add the WebSocket router factory**

Append to `terminal.py`:

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from claude_code_remote.project_store import ProjectStore


def create_terminal_router(
    terminal_mgr: TerminalManager, project_store: ProjectStore
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/terminal/{project_id}")
    async def terminal_stream(websocket: WebSocket, project_id: str):
        project = project_store.get(project_id)
        if not project:
            await websocket.close(code=4004, reason="Project not found")
            return

        await websocket.accept()

        # Get or create terminal for this project
        session = terminal_mgr.get_or_create(project_id, project.path)

        # Send replay buffer for context on reconnect
        if session.output_buffer:
            await websocket.send_bytes(bytes(session.output_buffer))

        # Subscribe to output
        queue = terminal_mgr.subscribe(project_id)

        async def send_output():
            """Forward PTY output to WebSocket."""
            try:
                while True:
                    data = await queue.get()
                    await websocket.send_bytes(data)
            except Exception:
                pass

        async def recv_input():
            """Forward WebSocket messages to PTY."""
            try:
                while True:
                    raw = await websocket.receive_text()
                    import json as _json

                    msg = _json.loads(raw)
                    msg_type = msg.get("type")

                    if msg_type == "input":
                        session.write_input(msg["data"])
                    elif msg_type == "resize":
                        session.resize(msg["cols"], msg["rows"])
                    elif msg_type == "close":
                        break
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.error(f"Terminal input error: {e}")

        # Run send and receive concurrently
        send_task = asyncio.create_task(send_output())
        try:
            await recv_input()
        finally:
            send_task.cancel()
            terminal_mgr.unsubscribe(project_id, queue)

    return router
```

**Step 2: Commit**

```bash
git add src/claude_code_remote/terminal.py
git commit -m "feat: add WebSocket endpoint for interactive terminal at /ws/terminal/{project_id}"
```

---

### Task 3: Register the terminal router in the server

**Files:**
- Modify: `src/claude_code_remote/server.py:31,64,93-94`

**Step 1: Add imports and instantiation**

In `server.py`, add the import (after line 31):

```python
from claude_code_remote.terminal import TerminalManager, create_terminal_router
```

Inside `create_app()`, after `project_store = ProjectStore(PROJECTS_FILE)` (after line 56), add:

```python
    terminal_mgr = TerminalManager()
```

In the lifespan shutdown (after line 64 `await session_mgr.shutdown()`), add:

```python
        await terminal_mgr.shutdown()
```

After the existing WebSocket router registration (after line 94), add:

```python
    terminal_router = create_terminal_router(terminal_mgr, project_store)
    app.include_router(terminal_router)
```

**Step 2: Verify server starts**

Run: `python -m claude_code_remote.cli --skip-auth`

Expected: Server starts without errors.

**Step 3: Commit**

```bash
git add src/claude_code_remote/server.py
git commit -m "feat: register terminal WebSocket router in server"
```

---

### Task 4: Verify the ProjectStore.get() method exists

**Files:**
- Read: `src/claude_code_remote/project_store.py`

**Step 1: Check that `project_store.get(project_id)` returns a project with a `.path` attribute**

If the method doesn't exist or returns a different shape, adapt the `create_terminal_router` to match the actual API. The terminal endpoint needs to resolve `project_id → directory path`.

**Step 2: If changes needed, commit**

```bash
git add src/claude_code_remote/project_store.py src/claude_code_remote/terminal.py
git commit -m "fix: adapt terminal router to project store API"
```

---

### Task 5: Manual integration test

**Step 1: Start the server**

```bash
python -m claude_code_remote.cli --skip-auth
```

**Step 2: Test with websocat or a simple Python script**

```python
import asyncio
import websockets
import json

async def test():
    uri = "ws://127.0.0.1:8080/ws/terminal/YOUR_PROJECT_ID"
    async with websockets.connect(uri) as ws:
        # Send a command
        await ws.send(json.dumps({"type": "input", "data": "echo hello\n"}))
        # Read output
        for _ in range(10):
            data = await asyncio.wait_for(ws.recv(), timeout=2)
            print(data)

asyncio.run(test())
```

Expected: See shell prompt and "hello" echoed back.

**Step 3: Test resize**

```python
await ws.send(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
```

Expected: No error. PTY resized.

**Step 4: Commit any fixes**

```bash
git commit -am "fix: terminal integration test fixes"
```
