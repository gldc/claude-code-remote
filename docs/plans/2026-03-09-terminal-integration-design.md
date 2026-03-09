# Terminal Integration Design

**Goal:** Wire the existing `terminal.py` (PTY WebSocket) into the server so the mobile app can open interactive terminal sessions for any project (scanned or created).

## Problem

The terminal WebSocket endpoint calls `project_store.get(project_id)` to resolve a project ID to a directory path. But `ProjectStore` only contains server-created/cloned projects. Scanned projects (from `~/Developer`) are discovered on-the-fly and never stored, so the terminal returns 403/4004 for them.

## Approach: Resolver Callback

Pass a `Callable[[str], Project | None]` to `create_terminal_router` instead of coupling it to `ProjectStore`. The server provides a closure that checks the store first, then scans directories.

## Changes

### 1. `terminal.py` — Use resolver callback

Change `create_terminal_router(terminal_mgr, project_store)` to `create_terminal_router(terminal_mgr, resolve_project)` where `resolve_project: Callable[[str], Project | None]`. The WebSocket handler calls `resolve_project(project_id)` instead of `project_store.get(project_id)`.

### 2. `server.py` — Wire up terminal with resolver

- Import `TerminalManager`, `create_terminal_router`
- Create `TerminalManager` instance
- Define resolver closure: check `project_store.get(id)` first, then scan `scan_dirs` and match by ID
- Register terminal router on the app
- Shut down terminal manager in lifespan

### 3. `server.py` — Fix existing partial wiring

The server.py already has partial edits from earlier (import, instantiation, shutdown, router include). These need to be reconciled with the resolver approach — replace `project_store` arg with the resolver closure.

### 4. Plan doc — Already exists, no update needed

The original plan doc describes the implementation steps. This design doc captures the integration approach.
