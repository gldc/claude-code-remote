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
