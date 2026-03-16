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
  showCost = false,
}: {
  sessions: DashboardSessionSummary[];
  sortKey: SortKey;
  sortDesc: boolean;
  onSort: (key: SortKey) => void;
  showCost?: boolean;
}) {
  const headers: { key: SortKey; label: string }[] = [
    { key: "name", label: "Name" },
    { key: "status", label: "Status" },
    ...(showCost ? [{ key: "total_cost_usd" as SortKey, label: "Cost" }] : []),
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
              {showCost && (
                <td className="px-4 py-3 text-zinc-300 tabular-nums">
                  {s.cost_is_estimated && "~"}${s.total_cost_usd.toFixed(2)}
                </td>
              )}
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
                colSpan={showCost ? 6 : 5}
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
