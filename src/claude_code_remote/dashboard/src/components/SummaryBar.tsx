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
