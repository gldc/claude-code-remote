# Terminal Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the existing `terminal.py` PTY WebSocket into the server so the mobile app can open interactive terminals for any project (scanned or server-created).

**Architecture:** Replace the `ProjectStore` dependency in `create_terminal_router` with a `Callable[[str], Project | None]` resolver. The server defines a closure that checks `ProjectStore` first, then scans configured directories. This keeps the terminal module decoupled from project discovery logic.

**Tech Stack:** Python 3.10+, FastAPI, asyncio, pty module

---

### Task 1: Update terminal.py to use a resolver callback

**Files:**
- Modify: `src/claude_code_remote/terminal.py:17-19,239-246`

**Step 1: Replace ProjectStore import and signature with Callable**

Replace lines 17-19:

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from claude_code_remote.project_store import ProjectStore
```

With:

```python
from collections.abc import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from claude_code_remote.models import Project
```

Replace lines 239-246:

```python
def create_terminal_router(
    terminal_mgr: TerminalManager, project_store: ProjectStore
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/terminal/{project_id}")
    async def terminal_stream(websocket: WebSocket, project_id: str):
        project = project_store.get(project_id)
```

With:

```python
def create_terminal_router(
    terminal_mgr: TerminalManager,
    resolve_project: Callable[[str], Project | None],
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/terminal/{project_id}")
    async def terminal_stream(websocket: WebSocket, project_id: str):
        project = resolve_project(project_id)
```

**Step 2: Commit**

```bash
git add src/claude_code_remote/terminal.py
git commit -m "refactor: use resolver callback in terminal router instead of ProjectStore"
```

---

### Task 2: Wire up the resolver in server.py

**Files:**
- Modify: `src/claude_code_remote/server.py:29,99`

**Step 1: Add projects import**

After line 29 (`from claude_code_remote.project_store import ProjectStore`), add:

```python
from claude_code_remote.projects import scan_directory
```

**Step 2: Replace terminal router wiring**

Replace line 99:

```python
    terminal_router = create_terminal_router(terminal_mgr, project_store)
```

With:

```python
    def resolve_project(project_id: str):
        """Resolve project_id to Project from store or scanned directories."""
        stored = project_store.get(project_id)
        if stored:
            return stored
        for d in scan_dirs:
            for project in scan_directory(Path(d).expanduser()):
                if project.id == project_id:
                    return project
        return None

    terminal_router = create_terminal_router(terminal_mgr, resolve_project)
```

This also requires adding `Path` import. Line 6 already has `from contextlib import asynccontextmanager`. Add after that:

```python
from pathlib import Path
```

**Step 3: Verify server starts**

Run: `ccr start --no-auth`

Expected: Server starts without import errors.

**Step 4: Commit**

```bash
git add src/claude_code_remote/server.py
git commit -m "feat: wire terminal router with project resolver for scanned + stored projects"
```

---

### Task 3: Manual smoke test

**Step 1: Start the server**

```bash
ccr start --no-auth
```

**Step 2: Get a project ID**

```bash
curl -s http://127.0.0.1:8080/api/projects | python3 -m json.tool | head -20
```

Pick any project's `id` field.

**Step 3: Test WebSocket connection with websocat or Python**

```bash
python3 -c "
import asyncio, websockets, json

async def test():
    uri = 'ws://127.0.0.1:8080/ws/terminal/PROJECT_ID_HERE'
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({'type': 'input', 'data': 'echo hello\n'}))
        for _ in range(5):
            data = await asyncio.wait_for(ws.recv(), timeout=3)
            print(repr(data))

asyncio.run(test())
"
```

Expected: Connection succeeds (no 403), shell prompt and "hello" appear in output.

**Step 4: Commit any fixes**

```bash
git commit -am "fix: terminal integration fixes"
```
