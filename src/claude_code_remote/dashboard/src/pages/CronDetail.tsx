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
      .then(([j, r]) => { setJob(j); setRuns(r); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  function refresh() {
    if (!id) return;
    Promise.all([getCronJob(id), getCronJobHistory(id)]).then(([j, r]) => {
      setJob(j); setRuns(r); setEditing(false);
    });
  }

  if (loading) return <div className="h-48 rounded-lg bg-zinc-900 border border-zinc-800 animate-pulse" />;
  if (error) return <div className="rounded-md bg-red-900/30 border border-red-800 px-4 py-3 text-sm text-red-400">{error}</div>;
  if (!job) return null;

  return (
    <div>
      <Link to="/cron" className="text-sm text-zinc-500 hover:text-zinc-300 mb-4 inline-block">← Back to cron jobs</Link>

      {editing ? (
        <CronJobForm existing={job} onSaved={refresh} onCancel={() => setEditing(false)} />
      ) : (
        <div className="rounded-lg bg-zinc-900 border border-zinc-800 p-5 mb-6">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-xl font-semibold text-zinc-100">{job.name}</h2>
              <p className="text-sm text-zinc-500 font-mono mt-1">{job.schedule}</p>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => triggerCronJob(job.id).then(refresh)} className="rounded-md bg-zinc-800 border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-700">Trigger Now</button>
              <button onClick={() => setEditing(true)} className="rounded-md bg-zinc-800 border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-700">Edit</button>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 text-sm">
            <div>
              <p className="text-zinc-500">Status</p>
              <p className="text-zinc-200">{job.enabled ? "Enabled" : "Disabled"}</p>
            </div>
            <div>
              <p className="text-zinc-500">Mode</p>
              <p className="text-zinc-200">{job.execution_mode}</p>
            </div>
            <div>
              <p className="text-zinc-500">Next Run</p>
              <p className="text-zinc-200">{job.next_run_at ? new Date(job.next_run_at).toLocaleString() : "—"}</p>
            </div>
            <div>
              <p className="text-zinc-500">Project</p>
              <p className="text-zinc-200 text-xs font-mono truncate">{job.session_config.project_dir}</p>
            </div>
          </div>

          {job.prompt_template && (
            <div className="mt-4 pt-4 border-t border-zinc-800">
              <p className="text-xs text-zinc-500 mb-1">Prompt Template</p>
              <pre className="text-sm text-zinc-300 bg-zinc-950 rounded-md p-3 whitespace-pre-wrap">{job.prompt_template}</pre>
            </div>
          )}
        </div>
      )}

      <h3 className="text-md font-semibold text-zinc-200 mb-3">Run History</h3>
      <CronRunHistory runs={runs} />
    </div>
  );
}
