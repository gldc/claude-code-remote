import { useState } from "react";

function MessageBubble({ event }: { event: Record<string, unknown> }) {
  const [expanded, setExpanded] = useState(false);
  const type = event.type as string;
  const message = event.message as Record<string, unknown> | undefined;
  const timestamp = event.timestamp as string | undefined;

  const time = timestamp
    ? new Date(timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

  if (type === "user") {
    const content =
      (message?.content as string) ?? JSON.stringify(message?.content);
    return (
      <div className="flex gap-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-900/50 border border-blue-800 flex items-center justify-center text-xs text-blue-400">
          U
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-zinc-500 mb-1">{time}</p>
          <div className="rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-3 text-sm text-zinc-200 whitespace-pre-wrap">
            {content}
          </div>
        </div>
      </div>
    );
  }

  if (type === "assistant") {
    const contentArr = message?.content as
      | { type: string; text?: string; name?: string; input?: unknown }[]
      | undefined;
    const model = message?.model as string | undefined;

    return (
      <div className="flex gap-3">
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-emerald-900/50 border border-emerald-800 flex items-center justify-center text-xs text-emerald-400">
          A
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-zinc-500 mb-1">
            {time}
            {model && (
              <span className="ml-2 text-zinc-600">{model}</span>
            )}
          </p>
          <div className="rounded-lg bg-zinc-900 border border-zinc-800 px-4 py-3 text-sm space-y-2">
            {contentArr?.map((block, i) => {
              if (block.type === "text") {
                return (
                  <div key={i} className="text-zinc-200 whitespace-pre-wrap">
                    {block.text}
                  </div>
                );
              }
              if (block.type === "tool_use") {
                return (
                  <div key={i}>
                    <button
                      onClick={() => setExpanded(!expanded)}
                      className="text-xs text-amber-400 hover:text-amber-300 font-mono"
                    >
                      {expanded ? "▼" : "▶"} {block.name}
                    </button>
                    {expanded && (
                      <pre className="mt-1 text-xs text-zinc-400 overflow-x-auto bg-zinc-950 rounded p-2">
                        {JSON.stringify(block.input, null, 2)}
                      </pre>
                    )}
                  </div>
                );
              }
              return null;
            })}
          </div>
        </div>
      </div>
    );
  }

  // System messages
  return (
    <div className="flex gap-3">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center text-xs text-zinc-500">
        S
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-zinc-500 mb-1">{time}</p>
        <div className="rounded-lg bg-zinc-900/50 border border-zinc-800 px-4 py-2 text-xs text-zinc-500">
          {(event.content as string) ?? "System event"}
        </div>
      </div>
    </div>
  );
}

export default function MessageTimeline({
  messages,
}: {
  messages: Record<string, unknown>[];
}) {
  if (!messages.length) {
    return (
      <p className="text-zinc-500 text-sm py-8 text-center">No messages</p>
    );
  }
  return (
    <div className="space-y-4">
      {messages.map((msg, i) => (
        <MessageBubble key={i} event={msg} />
      ))}
    </div>
  );
}
