"""Interactive terminal (PTY) management for project-scoped shells."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import termios
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from claude_code_remote.project_store import ProjectStore

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
            return
        # Reap the child, escalate to SIGKILL if needed
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            if pid == 0:
                time.sleep(0.5)
                try:
                    os.kill(self.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                os.waitpid(self.pid, 0)
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
        master_fd, slave_fd = pty.openpty()

        child_pid = os.fork()
        if child_pid == 0:
            # Child process: set up slave PTY as stdin/stdout/stderr
            os.close(master_fd)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            if slave_fd > 2:
                os.close(slave_fd)
            os.chdir(cwd)
            os.execvp(shell, [shell, "-l"])

        # Parent process: keep master, close slave
        os.close(slave_fd)

        session = TerminalSession(project_id=project_id, pid=child_pid, fd=master_fd)
        self._sessions[project_id] = session
        self._subscribers[project_id] = []

        # Start reading PTY output
        self._read_tasks[project_id] = asyncio.create_task(
            self._read_output(project_id)
        )

        logger.info(f"Terminal spawned for project {project_id} (pid={child_pid})")
        return session

    async def _read_output(self, project_id: str) -> None:
        """Read PTY output and broadcast to subscribers."""
        session = self._sessions[project_id]
        loop = asyncio.get_running_loop()

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

        # PTY died — send sentinel to all subscribers so they know to close
        logger.info(f"Terminal output ended for project {project_id}")
        for queue in self._subscribers.get(project_id, []):
            try:
                queue.put_nowait(None)  # type: ignore[arg-type]
            except asyncio.QueueFull:
                pass
        self._read_tasks.pop(project_id, None)
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
        session = self._sessions.get(project_id)
        if session:
            session.connected_clients += 1
            self._cancel_idle_timeout(project_id)
        return queue

    def unsubscribe(self, project_id: str, queue: asyncio.Queue[bytes]) -> None:
        """Unsubscribe from terminal output."""
        if project_id in self._subscribers:
            self._subscribers[project_id] = [
                q for q in self._subscribers[project_id] if q is not queue
            ]
        session = self._sessions.get(project_id)
        if session:
            session.connected_clients -= 1
            if session.connected_clients <= 0:
                self._start_idle_timeout(project_id)

    def _start_idle_timeout(self, project_id: str) -> None:
        """Start idle timeout when last client disconnects."""
        self._cancel_idle_timeout(project_id)
        self._timeout_tasks[project_id] = asyncio.create_task(
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
        if project_id not in self._sessions:
            return  # Already cleaned up
        session = self._sessions.pop(project_id)
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


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


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
                    if data is None:
                        # PTY died — close WebSocket cleanly
                        await websocket.close(code=1000, reason="Terminal exited")
                        return
                    await websocket.send_bytes(data)
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
            except Exception as e:
                logger.debug(f"Terminal send_output error: {e}")

        async def recv_input():
            """Forward WebSocket messages to PTY."""
            try:
                while True:
                    raw = await websocket.receive_text()
                    msg = json.loads(raw)
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
