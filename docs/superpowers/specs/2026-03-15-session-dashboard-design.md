# CCR Session Dashboard

## Problem

CCR session data and native Claude Code conversation history are stored locally but there's no way to browse, search, or analyze them visually. Users must read JSON files manually or use the API directly. There's no unified view across CCR-managed and native Claude sessions.

## Solution

A web dashboard served by the existing CCR FastAPI server, providing a unified view of all Claude Code sessions on the host machine -- both CCR-managed and native. Supports session browsing, detail views, lightweight analytics, session resumption, and cron job management.

## Data Sources

### Native Claude Code Sessions

- **Location:** `~/.claude/projects/<path-hash>/<uuid>.jsonl`
- **Path hash format:** Project path with `/` replaced by `-` (e.g., `/Users/gldc/Developer/foo` becomes `-Users-gldc-Developer-foo`)
- **Format:** JSONL, one event per line
- **Displayed event types:** `user`, `assistant`, `system` (rendered in message timeline)
- **Metadata-only event types:** `progress`, `file-history-snapshot`, `queue-operation`, `pr-link` (used for metadata extraction, not displayed)
- **Key fields per event:** `type`, `message` (with `role`, `content`, `model`, `usage`), `uuid`, `timestamp`, `sessionId`, `cwd`, `gitBranch`
- **Active session info:** `~/.claude/sessions/*.json` (pid, sessionId, cwd, startedAt)
- **Global history index:** `~/.claude/history.jsonl` -- used for fast session discovery without parsing every JSONL file. Contains `display` (prompt preview), `timestamp`, `project`, `sessionId`.

### CCR Sessions

- **Location:** `~/.local/state/claude-code-remote/sessions/*.json`
- **Format:** JSON, one file per session
- **Key fields:** id, name, project_dir, status, claude_session_id, current_model, total_cost_usd, context_percent, messages, created_at, updated_at, owner, collaborators, archived, git_branch, skip_permissions

### Cron Jobs

- **Location:** `~/.local/state/claude-code-remote/cron/{job_id}.json`
- **History:** `~/.local/state/claude-code-remote/cron_history.jsonl`
- **Existing API:** Full CRUD at `/api/cron-jobs/*` (list, create, get, update, delete, toggle, trigger, history)
- **Key fields:** id, name, schedule (cron expression), enabled, execution_mode (SPAWN/PERSISTENT), session_config, persistent_session_id, project_dir, timeout_minutes, prompt_template, next_run_at, last_run_at, last_run_status
- **Run history fields:** id, cron_job_id, session_id, status (success/error/running/timeout -- lowercase CronRunStatus enum), started_at, completed_at, cost_usd, error_message
- **Session link:** Sessions have a `cron_job_id` field linking back to the cron job that spawned them

### Unified Session Model

A Pydantic model (`DashboardSession`) in `models.py`, following the existing `Session`/`SessionSummary` pattern. A corresponding `DashboardSessionSummary` model is used for list responses.

| Field | Type | Source |
|-------|------|--------|
| id | str | CCR session ID or native sessionId (UUID) |
| name | str | CCR name or derived from project dir basename |
| project_dir | str | Both |
| source | Literal["ccr", "native"] | Derived (cron-spawned sessions are "ccr" with cron_job_id set) |
| status | str | CCR status or "active"/"completed" for native |
| current_model | str \| None | Both (from last assistant event for native) |
| total_cost_usd | float | CCR field or estimated from token usage for native |
| cost_is_estimated | bool | False for CCR, True for native |
| message_count | int | Both |
| context_percent | int \| None | CCR only (int, matching existing Session model) |
| git_branch | str \| None | Both |
| created_at | datetime | Both |
| updated_at | datetime | Both (last event timestamp for native) |
| owner | str \| None | CCR only |
| claude_session_id | str | CCR field or native sessionId |
| cron_job_id | str \| None | CCR only -- links to parent cron job if spawned by one |

Native session `project_dir`: derived from the first event's `cwd` field (stable since Claude Code sets the working directory at session start).

## Architecture

```
FastAPI (existing server, port 8080)
├── /api/*              (existing API routes, unchanged)
├── /api/dashboard/*    (new: unified session list, detail, analytics)
└── /dashboard/*        (new: static SPA files)
```

CORS: The SPA is served from the same origin as the API (`/dashboard` and `/api/dashboard/*` on the same host:port), so no CORS changes are needed. The existing `allow_origins=[]` is fine.

### Backend (Python)

**`native_sessions.py`** -- Discovers and parses native Claude Code sessions:
- Scans `~/.claude/projects/` for JSONL conversation files
- Uses `~/.claude/history.jsonl` for fast session discovery (avoids parsing every JSONL)
- Parses JSONL events to extract metadata (model, cost estimate, message count, timestamps)
- Checks `~/.claude/sessions/*.json` for active process status (verify pid is alive via `os.kill(pid, 0)`)
- Caches parsed metadata in memory with file mtime-based invalidation
- Gracefully handles malformed/corrupted JSONL lines (skip and continue)
- Exposes functions: `list_native_sessions()`, `get_native_session(session_id)`, `get_native_session_messages(session_id, offset, limit)`

**`dashboard.py`** -- API routes for the dashboard:
- `GET /api/dashboard/sessions?source=&status=&project=&q=&page=1&page_size=50` -- Unified list from both sources. Search (`q`) searches CCR sessions via existing `session_mgr.search_sessions()`. Native session search deferred to v2 (too expensive without indexing); `q` filter applies to native session names/projects only.
- `GET /api/dashboard/sessions/{id}?offset=0&limit=100` -- Unified session detail with paginated messages
- `GET /api/dashboard/analytics` -- Summary stats (total cost, session count, top model, active sessions). "This week" means rolling last 7 days.
- `POST /api/dashboard/sessions/{id}/resume` -- Resume a native session in CCR. Request body: `{ "prompt": "string" }` (define as `DashboardResumeRequest` Pydantic model).

**Cron job management:** The dashboard frontend calls the existing `/api/cron-jobs/*` endpoints directly for all CRUD operations. No new backend endpoints needed for cron -- the existing API is complete. The dashboard adds one enriched endpoint:
- `GET /api/dashboard/cron-jobs` -- Returns all cron jobs with their last 5 runs inlined (avoids N+1 fetches from the frontend). Combines `cron_mgr.list_jobs()` with `cron_mgr.get_history(job_id, limit=5)` for each job. Response model: `CronJobWithRuns` (extends `CronJob` with `recent_runs: list[CronJobRun]`).

**Wiring:** Dashboard routes added to the existing FastAPI app in `server.py`, behind the same Tailscale auth middleware. A catch-all route at `/dashboard/{path:path}` returns `index.html` to support client-side routing.

### Frontend (React + Vite)

- **Build:** Vite produces static files (HTML, JS, CSS) in a `dashboard/dist/` directory
- **Serving:** FastAPI mounts `StaticFiles` at `/dashboard/assets` for JS/CSS, plus the catch-all route for HTML5 history routing
- **Bundling:** Built assets are included in the pip package (added to `pyproject.toml` package data). Committed to repo so `pip install` works without requiring Node.js. Contributors run `npm run build` in the dashboard directory before committing frontend changes.
- **Styling:** Tailwind CSS
- **Client-side routing:** React Router with `basename="/dashboard"`, hash routing not needed due to server catch-all
- **Error/loading states:** Skeleton loaders while fetching, error banners on API failure, "No sessions found" empty state
- **No additional runtime dependencies** on the server side

### Auth and User Filtering

- All `/api/dashboard/*` routes go through existing Tailscale WhoIs middleware
- CCR sessions: filtered by owner + collaborators matching the requesting user's Tailscale identity
- Native sessions: visible to all authenticated users as read-only (they belong to the host machine)
- `--no-auth` mode: all sessions visible (local dev)

## Views

### Navigation

Top-level nav with two tabs:
- **Sessions** (`/dashboard`) -- default view
- **Cron Jobs** (`/dashboard/cron`)

### Session List (main view at `/dashboard`)

**Summary bar (top):**
- Active sessions count
- Total cost (rolling last 7 days)
- Most-used model
- Active cron jobs count

**Session table:**
- Columns: name, project, status, cost, model, last active, source badge (CCR/Native). CCR sessions with `cron_job_id` show an additional "Cron" sub-badge linking to the parent cron job.
- Sortable by any column
- Filterable by: status, project, source type, owner
- Search: CCR sessions full-text, native sessions by name/project only (v1)
- Pagination: `page` and `page_size` query params, default 50 per page

### Session Detail (at `/dashboard/sessions/:id`)

**Header section:**
- Name, project, status badge, model, cost (with "estimated" indicator for native), duration
- Context % (CCR only)
- Git branch

**Message timeline:**
- User prompts displayed in full
- Assistant responses displayed in full (markdown rendered)
- Tool use events collapsible (show tool name + summary, expand for full input/output)
- Timestamps on each message
- Paginated: `offset`/`limit` query params, default 100 messages per page

**Resume actions:**
- CCR sessions: "Resume" button (sends prompt via existing CCR API)
- Native sessions: "Resume in CCR" button + "Copy resume command" button

### Cron Jobs (at `/dashboard/cron`)

**Cron job list:**
- Table: name, schedule (human-readable), enabled toggle, last run status, next run time, execution mode badge (SPAWN/PERSISTENT), cost (last 7 days)
- Actions per row: enable/disable toggle, "Trigger Now" button, edit, delete
- "Create Cron Job" button opens a form

**Cron job detail (at `/dashboard/cron/:id`):**
- Header: name, schedule, enabled status, execution mode, project, prompt template
- Run history table: status badge, started/completed timestamps, cost, session link, error message (if any)
- "Trigger Now" button
- Edit/delete actions
- Link to persistent session (if PERSISTENT mode)

**Cron job form (create/edit):**
- Fields: name, schedule (cron expression with human-readable preview), execution mode (SPAWN/PERSISTENT), project directory, prompt template (with variable reference showing `{{date}}`, `{{time}}`, etc.), timeout, enabled
- Session config section: model selection, skip_permissions toggle. The form constructs a `SessionCreate` object from these fields, using the prompt template as `initial_prompt` and the project directory as `session_config.project_dir`. The top-level `CronJob.project_dir` is a label (defaults to "cron") -- the actual working directory is `session_config.project_dir`.
- Validate cron expression client-side before submit

**API calls:** The frontend calls existing `/api/cron-jobs/*` endpoints directly:
- `GET /api/dashboard/cron-jobs` for the enriched list (with recent runs inlined)
- `POST /api/cron-jobs` to create
- `PATCH /api/cron-jobs/{id}` to update
- `DELETE /api/cron-jobs/{id}` to delete
- `POST /api/cron-jobs/{id}/toggle` to enable/disable
- `POST /api/cron-jobs/{id}/trigger` to trigger manually
- `GET /api/cron-jobs/{id}/history` for full run history

### Analytics Summary

Kept minimal for v1 -- displayed as the summary bar at the top of the session list. No separate analytics page, no charts.

## Resume Behavior

### CCR Sessions

"Resume" button navigates to a prompt input, which calls `POST /api/sessions/{id}/send` with the new prompt. Existing CCR flow.

### Native Sessions

"Resume in CCR" button:
1. Calls `POST /api/dashboard/sessions/{id}/resume` with `{ "prompt": "..." }`
2. Backend creates a new CCR session with `project_dir` from the native session's `cwd` and `claude_session_id` set to the native session's UUID
3. First turn uses `claude -p <prompt> --resume <native-session-uuid>`
4. Session appears in CCR session list with a "Resumed from local session" badge
5. Original native session history remains viewable separately

"Copy resume command" button: copies `claude --resume <session-uuid>` to clipboard.

## Cost Estimation for Native Sessions

Native sessions don't have explicit cost fields. Estimate from token usage in assistant events:
- Each assistant event has `usage.input_tokens` and `usage.output_tokens`
- Apply model-specific pricing from a hardcoded lookup table in `native_sessions.py`:
  - `claude-opus-4-6`: $15/$75 per 1M input/output tokens
  - `claude-sonnet-4-6`: $3/$15 per 1M input/output tokens
  - `claude-haiku-4-5`: $0.80/$4 per 1M input/output tokens
  - Unknown models: use sonnet pricing as fallback
- Display as "~$X.XX (estimated)" to distinguish from CCR's exact tracking
- Table can be updated as new models are released

## Performance Considerations

- **JSONL parsing:** Native sessions can be large (1MB+). Parse lazily -- extract metadata on list, full messages only on detail view.
- **Metadata cache:** In-memory dict keyed by file path, invalidated when file mtime changes. No persistent cache file.
- **Malformed JSONL:** Skip corrupted lines, log a warning, continue parsing. Don't fail the entire session.
- **Pagination:** Both list and detail views paginated to avoid loading all data at once.
- **Session count:** ~131 JSONL files currently. Linear scan is fine for this scale. If it grows past 1000, add an index.

## File Structure

```
src/claude_code_remote/
├── native_sessions.py     (new: JSONL parsing and discovery)
├── dashboard.py           (new: dashboard API routes)
├── models.py              (modified: add DashboardSession, DashboardSessionSummary, DashboardResumeRequest, CronJobWithRuns)
├── server.py              (modified: mount dashboard routes + static files + catch-all)
└── dashboard/             (new: React frontend)
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.ts
    ├── index.html
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── api.ts          (API client)
    │   ├── types.ts         (TypeScript types matching unified model)
    │   ├── pages/
    │   │   ├── SessionList.tsx
    │   │   ├── SessionDetail.tsx
    │   │   ├── CronList.tsx
    │   │   └── CronDetail.tsx
    │   └── components/
    │       ├── SummaryBar.tsx
    │       ├── SessionTable.tsx
    │       ├── MessageTimeline.tsx
    │       ├── ResumeActions.tsx
    │       ├── CronJobTable.tsx
    │       ├── CronJobForm.tsx
    │       └── CronRunHistory.tsx
    └── dist/               (built output, committed to repo)
```

## Out of Scope for v1

- Charts or time-series visualizations
- Session creation from the dashboard (cron job creation is in scope)
- Real-time WebSocket updates (polling is fine for v1)
- Editing or deleting sessions from the dashboard
- Multi-machine session aggregation
- Export/download functionality
- Full-text search over native session message content (search by name/project only in v1)
