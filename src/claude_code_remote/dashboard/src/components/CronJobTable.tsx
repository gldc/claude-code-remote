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
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">Name</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">Schedule</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">Status</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">Last Run</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">Next Run</th>
            <th className="px-4 py-3 text-left text-xs font-medium text-zinc-500 uppercase tracking-wide">Mode</th>
            <th className="px-4 py-3 text-right text-xs font-medium text-zinc-500 uppercase tracking-wide">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {jobs.map((job) => (
            <tr key={job.id} className="hover:bg-zinc-900/50 transition-colors">
              <td className="px-4 py-3">
                <Link to={`/cron/${job.id}`} className="text-zinc-100 hover:text-white font-medium">{job.name}</Link>
              </td>
              <td className="px-4 py-3 font-mono text-xs text-zinc-400">{job.schedule}</td>
              <td className="px-4 py-3">
                <span className="flex items-center gap-2">
                  <RunStatusDot status={job.last_run_status} />
                  <button onClick={() => onToggle(job.id)} className={`text-xs px-2 py-0.5 rounded-full border ${job.enabled ? "border-green-800 bg-green-900/50 text-green-400" : "border-zinc-700 bg-zinc-800 text-zinc-500"}`}>
                    {job.enabled ? "Enabled" : "Disabled"}
                  </button>
                </span>
              </td>
              <td className="px-4 py-3 text-zinc-400 text-xs">{job.last_run_at ? new Date(job.last_run_at).toLocaleString() : "Never"}</td>
              <td className="px-4 py-3 text-zinc-400 text-xs">{job.next_run_at ? new Date(job.next_run_at).toLocaleString() : "—"}</td>
              <td className="px-4 py-3">
                <span className="text-xs rounded-full border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-zinc-400">{job.execution_mode}</span>
              </td>
              <td className="px-4 py-3 text-right">
                <div className="flex items-center justify-end gap-1">
                  <button onClick={() => onTrigger(job.id)} className="text-xs text-zinc-400 hover:text-white px-2 py-1 rounded hover:bg-zinc-800">Trigger</button>
                  <button onClick={() => onDelete(job.id)} className="text-xs text-red-400 hover:text-red-300 px-2 py-1 rounded hover:bg-zinc-800">Delete</button>
                </div>
              </td>
            </tr>
          ))}
          {jobs.length === 0 && (
            <tr><td colSpan={7} className="px-4 py-8 text-center text-zinc-500">No cron jobs configured</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
