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
