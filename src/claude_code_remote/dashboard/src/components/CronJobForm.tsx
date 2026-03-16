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
  const [mode, setMode] = useState<"spawn" | "persistent">(existing?.execution_mode ?? "spawn");
  const [projectDir, setProjectDir] = useState(existing?.session_config.project_dir ?? "");
  const [promptTemplate, setPromptTemplate] = useState(existing?.prompt_template ?? "");
  const [model, setModel] = useState(existing?.session_config.model ?? "");
  const [timeout, setTimeout_] = useState(existing?.timeout_minutes?.toString() ?? "");
  const [skipPermissions, setSkipPermissions] = useState(existing?.session_config.skip_permissions ?? true);
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

  const inputClass = "w-full rounded-md bg-zinc-950 border border-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600";
  const labelClass = "block text-xs font-medium text-zinc-400 mb-1";

  return (
    <form onSubmit={handleSubmit} className="rounded-lg bg-zinc-900 border border-zinc-800 p-5 space-y-4">
      <h3 className="text-lg font-semibold text-zinc-100">{existing ? "Edit Cron Job" : "Create Cron Job"}</h3>

      {error && (
        <div className="rounded-md bg-red-900/30 border border-red-800 px-3 py-2 text-sm text-red-400">{error}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className={labelClass}>Name</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} required className={inputClass} placeholder="Daily code review" />
        </div>
        <div>
          <label className={labelClass}>Schedule (cron expression)</label>
          <input type="text" value={schedule} onChange={(e) => setSchedule(e.target.value)} required className={inputClass} placeholder="0 9 * * *" />
        </div>
        <div>
          <label className={labelClass}>Project Directory</label>
          <input type="text" value={projectDir} onChange={(e) => setProjectDir(e.target.value)} required className={inputClass} placeholder="/Users/you/Developer/project" />
        </div>
        <div>
          <label className={labelClass}>Execution Mode</label>
          <select value={mode} onChange={(e) => setMode(e.target.value as "spawn" | "persistent")} className={inputClass}>
            <option value="spawn">Spawn (new session each run)</option>
            <option value="persistent">Persistent (reuse session)</option>
          </select>
        </div>
        <div>
          <label className={labelClass}>Model (optional)</label>
          <input type="text" value={model} onChange={(e) => setModel(e.target.value)} className={inputClass} placeholder="claude-sonnet-4-6" />
        </div>
        <div>
          <label className={labelClass}>Timeout (minutes, optional)</label>
          <input type="number" value={timeout} onChange={(e) => setTimeout_(e.target.value)} className={inputClass} placeholder="30" />
        </div>
      </div>

      <div>
        <label className={labelClass}>
          Prompt Template
          <span className="ml-2 text-zinc-600 font-normal">
            Variables: {"{{date}}"} {"{{time}}"} {"{{datetime}}"} {"{{project}}"} {"{{run_number}}"} {"{{branch}}"}
          </span>
        </label>
        <textarea value={promptTemplate} onChange={(e) => setPromptTemplate(e.target.value)} rows={3} className={inputClass} placeholder="Review the latest changes on {{branch}} and summarize..." />
      </div>

      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input type="checkbox" checked={skipPermissions} onChange={(e) => setSkipPermissions(e.target.checked)} className="rounded border-zinc-700" />
          Skip permissions
        </label>
        <label className="flex items-center gap-2 text-sm text-zinc-300">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="rounded border-zinc-700" />
          Enabled
        </label>
      </div>

      <div className="flex items-center gap-2 pt-2">
        <button type="submit" disabled={saving} className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-50">
          {saving ? "Saving..." : existing ? "Update" : "Create"}
        </button>
        <button type="button" onClick={onCancel} className="rounded-md bg-zinc-800 border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-700">
          Cancel
        </button>
      </div>
    </form>
  );
}
