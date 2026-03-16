import { useState } from "react";
import type { DashboardSession } from "../types";
import { resumeNativeSession } from "../api";

export default function ResumeActions({
  session,
}: {
  session: DashboardSession;
}) {
  const [prompt, setPrompt] = useState("");
  const [resuming, setResuming] = useState(false);
  const [showInput, setShowInput] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function handleResume() {
    if (!prompt.trim()) return;
    setResuming(true);
    try {
      if (session.source === "native") {
        const resp = await resumeNativeSession(session.id, prompt);
        setResult(`Created CCR session: ${resp.session_id}`);
      } else {
        // CCR sessions use the existing sessions API, not dashboard API
        const resp = await fetch(`/api/sessions/${session.id}/send`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt }),
        });
        if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
        setResult("Prompt sent");
      }
    } catch {
      setResult("Failed to resume");
    } finally {
      setResuming(false);
    }
  }

  function copyCommand() {
    const cmd = `claude --resume ${session.claude_session_id}`;
    navigator.clipboard.writeText(cmd);
    setResult("Copied to clipboard");
    setTimeout(() => setResult(null), 2000);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setShowInput(!showInput)}
          className="rounded-md bg-zinc-800 border border-zinc-700 px-3 py-1.5 text-sm text-zinc-200 hover:bg-zinc-700"
        >
          {session.source === "native" ? "Resume in CCR" : "Resume"}
        </button>
        {session.source === "native" && (
          <button
            onClick={copyCommand}
            className="rounded-md bg-zinc-900 border border-zinc-800 px-3 py-1.5 text-sm text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
          >
            Copy resume command
          </button>
        )}
      </div>
      {showInput && (
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="Enter prompt..."
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleResume()}
            className="flex-1 rounded-md bg-zinc-900 border border-zinc-800 px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-1 focus:ring-zinc-600"
          />
          <button
            onClick={handleResume}
            disabled={resuming || !prompt.trim()}
            className="rounded-md bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
          >
            {resuming ? "Sending..." : "Send"}
          </button>
        </div>
      )}
      {result && <p className="text-xs text-zinc-500">{result}</p>}
    </div>
  );
}
