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
        <button onClick={() => setShowForm(!showForm)} className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500">
          {showForm ? "Cancel" : "Create Cron Job"}
        </button>
      </div>

      {showForm && (
        <div className="mb-6">
          <CronJobForm onSaved={() => { setShowForm(false); fetchJobs(); }} onCancel={() => setShowForm(false)} />
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md bg-red-900/30 border border-red-800 px-4 py-3 text-sm text-red-400">{error}</div>
      )}

      {loading && !jobs.length ? (
        <div className="rounded-lg border border-zinc-800 bg-zinc-900 h-48 animate-pulse" />
      ) : (
        <CronJobTable jobs={jobs} onToggle={handleToggle} onTrigger={handleTrigger} onDelete={handleDelete} />
      )}
    </div>
  );
}
