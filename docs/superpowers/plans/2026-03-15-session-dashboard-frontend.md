# Session Dashboard Frontend Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a React SPA dashboard served by the CCR FastAPI server at `/dashboard`, with session browsing, cron job management, and analytics.

**Architecture:** React + Vite + Tailwind CSS SPA. Built to static files in `src/claude_code_remote/dashboard/dist/`, served by FastAPI via StaticFiles mount and a catch-all route for HTML5 history routing. Calls `/api/dashboard/*` and `/api/cron-jobs/*` endpoints.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS v4, React Router v7

**Spec:** `docs/superpowers/specs/2026-03-15-session-dashboard-design.md`
**Backend plan:** `docs/superpowers/plans/2026-03-15-session-dashboard-backend.md`

**Prerequisite:** Plan A (backend) must be implemented first. The frontend depends on the `/api/dashboard/*` endpoints.

---

## File Map

All frontend files live under `src/claude_code_remote/dashboard/`.

| File | Purpose |
|------|---------|
| `package.json` | Dependencies and scripts |
| `tsconfig.json` | TypeScript configuration |
| `vite.config.ts` | Vite build config with `/dashboard` base path |
| `index.html` | SPA entry point |
| `src/main.tsx` | React entry point |
| `src/App.tsx` | Root component with React Router |
| `src/api.ts` | API client for all backend calls |
| `src/types.ts` | TypeScript types matching backend models |
| `src/pages/SessionList.tsx` | Session list with summary bar, filters, table |
| `src/pages/SessionDetail.tsx` | Session detail with message timeline |
| `src/pages/CronList.tsx` | Cron job list with actions |
| `src/pages/CronDetail.tsx` | Cron job detail with run history |
| `src/components/SummaryBar.tsx` | Analytics summary bar |
| `src/components/SessionTable.tsx` | Sortable, filterable session table |
| `src/components/MessageTimeline.tsx` | Message display with collapsible tool use |
| `src/components/ResumeActions.tsx` | Resume buttons for CCR and native sessions |
| `src/components/CronJobTable.tsx` | Cron job table with toggle/trigger actions |
| `src/components/CronJobForm.tsx` | Create/edit cron job form |
| `src/components/CronRunHistory.tsx` | Run history table for cron detail |

Server-side files modified:

| File | Purpose |
|------|---------|
| `src/claude_code_remote/server.py` | Mount static files + catch-all route |
| `pyproject.toml` | Add `dashboard/dist/` to package data |

---

## Chunk 1: Project Scaffold and Routing

### Task 1: Initialize Vite + React + TypeScript project

**Files:**
- Create: `src/claude_code_remote/dashboard/package.json`
- Create: `src/claude_code_remote/dashboard/tsconfig.json`
- Create: `src/claude_code_remote/dashboard/vite.config.ts`
- Create: `src/claude_code_remote/dashboard/index.html`

- [ ] **Step 1: Create package.json**

Create `src/claude_code_remote/dashboard/package.json`:

```json
{
  "name": "ccr-dashboard",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router": "^7.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.6.0",
    "vite": "^6.0.0",
    "@tailwindcss/vite": "^4.0.0",
    "tailwindcss": "^4.0.0"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

Create `src/claude_code_remote/dashboard/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noUncheckedSideEffectImports": true
  },
  "include": ["src"]
}
```

- [ ] **Step 3: Create vite.config.ts**

Create `src/claude_code_remote/dashboard/vite.config.ts`:

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/dashboard/",
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
    },
  },
});
```

- [ ] **Step 4: Create index.html**

Create `src/claude_code_remote/dashboard/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>CCR Dashboard</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Install dependencies**

Run: `cd src/claude_code_remote/dashboard && npm install`
Expected: `node_modules/` created, no errors

- [ ] **Step 6: Commit**

```bash
git add src/claude_code_remote/dashboard/package.json src/claude_code_remote/dashboard/package-lock.json src/claude_code_remote/dashboard/tsconfig.json src/claude_code_remote/dashboard/vite.config.ts src/claude_code_remote/dashboard/index.html
git commit -m "feat(dashboard): scaffold Vite + React + TypeScript project"
```

---

### Task 2: Add types, API client, and app shell

**Files:**
- Create: `src/claude_code_remote/dashboard/src/main.tsx`
- Create: `src/claude_code_remote/dashboard/src/app.css`
- Create: `src/claude_code_remote/dashboard/src/App.tsx`
- Create: `src/claude_code_remote/dashboard/src/types.ts`
- Create: `src/claude_code_remote/dashboard/src/api.ts`

- [ ] **Step 1: Create types.ts**

Create `src/claude_code_remote/dashboard/src/types.ts`:

```typescript
export interface DashboardSessionSummary {
  id: string;
  name: string;
  project_dir: string;
  source: "ccr" | "native";
  status: string;
  current_model: string | null;
  total_cost_usd: number;
  cost_is_estimated: boolean;
  message_count: number;
  context_percent: number | null;
  git_branch: string | null;
  created_at: string;
  updated_at: string;
  owner: string | null;
  claude_session_id: string | null;
  cron_job_id: string | null;
}

export interface DashboardSession extends DashboardSessionSummary {
  messages: Record<string, unknown>[];
  total_messages: number;
}

export interface SessionListResponse {
  sessions: DashboardSessionSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface DashboardAnalytics {
  active_sessions: number;
  total_cost_7d: number;
  top_model: string | null;
  active_cron_jobs: number;
}

export interface CronJobRun {
  id: string;
  cron_job_id: string;
  session_id: string | null;
  status: "success" | "error" | "running" | "timeout";
  started_at: string;
  completed_at: string | null;
  cost_usd: number;
  error_message: string | null;
}

export interface CronJob {
  id: string;
  name: string;
  schedule: string;
  enabled: boolean;
  execution_mode: "spawn" | "persistent";
  session_config: {
    name: string;
    project_dir: string;
    initial_prompt: string;
    model?: string | null;
    skip_permissions?: boolean;
  };
  persistent_session_id: string | null;
  project_dir: string;
  timeout_minutes: number | null;
  prompt_template: string | null;
  created_at: string;
  updated_at: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
}

export interface CronJobWithRuns extends CronJob {
  recent_runs: CronJobRun[];
}

export interface CronJobCreateRequest {
  name: string;
  schedule: string;
  execution_mode: "spawn" | "persistent";
  session_config: {
    name: string;
    project_dir: string;
    initial_prompt: string;
    model?: string | null;
    skip_permissions?: boolean;
  };
  project_dir?: string;
  timeout_minutes?: number | null;
  prompt_template?: string | null;
  enabled?: boolean;
}
```

- [ ] **Step 2: Create api.ts**

Create `src/claude_code_remote/dashboard/src/api.ts`:

```typescript
import type {
  SessionListResponse,
  DashboardSession,
  DashboardAnalytics,
  CronJobWithRuns,
  CronJob,
  CronJobCreateRequest,
  CronJobRun,
} from "./types";

const BASE = "/api";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, init);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText}`);
  }
  return resp.json();
}

// --- Sessions ---

export function listSessions(params?: {
  source?: string;
  status?: string;
  project?: string;
  q?: string;
  page?: number;
  page_size?: number;
}): Promise<SessionListResponse> {
  const sp = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
    }
  }
  return fetchJson(`${BASE}/dashboard/sessions?${sp}`);
}

export function getSession(
  id: string,
  offset = 0,
  limit = 100
): Promise<DashboardSession> {
  return fetchJson(
    `${BASE}/dashboard/sessions/${id}?offset=${offset}&limit=${limit}`
  );
}

export function getAnalytics(): Promise<DashboardAnalytics> {
  return fetchJson(`${BASE}/dashboard/analytics`);
}

export function resumeNativeSession(
  id: string,
  prompt: string
): Promise<{ session_id: string; status: string }> {
  return fetchJson(`${BASE}/dashboard/sessions/${id}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });
}

// --- Cron Jobs ---

export function listCronJobs(): Promise<CronJobWithRuns[]> {
  return fetchJson(`${BASE}/dashboard/cron-jobs`);
}

export function getCronJob(id: string): Promise<CronJob> {
  return fetchJson(`${BASE}/cron-jobs/${id}`);
}

export function createCronJob(data: CronJobCreateRequest): Promise<CronJob> {
  return fetchJson(`${BASE}/cron-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function updateCronJob(
  id: string,
  data: Partial<CronJobCreateRequest>
): Promise<CronJob> {
  return fetchJson(`${BASE}/cron-jobs/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function deleteCronJob(id: string): Promise<void> {
  return fetch(`${BASE}/cron-jobs/${id}`, { method: "DELETE" }).then(() => {});
}

export function toggleCronJob(id: string): Promise<CronJob> {
  return fetchJson(`${BASE}/cron-jobs/${id}/toggle`, { method: "POST" });
}

export function triggerCronJob(
  id: string
): Promise<{ status: string }> {
  return fetchJson(`${BASE}/cron-jobs/${id}/trigger`, { method: "POST" });
}

export function getCronJobHistory(
  id: string,
  limit = 50,
  offset = 0
): Promise<CronJobRun[]> {
  return fetchJson(
    `${BASE}/cron-jobs/${id}/history?limit=${limit}&offset=${offset}`
  );
}
```

- [ ] **Step 3: Create app.css**

Create `src/claude_code_remote/dashboard/src/app.css`:

```css
@import "tailwindcss";
```

- [ ] **Step 4: Create main.tsx**

Create `src/claude_code_remote/dashboard/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import "./app.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename="/dashboard">
      <App />
    </BrowserRouter>
  </StrictMode>
);
```

- [ ] **Step 5: Create App.tsx with routing**

Create `src/claude_code_remote/dashboard/src/App.tsx`:

```tsx
import { Routes, Route, NavLink } from "react-router";

import SessionList from "./pages/SessionList";
import SessionDetail from "./pages/SessionDetail";
import CronList from "./pages/CronList";
import CronDetail from "./pages/CronDetail";

function Nav() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 text-sm font-medium rounded-md transition-colors ${
      isActive
        ? "bg-zinc-800 text-white"
        : "text-zinc-400 hover:text-white hover:bg-zinc-800/50"
    }`;

  return (
    <header className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-6">
        <h1 className="text-lg font-semibold text-white tracking-tight">
          CCR Dashboard
        </h1>
        <nav className="flex gap-1">
          <NavLink to="/" end className={linkClass}>
            Sessions
          </NavLink>
          <NavLink to="/cron" className={linkClass}>
            Cron Jobs
          </NavLink>
        </nav>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <Nav />
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Routes>
          <Route index element={<SessionList />} />
          <Route path="sessions/:id" element={<SessionDetail />} />
          <Route path="cron" element={<CronList />} />
          <Route path="cron/:id" element={<CronDetail />} />
        </Routes>
      </main>
    </div>
  );
}
```

- [ ] **Step 6: Create placeholder pages**

Create `src/claude_code_remote/dashboard/src/pages/SessionList.tsx`:

```tsx
export default function SessionList() {
  return <div>Session list placeholder</div>;
}
```

Create `src/claude_code_remote/dashboard/src/pages/SessionDetail.tsx`:

```tsx
export default function SessionDetail() {
  return <div>Session detail placeholder</div>;
}
```

Create `src/claude_code_remote/dashboard/src/pages/CronList.tsx`:

```tsx
export default function CronList() {
  return <div>Cron list placeholder</div>;
}
```

Create `src/claude_code_remote/dashboard/src/pages/CronDetail.tsx`:

```tsx
export default function CronDetail() {
  return <div>Cron detail placeholder</div>;
}
```

- [ ] **Step 7: Verify build**

Run: `cd src/claude_code_remote/dashboard && npm run build`
Expected: `dist/` created with `index.html` and JS/CSS assets

- [ ] **Step 8: Commit**

```bash
git add src/claude_code_remote/dashboard/src/
git commit -m "feat(dashboard): add types, API client, app shell with routing"
```

---

### Task 3: Mount static files in FastAPI server

**Files:**
- Modify: `src/claude_code_remote/server.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add static file serving and catch-all to server.py**

Add import at top of `server.py` (after `from pathlib import Path`):

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
```

Then add after the `app.include_router(dashboard_router, prefix="/api/dashboard")` line (added in Plan A Task 4):

```python
    # Dashboard SPA static files
    dashboard_dist = Path(__file__).parent / "dashboard" / "dist"
    if dashboard_dist.exists():
        app.mount(
            "/dashboard/assets",
            StaticFiles(directory=dashboard_dist / "assets"),
            name="dashboard-assets",
        )

        @app.get("/dashboard/{path:path}")
        @app.get("/dashboard")
        async def dashboard_spa(path: str = ""):
            return FileResponse(dashboard_dist / "index.html")
```

- [ ] **Step 2: Add dashboard/dist to pyproject.toml package data**

Add to `pyproject.toml` after the `[project.scripts]` section:

```toml

[tool.hatch.build.targets.wheel]
packages = ["src/claude_code_remote"]

[tool.hatch.build.targets.wheel.force-include]
"src/claude_code_remote/dashboard/dist" = "claude_code_remote/dashboard/dist"
```

- [ ] **Step 3: Add .gitignore for dashboard node_modules**

Create `src/claude_code_remote/dashboard/.gitignore`:

```
node_modules/
```

- [ ] **Step 4: Verify server starts with dashboard**

Run: `ccr start --no-auth` then `curl -s http://127.0.0.1:8080/dashboard/ | head -5`
Expected: HTML with `<div id="root"></div>`

Run: `ccr stop`

- [ ] **Step 5: Commit**

```bash
git add src/claude_code_remote/server.py pyproject.toml src/claude_code_remote/dashboard/.gitignore
git commit -m "feat(dashboard): mount SPA static files and catch-all route"
```

---

## Chunk 2: Session Views

### Task 4: SummaryBar component

**Files:**
- Create: `src/claude_code_remote/dashboard/src/components/SummaryBar.tsx`

- [ ] **Step 1: Implement SummaryBar**

Create `src/claude_code_remote/dashboard/src/components/SummaryBar.tsx`:

```tsx
import type { DashboardAnalytics } from "../types";

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-3">
      <p className="text-xs text-zinc-500 uppercase tracking-wide">{label}</p>
      <p className="mt-1 text-xl font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

export default function SummaryBar({
  analytics,
}: {
  analytics: DashboardAnalytics | null;
}) {
  if (!analytics) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="h-[72px] rounded-lg bg-zinc-900 border border-zinc-800 animate-pulse"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <StatCard label="Active Sessions" value={analytics.active_sessions} />
      <StatCard
        label="Cost (7d)"
        value={`$${analytics.total_cost_7d.toFixed(2)}`}
      />
      <StatCard label="Top Model" value={analytics.top_model ?? "—"} />
      <StatCard label="Cron Jobs" value={analytics.active_cron_jobs} />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/claude_code_remote/dashboard/src/components/SummaryBar.tsx
git commit -m "feat(dashboard): add SummaryBar analytics component"
```

---

### Task 5: SessionTable component

**Files:**
- Create: `src/claude_code_remote/dashboard/src/components/SessionTable.tsx`

- [ ] **Step 1: Implement SessionTable**

Create `src/claude_code_remote/dashboard/src/components/SessionTable.tsx`:

```tsx
import { Link } from "react-router";
import type { DashboardSessionSummary } from "../types";

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: "bg-green-900/50 text-green-400 border-green-800",
    idle: "bg-blue-900/50 text-blue-400 border-blue-800",
    active: "bg-green-900/50 text-green-400 border-green-800",
    completed: "bg-zinc-800 text-zinc-400 border-zinc-700",
    error: "bg-red-900/50 text-red-400 border-red-800",
    paused: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
    awaiting_approval: "bg-orange-900/50 text-orange-400 border-orange-800",
  };
  const cls = colors[status] ?? "bg-zinc-800 text-zinc-400 border-zinc-700";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {status}
    </span>
  );
}

function SourceBadge({
  source,
  cronJobId,
}: {
  source: string;
  cronJobId: string | null;
}) {
  const cls =
    source === "native"
      ? "bg-purple-900/50 text-purple-400 border-purple-800"
      : "bg-sky-900/50 text-sky-400 border-sky-800";
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}
      >
        {source === "native" ? "Native" : "CCR"}
      </span>
      {cronJobId && (
        <Link
          to={`/cron/${cronJobId}`}
          className="inline-flex items-center rounded-full border border-amber-800 bg-amber-900/50 px-2 py-0.5 text-xs font-medium text-amber-400 hover:bg-amber-900"
        >
          Cron
        </Link>
      )}
    </span>
  );
}

function timeAgo(dateStr: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

type SortKey = "name" | "updated_at" | "total_cost_usd" | "status";

export default function SessionTable({
  sessions,
  sortKey,
  sortDesc,
  onSort,
}: {
  sessions: DashboardSessionSummary[];
  sortKey: SortKey;
  sortDesc: boolean;
  onSort: (key: SortKey) => void;
}) {
  const headers: { key: SortKey; label: string }[] = [
    { key: "name", label: "Name" },
    { key: "status", label: "Status" },
    { key: "total_cost_usd", label: "Cost" },
    { key: "updated_at", label: "Last Active" },
  ];

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900/50">
            {headers.map((h) => (
              <th
                key={h.key}
                onClick={() => onSort(h.key)}
                className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide cursor-pointer hover:text-zinc-300"
              >
                {h.label}
                {sortKey === h.key && (
                  <span className="ml-1">{sortDesc ? "↓" : "↑"}</span>
                )}
              </th>
            ))}
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Model
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Source
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {sessions.map((s) => (
            <tr
              key={s.id}
              className="hover:bg-zinc-900/50 transition-colors"
            >
              <td className="px-4 py-3">
                <Link
                  to={`/sessions/${s.id}`}
                  className="text-zinc-100 hover:text-white font-medium"
                >
                  {s.name}
                </Link>
                <p className="text-xs text-zinc-500 mt-0.5 truncate max-w-[200px]">
                  {s.project_dir}
                </p>
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={s.status} />
              </td>
              <td className="px-4 py-3 text-zinc-300 tabular-nums">
                {s.cost_is_estimated && "~"}${s.total_cost_usd.toFixed(2)}
              </td>
              <td className="px-4 py-3 text-zinc-400">
                {timeAgo(s.updated_at)}
              </td>
              <td className="px-4 py-3 text-zinc-400 text-xs">
                {s.current_model ?? "—"}
              </td>
              <td className="px-4 py-3">
                <SourceBadge source={s.source} cronJobId={s.cron_job_id} />
              </td>
            </tr>
          ))}
          {sessions.length === 0 && (
            <tr>
              <td
                colSpan={6}
                className="px-4 py-8 text-center text-zinc-500"
              >
                No sessions found
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/claude_code_remote/dashboard/src/components/SessionTable.tsx
git commit -m "feat(dashboard): add SessionTable component with sorting and badges"
```

---

### Task 6: SessionList page

**Files:**
- Modify: `src/claude_code_remote/dashboard/src/pages/SessionList.tsx`

- [ ] **Step 1: Implement SessionList page**

Replace `src/claude_code_remote/dashboard/src/pages/SessionList.tsx`:

```tsx
import { useEffect, useState, useCallback } from "react";
import type { DashboardSessionSummary, DashboardAnalytics } from "../types";
import { listSessions, getAnalytics } from "../api";
import SummaryBar from "../components/SummaryBar";
import SessionTable from "../components/SessionTable";

type SortKey = "name" | "updated_at" | "total_cost_usd" | "status";

export default function SessionList() {
  const [sessions, setSessions] = useState<DashboardSessionSummary[]>([]);
  const [analytics, setAnalytics] = useState<DashboardAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<string>("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("updated_at");
  const [sortDesc, setSortDesc] = useState(true);
  const pageSize = 50;

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [sessResp, analyticsResp] = await Promise.all([
        listSessions({
          source: source || undefined,
          q: search || undefined,
          page,
          page_size: pageSize,
        }),
        getAnalytics(),
      ]);
      setSessions(sessResp.sessions);
      setTotal(sessResp.total);
      setAnalytics(analyticsResp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [source, search, page]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const sorted = [...sessions].sort((a, b) => {
    let cmp = 0;
    if (sortKey === "name") cmp = a.name.localeCompare(b.name);
    else if (sortKey === "updated_at")
      cmp =
        new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime();
    else if (sortKey === "total_cost_usd")
      cmp = a.total_cost_usd - b.total_cost_usd;
    else if (sortKey === "status") cmp = a.status.localeCompare(b.status);
    return sortDesc ? -cmp : cmp;
  });

  function handleSort(key: SortKey) {
    if (key === sortKey) setSortDesc(!sortDesc);
    else {
      setSortKey(key);
      setSortDesc(true);
    }
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <div>
      <SummaryBar analytics={analytics} />

      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="Search sessions..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          className="rounded-md bg-zinc-900 border border-zinc-800 px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600 w-64"
        />
        <select
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            setPage(1);
          }}
          className="rounded-md bg-zinc-900 border border-zinc-800 px-3 py-1.5 text-sm text-zinc-100 focus:outline-none focus:ring-1 focus:ring-zinc-600"
        >
          <option value="">All sources</option>
          <option value="ccr">CCR</option>
          <option value="native">Native</option>
        </select>
      </div>

      {error && (
        <div className="mb-4 rounded-md bg-red-900/30 border border-red-800 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {loading && !sessions.length ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 h-64 animate-pulse" />
      ) : (
        <SessionTable
          sessions={sorted}
          sortKey={sortKey}
          sortDesc={sortDesc}
          onSort={handleSort}
        />
      )}

      {totalPages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm text-zinc-500">
          <span>
            {total} sessions, page {page} of {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page === 1}
              className="px-3 py-1 rounded-md bg-zinc-900 border border-zinc-800 disabled:opacity-50 hover:bg-zinc-800"
            >
              Prev
            </button>
            <button
              onClick={() => setPage(Math.min(totalPages, page + 1))}
              disabled={page === totalPages}
              className="px-3 py-1 rounded-md bg-zinc-900 border border-zinc-800 disabled:opacity-50 hover:bg-zinc-800"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd src/claude_code_remote/dashboard && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/dashboard/src/
git commit -m "feat(dashboard): add SessionList page with filtering, search, pagination"
```

---

### Task 7: MessageTimeline and ResumeActions components

**Files:**
- Create: `src/claude_code_remote/dashboard/src/components/MessageTimeline.tsx`
- Create: `src/claude_code_remote/dashboard/src/components/ResumeActions.tsx`

- [ ] **Step 1: Implement MessageTimeline**

Create `src/claude_code_remote/dashboard/src/components/MessageTimeline.tsx`:

```tsx
import { useState } from "react";

function MessageBubble({ event }: { event: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const type = event.type as string;
  const message = event.message as Record<string, unknown> | undefined;
  const timestamp = event.timestamp as string | undefined;

  const time = timestamp
    ? new Date(timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  if (type === "user") {
    const content =
      (message?.content as string) ?? JSON.stringify(message?.content);
    return (
      <div className="flex gap-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-900/50 border border-blue-800 flex items-center justify-center text-xs text-blue-400">
          U
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-zinc-500 mb-1">{time}</p>
          <div className="rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-3 text-sm text-zinc-200 whitespace-pre-wrap">
            {content}
          </div>
        </div>
      </div>
    );
  }

  if (type === "assistant") {
    const contentArr = message?.content as
      | { type: string; text?: string; name?: string; input?: unknown }[]
      | undefined;
    const model = message?.model as string | undefined;

    return (
      <div className="flex gap-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-900/50 border border-emerald-800 flex items-center justify-center text-xs text-emerald-400">
          A
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-zinc-500 mb-1">
            {time}
            {model && (
              <span className="ml-2 text-zinc-600">{model}</span>
            )}
          </p>
          <div className="rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-3 text-sm space-y-2">
            {contentArr?.map((block, i) => {
              if (block.type === "text") {
                return (
                  <div key={i} className="text-zinc-200 whitespace-pre-wrap">
                    {block.text}
                  </div>
                );
              }
              if (block.type === "tool_use") {
                return (
                  <div key={i}>
                    <button
                      onClick={() => setExpanded(!expanded)}
                      className="text-xs text-amber-400 hover:text-amber-300 font-mono"
                    >
                      {expanded ? "▼" : "▶"} {block.name}
                    </button>
                    {expanded && (
                      <pre className="mt-1 text-xs text-zinc-400 overflow-x-auto bg-zinc-950 rounded p-2">
                        {JSON.stringify(block.input, null, 2)}
                      </pre>
                    )}
                  </div>
                );
              }
              return null;
            })}
          </div>
        </div>
      </div>
    );
  }

  // System messages
  return (
    <div className="flex gap-3">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center text-xs text-zinc-500">
        S
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-zinc-500 mb-1">{time}</p>
        <div className="rounded-lg bg-zinc-900/50 border border-zinc-800 px-4 py-2 text-xs text-zinc-500">
          {(event as Record<string, unknown>).content as string ??
            "System event"}
        </div>
      </div>
    </div>
  );
}

export default function MessageTimeline({
  messages,
}: {
  messages: Record<string, unknown>[];
}) {
  if (!messages.length) {
    return (
      <p className="text-zinc-500 text-sm py-8 text-center">No messages</p>
    );
  }
  return (
    <div className="space-y-4">
      {messages.map((msg, i) => (
        <MessageBubble key={i} event={msg} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Implement ResumeActions**

Create `src/claude_code_remote/dashboard/src/components/ResumeActions.tsx`:

```tsx
import { useState } from "react";
import type { DashboardSession } from "../types";
import { resumeNativeSession } from "../api";

export default function ResumeActions({
  session,
}: {
  session: DashboardSession;
}) {
  const [prompt, setPrompt] = useState("");
  const [resuming, setResuming] = useState(false);
  const [showInput, setShowInput] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function handleResume() {
    if (!prompt.trim()) return;
    setResuming(true);
    try {
      if (session.source === "native") {
        const resp = await resumeNativeSession(session.id, prompt);
        setResult(`Created CCR session: ${resp.session_id}`);
      } else {
        // CCR sessions use the existing sessions API, not dashboard API
        const resp = await fetch(`/api/sessions/${session.id}/send`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt }),
        });
        if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
        setResult("Prompt sent");
      }
    } catch {
      setResult("Failed to resume");
    } finally {
      setResuming(false);
    }
  }

  function copyCommand() {
    const cmd = `claude --resume ${session.claude_session_id}`;
    navigator.clipboard.writeText(cmd);
    setResult("Copied to clipboard");
    setTimeout(() => setResult(null), 2000);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setShowInput(!showInput)}
          className="rounded-md bg-zinc-800 border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-700"
        >
          {session.source === "native" ? "Resume in CCR" : "Resume"}
        </button>
        {session.source === "native" && (
          <button
            onClick={copyCommand}
            className="rounded-md bg-zinc-900 border border-zinc-800 px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
          >
            Copy resume command
          </button>
        )}
      </div>
      {showInput && (
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="Enter prompt..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleResume()}
            className="flex-1 rounded-md bg-zinc-900 border border-zinc-800 px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600"
          />
          <button
            onClick={handleResume}
            disabled={resuming || !prompt.trim()}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {resuming ? "Sending..." : "Send"}
          </button>
        </div>
      )}
      {result && <p className="text-xs text-zinc-500">{result}</p>}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/dashboard/src/components/MessageTimeline.tsx src/claude_code_remote/dashboard/src/components/ResumeActions.tsx
git commit -m "feat(dashboard): add MessageTimeline and ResumeActions components"
```

---

### Task 8: SessionDetail page

**Files:**
- Modify: `src/claude_code_remote/dashboard/src/pages/SessionDetail.tsx`

- [ ] **Step 1: Implement SessionDetail**

Replace `src/claude_code_remote/dashboard/src/pages/SessionDetail.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router";
import type { DashboardSession } from "../types";
import { getSession } from "../api";
import MessageTimeline from "../components/MessageTimeline";
import ResumeActions from "../components/ResumeActions";

export default function SessionDetail() {
  const { id } = useParams<{ id: string }>();
  const [session, setSession] = useState<DashboardSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 100;

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    getSession(id, offset, limit)
      .then(setSession)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id, offset]);

  if (loading)
    return (
      <div className="h-64 rounded-lg bg-zinc-900 border border-zinc-800 animate-pulse" />
    );
  if (error)
    return (
      <div className="rounded-md bg-red-900/30 border border-red-800 px-4 py-3 text-sm text-red-400">
        {error}
      </div>
    );
  if (!session) return null;

  const statusColors: Record<string, string> = {
    running: "text-green-400",
    idle: "text-blue-400",
    active: "text-green-400",
    completed: "text-zinc-400",
    error: "text-red-400",
  };

  return (
    <div>
      <Link
        to="/"
        className="text-sm text-zinc-500 hover:text-zinc-300 mb-4 inline-block"
      >
        ← Back to sessions
      </Link>

      <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-5 mb-6">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-xl font-semibold text-zinc-100">
              {session.name}
            </h2>
            <p className="text-sm text-zinc-500 mt-1">{session.project_dir}</p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span
              className={
                statusColors[session.status] ?? "text-zinc-400"
              }
            >
              {session.status}
            </span>
            <span className="text-zinc-500">
              {session.source === "native" ? "Native" : "CCR"}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-4 text-sm">
          <div>
            <p className="text-zinc-500">Model</p>
            <p className="text-zinc-200">{session.current_model ?? "—"}</p>
          </div>
          <div>
            <p className="text-zinc-500">Cost</p>
            <p className="text-zinc-200">
              {session.cost_is_estimated && "~"}$
              {session.total_cost_usd.toFixed(2)}
              {session.cost_is_estimated && (
                <span className="text-zinc-600 ml-1">(est.)</span>
              )}
            </p>
          </div>
          <div>
            <p className="text-zinc-500">Messages</p>
            <p className="text-zinc-200">{session.total_messages}</p>
          </div>
          {session.context_percent != null && session.context_percent > 0 && (
            <div>
              <p className="text-zinc-500">Context</p>
              <p className="text-zinc-200">{session.context_percent}%</p>
            </div>
          )}
          {session.git_branch && (
            <div>
              <p className="text-zinc-500">Branch</p>
              <p className="text-zinc-200 font-mono text-xs">
                {session.git_branch}
              </p>
            </div>
          )}
        </div>

        <div className="mt-4 pt-4 border-t border-zinc-800">
          <ResumeActions session={session} />
        </div>
      </div>

      <MessageTimeline messages={session.messages} />

      {session.total_messages > limit && (
        <div className="mt-4 flex items-center justify-between text-sm text-zinc-500">
          <span>
            Showing {offset + 1}–{Math.min(offset + limit, session.total_messages)}{" "}
            of {session.total_messages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - limit))}
              disabled={offset === 0}
              className="px-3 py-1 rounded-md bg-zinc-900 border border-zinc-800 disabled:opacity-50 hover:bg-zinc-800"
            >
              Prev
            </button>
            <button
              onClick={() => setOffset(offset + limit)}
              disabled={offset + limit >= session.total_messages}
              className="px-3 py-1 rounded-md bg-zinc-900 border border-zinc-800 disabled:opacity-50 hover:bg-zinc-800"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd src/claude_code_remote/dashboard && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/dashboard/src/pages/SessionDetail.tsx
git commit -m "feat(dashboard): add SessionDetail page with message timeline and resume"
```

---

## Chunk 3: Cron Views

### Task 9: CronJobTable and CronRunHistory components

**Files:**
- Create: `src/claude_code_remote/dashboard/src/components/CronJobTable.tsx`
- Create: `src/claude_code_remote/dashboard/src/components/CronRunHistory.tsx`

- [ ] **Step 1: Implement CronJobTable**

Create `src/claude_code_remote/dashboard/src/components/CronJobTable.tsx`:

```tsx
import { Link } from "react-router";
import type { CronJobWithRuns } from "../types";

function RunStatusDot({ status }: { status: string | null }) {
  const colors: Record<string, string> = {
    success: "bg-green-400",
    error: "bg-red-400",
    running: "bg-blue-400 animate-pulse",
    timeout: "bg-yellow-400",
  };
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${colors[status ?? ""] ?? "bg-zinc-600"}`}
    />
  );
}

export default function CronJobTable({
  jobs,
  onToggle,
  onTrigger,
  onDelete,
}: {
  jobs: CronJobWithRuns[];
  onToggle: (id: string) => void;
  onTrigger: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900/50">
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Name
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Schedule
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Status
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Last Run
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Next Run
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Mode
            </th>
            <th className="px-4 py-3 text-right text-xs font-medium text-zinc-500 uppercase tracking-wide">
              Actions
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {jobs.map((job) => (
            <tr key={job.id} className="hover:bg-zinc-900/50 transition-colors">
              <td className="px-4 py-3">
                <Link
                  to={`/cron/${job.id}`}
                  className="text-zinc-100 hover:text-white font-medium"
                >
                  {job.name}
                </Link>
              </td>
              <td className="px-4 py-3 font-mono text-xs text-zinc-400">
                {job.schedule}
              </td>
              <td className="px-4 py-3">
                <span className="flex items-center gap-2">
                  <RunStatusDot status={job.last_run_status} />
                  <button
                    onClick={() => onToggle(job.id)}
                    className={`text-xs px-2 py-0.5 rounded-full border ${
                      job.enabled
                        ? "border-green-800 bg-green-900/50 text-green-400"
                        : "border-zinc-700 bg-zinc-800 text-zinc-500"
                    }`}
                  >
                    {job.enabled ? "Enabled" : "Disabled"}
                  </button>
                </span>
              </td>
              <td className="px-4 py-3 text-zinc-400 text-xs">
                {job.last_run_at
                  ? new Date(job.last_run_at).toLocaleString()
                  : "Never"}
              </td>
              <td className="px-4 py-3 text-zinc-400 text-xs">
                {job.next_run_at
                  ? new Date(job.next_run_at).toLocaleString()
                  : "—"}
              </td>
              <td className="px-4 py-3">
                <span className="text-xs rounded-full border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-zinc-400">
                  {job.execution_mode}
                </span>
              </td>
              <td className="px-4 py-3 text-right">
                <div className="flex items-center justify-end gap-1">
                  <button
                    onClick={() => onTrigger(job.id)}
                    className="text-xs text-zinc-400 hover:text-white px-2 py-1 rounded hover:bg-zinc-800"
                  >
                    Trigger
                  </button>
                  <button
                    onClick={() => onDelete(job.id)}
                    className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-zinc-800"
                  >
                    Delete
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {jobs.length === 0 && (
            <tr>
              <td colSpan={7} className="px-4 py-8 text-center text-zinc-500">
                No cron jobs configured
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Implement CronRunHistory**

Create `src/claude_code_remote/dashboard/src/components/CronRunHistory.tsx`:

```tsx
import { Link } from "react-router";
import type { CronJobRun } from "../types";

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    success: "bg-green-900/50 text-green-400 border-green-800",
    error: "bg-red-900/50 text-red-400 border-red-800",
    running: "bg-blue-900/50 text-blue-400 border-blue-800",
    timeout: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls[status] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"}`}
    >
      {status}
    </span>
  );
}

export default function CronRunHistory({ runs }: { runs: CronJobRun[] }) {
  if (!runs.length) {
    return <p className="text-zinc-500 text-sm py-4">No run history</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900/50">
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">
              Status
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">
              Started
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">
              Completed
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">
              Cost
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">
              Session
            </th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">
              Error
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {runs.map((run) => (
            <tr key={run.id} className="hover:bg-zinc-900/50">
              <td className="px-4 py-3">
                <StatusBadge status={run.status} />
              </td>
              <td className="px-4 py-3 text-zinc-400 text-xs">
                {new Date(run.started_at).toLocaleString()}
              </td>
              <td className="px-4 py-3 text-zinc-400 text-xs">
                {run.completed_at
                  ? new Date(run.completed_at).toLocaleString()
                  : "—"}
              </td>
              <td className="px-4 py-3 text-zinc-300 tabular-nums">
                ${run.cost_usd.toFixed(2)}
              </td>
              <td className="px-4 py-3">
                {run.session_id ? (
                  <Link
                    to={`/sessions/${run.session_id}`}
                    className="text-xs text-sky-400 hover:text-sky-300 font-mono"
                  >
                    {run.session_id.slice(0, 8)}
                  </Link>
                ) : (
                  <span className="text-zinc-600">—</span>
                )}
              </td>
              <td className="px-4 py-3 text-xs text-red-400 max-w-[200px] truncate">
                {run.error_message ?? ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/dashboard/src/components/CronJobTable.tsx src/claude_code_remote/dashboard/src/components/CronRunHistory.tsx
git commit -m "feat(dashboard): add CronJobTable and CronRunHistory components"
```

---

### Task 10: CronJobForm component

**Files:**
- Create: `src/claude_code_remote/dashboard/src/components/CronJobForm.tsx`

- [ ] **Step 1: Implement CronJobForm**

Create `src/claude_code_remote/dashboard/src/components/CronJobForm.tsx`:

```tsx
import { useState } from "react";
import type { CronJobCreateRequest, CronJob } from "../types";
import { createCronJob, updateCronJob } from "../api";

interface Props {
  existing?: CronJob | null;
  onSaved: () => void;
  onCancel: () => void;
}

export default function CronJobForm({ existing, onSaved, onCancel }: Props) {
  const [name, setName] = useState(existing?.name ?? "");
  const [schedule, setSchedule] = useState(existing?.schedule ?? "");
  const [mode, setMode] = useState<"spawn" | "persistent">(
    existing?.execution_mode ?? "spawn"
  );
  const [projectDir, setProjectDir] = useState(
    existing?.session_config.project_dir ?? ""
  );
  const [promptTemplate, setPromptTemplate] = useState(
    existing?.prompt_template ?? ""
  );
  const [model, setModel] = useState(existing?.session_config.model ?? "");
  const [timeout, setTimeout_] = useState(
    existing?.timeout_minutes?.toString() ?? ""
  );
  const [skipPermissions, setSkipPermissions] = useState(
    existing?.session_config.skip_permissions ?? true
  );
  const [enabled, setEnabled] = useState(existing?.enabled ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);

    const data: CronJobCreateRequest = {
      name,
      schedule,
      execution_mode: mode,
      session_config: {
        name: `cron-${name.toLowerCase().replace(/\s+/g, "-")}`,
        project_dir: projectDir,
        initial_prompt: promptTemplate,
        model: model || null,
        skip_permissions: skipPermissions,
      },
      prompt_template: promptTemplate || null,
      timeout_minutes: timeout ? parseInt(timeout) : null,
      enabled,
    };

    try {
      if (existing) {
        await updateCronJob(existing.id, data);
      } else {
        await createCronJob(data);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    "w-full rounded-md bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600";
  const labelClass = "block text-xs font-medium text-zinc-400 mb-1";

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg bg-zinc-900 border border-zinc-800 p-5 space-y-4"
    >
      <h3 className="text-lg font-semibold text-zinc-100">
        {existing ? "Edit Cron Job" : "Create Cron Job"}
      </h3>

      {error && (
        <div className="rounded-md bg-red-900/30 border border-red-800 px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className={inputClass}
            placeholder="Daily code review"
          />
        </div>
        <div>
          <label className={labelClass}>Schedule (cron expression)</label>
          <input
            type="text"
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
            required
            className={inputClass}
            placeholder="0 9 * * *"
          />
        </div>
        <div>
          <label className={labelClass}>Project Directory</label>
          <input
            type="text"
            value={projectDir}
            onChange={(e) => setProjectDir(e.target.value)}
            required
            className={inputClass}
            placeholder="/Users/you/Developer/project"
          />
        </div>
        <div>
          <label className={labelClass}>Execution Mode</label>
          <select
            value={mode}
            onChange={(e) =>
              setMode(e.target.value as "spawn" | "persistent")
            }
            className={inputClass}
          >
            <option value="spawn">Spawn (new session each run)</option>
            <option value="persistent">Persistent (reuse session)</option>
          </select>
        </div>
        <div>
          <label className={labelClass}>Model (optional)</label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className={inputClass}
            placeholder="claude-sonnet-4-6"
          />
        </div>
        <div>
          <label className={labelClass}>Timeout (minutes, optional)</label>
          <input
            type="number"
            value={timeout}
            onChange={(e) => setTimeout_(e.target.value)}
            className={inputClass}
            placeholder="30"
          />
        </div>
      </div>

      <div>
        <label className={labelClass}>
          Prompt Template
          <span className="ml-2 text-zinc-600 font-normal">
            Variables: {"{{date}}"} {"{{time}}"} {"{{datetime}}"}{" "}
            {"{{project}}"} {"{{run_number}}"} {"{{branch}}"}
          </span>
        </label>
        <textarea
          value={promptTemplate}
          onChange={(e) => setPromptTemplate(e.target.value)}
          rows={3}
          className={inputClass}
          placeholder="Review the latest changes on {{branch}} and summarize..."
        />
      </div>

      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={skipPermissions}
            onChange={(e) => setSkipPermissions(e.target.checked)}
            className="rounded border-zinc-700"
          />
          Skip permissions
        </label>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="rounded border-zinc-700"
          />
          Enabled
        </label>
      </div>

      <div className="flex items-center gap-2 pt-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
        >
          {saving ? "Saving..." : existing ? "Update" : "Create"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md bg-zinc-800 border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-700"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/claude_code_remote/dashboard/src/components/CronJobForm.tsx
git commit -m "feat(dashboard): add CronJobForm component for create/edit"
```

---

### Task 11: CronList and CronDetail pages

**Files:**
- Modify: `src/claude_code_remote/dashboard/src/pages/CronList.tsx`
- Modify: `src/claude_code_remote/dashboard/src/pages/CronDetail.tsx`

- [ ] **Step 1: Implement CronList page**

Replace `src/claude_code_remote/dashboard/src/pages/CronList.tsx`:

```tsx
import { useEffect, useState, useCallback } from "react";
import type { CronJobWithRuns } from "../types";
import { listCronJobs, toggleCronJob, triggerCronJob, deleteCronJob } from "../api";
import CronJobTable from "../components/CronJobTable";
import CronJobForm from "../components/CronJobForm";

export default function CronList() {
  const [jobs, setJobs] = useState<CronJobWithRuns[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const fetchJobs = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listCronJobs();
      setJobs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  async function handleToggle(id: string) {
    await toggleCronJob(id);
    fetchJobs();
  }

  async function handleTrigger(id: string) {
    await triggerCronJob(id);
    fetchJobs();
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this cron job?")) return;
    await deleteCronJob(id);
    fetchJobs();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-zinc-100">Cron Jobs</h2>
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500"
        >
          {showForm ? "Cancel" : "Create Cron Job"}
        </button>
      </div>

      {showForm && (
        <div className="mb-6">
          <CronJobForm
            onSaved={() => {
              setShowForm(false);
              fetchJobs();
            }}
            onCancel={() => setShowForm(false)}
          />
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md bg-red-900/30 border border-red-800 px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {loading && !jobs.length ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 h-48 animate-pulse" />
      ) : (
        <CronJobTable
          jobs={jobs}
          onToggle={handleToggle}
          onTrigger={handleTrigger}
          onDelete={handleDelete}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Implement CronDetail page**

Replace `src/claude_code_remote/dashboard/src/pages/CronDetail.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router";
import type { CronJob, CronJobRun } from "../types";
import { getCronJob, getCronJobHistory, triggerCronJob } from "../api";
import CronRunHistory from "../components/CronRunHistory";
import CronJobForm from "../components/CronJobForm";

export default function CronDetail() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<CronJob | null>(null);
  const [runs, setRuns] = useState<CronJobRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([getCronJob(id), getCronJobHistory(id)])
      .then(([j, r]) => {
        setJob(j);
        setRuns(r);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  function refresh() {
    if (!id) return;
    Promise.all([getCronJob(id), getCronJobHistory(id)]).then(([j, r]) => {
      setJob(j);
      setRuns(r);
      setEditing(false);
    });
  }

  if (loading)
    return (
      <div className="h-48 rounded-lg bg-zinc-900 border border-zinc-800 animate-pulse" />
    );
  if (error)
    return (
      <div className="rounded-md bg-red-900/30 border border-red-800 px-4 py-3 text-sm text-red-400">
        {error}
      </div>
    );
  if (!job) return null;

  return (
    <div>
      <Link
        to="/cron"
        className="text-sm text-zinc-500 hover:text-zinc-300 mb-4 inline-block"
      >
        ← Back to cron jobs
      </Link>

      {editing ? (
        <CronJobForm
          existing={job}
          onSaved={refresh}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-5 mb-6">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">
                {job.name}
              </h2>
              <p className="text-sm text-zinc-500 font-mono mt-1">
                {job.schedule}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => triggerCronJob(job.id).then(refresh)}
                className="rounded-md bg-zinc-800 border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-700"
              >
                Trigger Now
              </button>
              <button
                onClick={() => setEditing(true)}
                className="rounded-md bg-zinc-800 border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-700"
              >
                Edit
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 text-sm">
            <div>
              <p className="text-zinc-500">Status</p>
              <p className="text-zinc-200">
                {job.enabled ? "Enabled" : "Disabled"}
              </p>
            </div>
            <div>
              <p className="text-zinc-500">Mode</p>
              <p className="text-zinc-200">{job.execution_mode}</p>
            </div>
            <div>
              <p className="text-zinc-500">Next Run</p>
              <p className="text-zinc-200">
                {job.next_run_at
                  ? new Date(job.next_run_at).toLocaleString()
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-zinc-500">Project</p>
              <p className="text-zinc-200 text-xs font-mono truncate">
                {job.session_config.project_dir}
              </p>
            </div>
          </div>

          {job.prompt_template && (
            <div className="mt-4 pt-4 border-t border-zinc-800">
              <p className="text-xs text-zinc-500 mb-1">Prompt Template</p>
              <pre className="text-sm text-zinc-300 bg-zinc-950 rounded-md p-3 whitespace-pre-wrap">
                {job.prompt_template}
              </pre>
            </div>
          )}
        </div>
      )}

      <h3 className="text-md font-semibold text-zinc-200 mb-3">Run History</h3>
      <CronRunHistory runs={runs} />
    </div>
  );
}
```

- [ ] **Step 3: Verify build**

Run: `cd src/claude_code_remote/dashboard && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
git add src/claude_code_remote/dashboard/src/pages/
git commit -m "feat(dashboard): add CronList and CronDetail pages"
```

---

## Chunk 4: Build, Integrate, and Verify

### Task 12: Final build and commit dist

- [ ] **Step 1: Build production assets**

Run: `cd src/claude_code_remote/dashboard && npm run build`
Expected: `dist/` directory with `index.html` and `assets/` folder

- [ ] **Step 2: Commit dist**

```bash
git add src/claude_code_remote/dashboard/dist/
git commit -m "feat(dashboard): build production assets"
```

---

### Task 13: End-to-end smoke test

- [ ] **Step 1: Start server**

Run: `ccr start --no-auth`

- [ ] **Step 2: Verify dashboard loads**

Open: `http://127.0.0.1:8080/dashboard/`
Expected: CCR Dashboard with nav bar, summary bar, session table showing native sessions

- [ ] **Step 3: Verify session detail**

Click any session in the table.
Expected: Session detail page with message timeline, resume actions

- [ ] **Step 4: Verify cron tab**

Click "Cron Jobs" in nav.
Expected: Cron job list (may be empty). "Create Cron Job" button opens form.

- [ ] **Step 5: Verify client-side routing**

Navigate directly to `http://127.0.0.1:8080/dashboard/cron`
Expected: Cron list page loads (not 404)

- [ ] **Step 6: Stop server**

Run: `ccr stop`

- [ ] **Step 7: Final commit if fixes were needed**

Only if adjustments were made during testing.
