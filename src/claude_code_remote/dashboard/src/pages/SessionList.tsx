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
          showCost={analytics?.show_cost ?? false}
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
