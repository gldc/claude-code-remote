import { Link } from "react-router";
import type { CronJobRun } from "../types";
import { useConfig } from "../config";

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    success: "bg-green-900/50 text-green-400 border-green-800",
    error: "bg-red-900/50 text-red-400 border-red-800",
    running: "bg-blue-900/50 text-blue-400 border-blue-800",
    timeout: "bg-yellow-900/50 text-yellow-400 border-yellow-800",
  };
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls[status] ?? "bg-zinc-800 text-zinc-400 border-zinc-700"}`}>
      {status}
    </span>
  );
}

export default function CronRunHistory({ runs }: { runs: CronJobRun[] }) {
  const { showCost } = useConfig();

  if (!runs.length) {
    return <p className="text-zinc-500 text-sm py-4">No run history</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900/50">
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">Status</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">Started</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">Completed</th>
            {showCost && <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">Cost</th>}
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">Session</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase">Error</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {runs.map((run) => (
            <tr key={run.id} className="hover:bg-zinc-900/50">
              <td className="px-4 py-3"><StatusBadge status={run.status} /></td>
              <td className="px-4 py-3 text-zinc-400 text-xs">{new Date(run.started_at).toLocaleString()}</td>
              <td className="px-4 py-3 text-zinc-400 text-xs">{run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"}</td>
              {showCost && <td className="px-4 py-3 text-zinc-300 tabular-nums">${run.cost_usd.toFixed(2)}</td>}
              <td className="px-4 py-3">
                {run.session_id ? (
                  <Link to={`/sessions/${run.session_id}`} className="text-xs text-sky-400 hover:text-sky-300 font-mono">{run.session_id.slice(0, 8)}</Link>
                ) : (
                  <span className="text-zinc-600">—</span>
                )}
              </td>
              <td className="px-4 py-3 text-xs text-red-400 max-w-[200px] truncate">{run.error_message ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
