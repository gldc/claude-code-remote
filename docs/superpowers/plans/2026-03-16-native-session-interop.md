# Native Session Interop Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to seamlessly switch between native Claude Code terminal sessions and the mobile app. Use Claude Code's native JSONL event format everywhere — eliminating the CCR-specific WSMessage translation layer — so that native and CCR sessions are indistinguishable in the app.

**Architecture:** Two major changes: (1) Replace CCR's custom WSMessage format with native Claude Code stream-json passthrough, so the server is a thin relay and both native/CCR sessions use identical event structures. (2) Merge native sessions into `/api/sessions` with recency filtering, hidden-session management, auto-adoption, and active-process conflict detection.

**Tech Stack:** Python/FastAPI (server), TypeScript/React Native (Expo app), Pydantic models

---

## File Structure

### Server (claude-code-remote)

| File | Action | Responsibility |
|------|--------|----------------|
| `src/claude_code_remote/session_manager.py` | Modify | Replace `_parse_event()` with native passthrough, change user message format to native |
| `src/claude_code_remote/models.py` | Modify | Remove WSMessageType enum; add `source`, `native_pid` to SessionSummary |
| `src/claude_code_remote/websocket.py` | Modify | Update WebSocket replay to use native event format |
| `src/claude_code_remote/config.py` | Modify | Add `HIDDEN_SESSIONS_FILE` path constant, `native_max_age_days` default |
| `src/claude_code_remote/hidden_sessions.py` | Create | Hidden sessions store — load/save/add/remove UUID sets (hidden vs permanent) |
| `src/claude_code_remote/native_sessions.py` | Modify | Add `get_active_pid()`, recency filter, hidden filter |
| `src/claude_code_remote/routes.py` | Modify | Merge native sessions into `/api/sessions`, auto-adopt, hide/unhide |
| `src/claude_code_remote/server.py` | Modify | Wire `native_reader` and `hidden_store` into `create_router()` |
| `tests/test_hidden_sessions.py` | Create | Tests for hidden sessions store |
| `tests/test_native_interop.py` | Create | Tests for native session listing, adoption, conflict detection |

### App (claude-code-remote-app)

| File | Action | Responsibility |
|------|--------|----------------|
| `lib/types.ts` | Modify | Replace WSMessageType with native event types, add `source`/`native_pid` |
| `lib/websocket.ts` | Modify | Update valid message types to native event types |
| `components/MessageCard.tsx` | Modify | Rewrite router for native event types |
| `components/AssistantCard.tsx` | Create | Renders `assistant` events (iterates content blocks: text + tool_use) |
| `components/NativeToolResultCard.tsx` | Create | Renders native `tool_result` events (field mapping differs) |
| `components/AssistantTextCard.tsx` | Keep | Reused by AssistantCard for text content blocks |
| `components/ToolUseCard.tsx` | Modify | Minor: accept content block shape instead of WSMessage data shape |
| `components/ToolResultCard.tsx` | Modify | Accept native field names (`content` instead of `data.output`) |
| `components/ApprovalCard.tsx` | Keep | Unchanged — CCR-specific event type |
| `components/SessionCard.tsx` | Modify | Add source badge, "Live on terminal" indicator |
| `lib/api.ts` | Modify | Add `useHideSession()`, `useUnhideSession()` hooks |
| `app/(tabs)/sessions/[id]/index.tsx` | Modify | Handle adoption redirect, disable input when native_pid set |

---

## Format Migration Reference

### Current WSMessage format (being replaced):
```
assistant_text  →  {type: "assistant_text", data: {text: "..."}}
tool_use        →  {type: "tool_use", data: {tool_name, tool_input, tool_use_id}}
tool_result     →  {type: "tool_result", data: {tool_use_id, output, is_error}}
user_message    →  {type: "user_message", data: {text: "..."}}
status_change   →  {type: "status_change", data: {status, cost_usd, duration_ms}}
approval_request → {type: "approval_request", data: {tool_name, tool_input}}
```

### Native stream-json format (target):
```
assistant       →  {type: "assistant", message: {content: [{type: "text", text: "..."}, {type: "tool_use", name: "...", input: {...}, id: "..."}]}}
tool_result     →  {type: "tool_result", content: "...", tool_use_id: "...", is_error: false}
user            →  {type: "user", message: {role: "user", content: "..."}}
result          →  {type: "result", subtype: "success"|"error", session_id: "...", total_cost_usd: 0.05}
approval_request → {type: "approval_request", data: {tool_name, tool_input}}  (CCR-specific, stays)
```

### Key differences:
1. `assistant` is ONE event with a `content[]` array containing both text and tool_use blocks (currently split into separate messages)
2. `tool_result.content` instead of `data.output`
3. `user` instead of `user_message`, with `message.content` instead of `data.text`
4. `result` instead of `status_change`, with `subtype` and direct fields instead of nested `data`
5. `approval_request` stays as-is (CCR-only concept)

---

## Task 1: Server — Native Event Passthrough

**Files:**
- Modify: `src/claude_code_remote/session_manager.py`
- Modify: `src/claude_code_remote/models.py`
- Modify: `src/claude_code_remote/websocket.py`

This task replaces the CCR-specific `_parse_event()` translation with direct passthrough of native stream-json events. The server becomes a thin relay.

- [ ] **Step 1: Simplify `_parse_event()` to passthrough**

In `src/claude_code_remote/session_manager.py`, replace the `_parse_event` method. Instead of translating events into WSMessage objects, return raw event dicts directly. Keep the extraction of `session_id`, `cost`, `model`, and `context_percent` from result/assistant events in `_read_output()` (that metadata extraction stays).

The new approach: `_read_output()` stores raw events in `session.messages` and broadcasts them as plain dicts instead of WSMessage objects.

Replace `_parse_event()`:

```python
def _should_broadcast(self, event: dict) -> bool:
    """Determine if a stream-json event should be stored and broadcast."""
    etype = event.get("type")
    # Broadcast displayable events; skip internal bookkeeping
    return etype in (
        "assistant", "tool_result", "result", "rate_limit_event",
        "user",  # shouldn't appear in stream output, but handle gracefully
    )
```

- [ ] **Step 2: Update `_read_output()` to store raw events**

Replace the parsed-message handling in `_read_output()`. Instead of calling `_parse_event()` and storing `WSMessage.model_dump()`, store the raw event dict and broadcast it:

```python
# In _read_output, replace the _parse_event block:
if self._should_broadcast(event):
    # Add timestamp if not present
    if "timestamp" not in event:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
    session.messages.append(event)
    for cb in self.ws_subscribers.get(session_id, []):
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(event)
            else:
                cb(event)
        except Exception as e:
            logger.error(f"WebSocket broadcast error: {e}")
    session.updated_at = datetime.now(timezone.utc)
```

Keep the existing metadata extraction blocks (`event.get("type") == "assistant"` for model, `event.get("type") == "result"` for session_id/cost/context) exactly as they are.

- [ ] **Step 3: Update user message injection to native format**

In `send_prompt()`, change the user message format:

```python
# Replace the WSMessage user message with native format:
user_event = {
    "type": "user",
    "message": {"role": "user", "content": prompt},
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
session.messages.append(user_event)
# Broadcast to WebSocket subscribers
for cb in self.ws_subscribers.get(session_id, []):
    try:
        if asyncio.iscoroutinefunction(cb):
            await cb(user_event)
        else:
            cb(user_event)
    except Exception as e:
        logger.error(f"WebSocket broadcast error: {e}")
```

- [ ] **Step 4: Update approval_request to broadcast as dict**

In `request_approval()`, change from WSMessage to plain dict:

```python
approval_event = {
    "type": "approval_request",
    "data": {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "description": f"{tool_name} wants to run",
    },
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
session.messages.append(approval_event)
# Broadcast
for cb in self.ws_subscribers.get(session_id, []):
    try:
        if asyncio.iscoroutinefunction(cb):
            await cb(approval_event)
        else:
            cb(approval_event)
    except Exception as e:
        logger.error(f"WebSocket broadcast error: {e}")
```

- [ ] **Step 5: Emit synthetic `result` event on process exit (only if none was received)**

Claude Code normally emits a `result` event before exiting. But if the process crashes or is killed, no `result` event is sent. Track whether one was received and only emit a synthetic one if not.

Add a `seen_result` flag at the top of `_read_output()`:

```python
seen_result = False
```

In the event loop, where `event.get("type") == "result"` is already handled, add:

```python
if event.get("type") == "result":
    seen_result = True
    # ... existing session_id/cost/context extraction ...
```

After `await proc.wait()`, only emit a synthetic result if none was received:

```python
if session.status == SessionStatus.RUNNING and not seen_result:
    result_event = {
        "type": "result",
        "subtype": "success" if proc.returncode == 0 else "error",
        "total_cost_usd": session.total_cost_usd,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if proc.returncode != 0:
        result_event["error"] = f"Process exited with code {proc.returncode}"
    session.messages.append(result_event)
    await self._broadcast(session_id, result_event)
```

- [ ] **Step 6: Update `_broadcast` to accept plain dicts**

**Do this step FIRST before steps 2-5.** Change the `_broadcast` method signature from `WSMessage` to `dict`:

```python
async def _broadcast(self, session_id: str, event: dict) -> None:
    for cb in self.ws_subscribers.get(session_id, []):
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(event)
            else:
                cb(event)
        except Exception as e:
            logger.error(f"WebSocket broadcast error: {e}")
```

All broadcast calls in steps 2-5 should use `await self._broadcast(session_id, event)` — not inline loops.

- [ ] **Step 7: Update WebSocket handler for dict broadcasts**

In `src/claude_code_remote/websocket.py`, make these specific changes:

```python
# Line 13: Remove WSMessage import
# FROM: from claude_code_remote.models import WSMessage
# (delete this line entirely — WSMessage no longer exists)

# Line 43-44: Backfill already works (sends plain dicts via send_json) — no change needed

# Line 47: Change queue type
# FROM: queue: asyncio.Queue[WSMessage] = asyncio.Queue()
# TO:
queue: asyncio.Queue[dict] = asyncio.Queue()

# Line 49-50: Change callback signature
# FROM: async def on_event(msg: WSMessage): await queue.put(msg)
# TO:
async def on_event(event: dict):
    await queue.put(event)

# Line 58: Remove model_dump — events are already dicts
# FROM: await websocket.send_json(msg.model_dump(mode="json"))
# TO:
msg = await asyncio.wait_for(queue.get(), timeout=30)
await websocket.send_json(msg)
```

- [ ] **Step 8: Remove WSMessageType and WSMessage from models.py**

In `src/claude_code_remote/models.py`, delete the `WSMessageType` enum and `WSMessage` class (lines 38-49 and 184-187). These are no longer used. Also remove the corresponding import in `session_manager.py`.

Search for `WSMessage` and `WSMessageType` across the entire server codebase and remove all imports/references. Key files:
- `session_manager.py` — remove import, all WSMessage/WSMessageType usage (already replaced in steps above)
- `websocket.py` — remove import (already updated in Step 7)
- `tests/test_models.py` — remove the `WSMessage`/`WSMessageType` import and the test that creates `WSMessage(type=WSMessageType.ASSISTANT_TEXT, ...)`. Either delete the test or replace it with a test validating native event dict format.

- [ ] **Step 9: Add migration for existing session files**

In `session_manager.py`'s `load_sessions()` method, add a migration step that converts old WSMessage-format messages to native format:

```python
def _migrate_messages(self, messages: list[dict]) -> list[dict]:
    """Convert old WSMessage-format messages to native event format."""
    migrated = []
    for msg in messages:
        msg_type = msg.get("type")
        data = msg.get("data", {})
        ts = msg.get("timestamp", datetime.now(timezone.utc).isoformat())

        if msg_type == "user_message":
            migrated.append({
                "type": "user",
                "message": {"role": "user", "content": data.get("text", "")},
                "timestamp": ts,
            })
        elif msg_type == "assistant_text":
            migrated.append({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": data.get("text", "")}]},
                "timestamp": ts,
            })
        elif msg_type == "tool_use":
            migrated.append({
                "type": "assistant",
                "message": {"content": [{
                    "type": "tool_use",
                    "name": data.get("tool_name", ""),
                    "input": data.get("tool_input", {}),
                    "id": data.get("tool_use_id", ""),
                }]},
                "timestamp": ts,
            })
        elif msg_type == "tool_result":
            migrated.append({
                "type": "tool_result",
                "content": data.get("output", data.get("content", "")),
                "tool_use_id": data.get("tool_use_id", ""),
                "is_error": data.get("is_error", False),
                "timestamp": ts,
            })
        elif msg_type == "status_change":
            migrated.append({
                "type": "result",
                "subtype": "success" if data.get("status") == "idle" else "error",
                "total_cost_usd": data.get("cost_usd", 0),
                "duration_ms": data.get("duration_ms", 0),
                "timestamp": ts,
            })
        elif msg_type == "approval_request":
            migrated.append(msg)  # Keep as-is
        elif msg_type == "rate_limit":
            migrated.append({
                "type": "rate_limit_event",
                "rate_limit_info": data,
                "timestamp": ts,
            })
        else:
            migrated.append(msg)  # Unknown types pass through
    return migrated
```

**Known limitation:** The migration converts each `assistant_text` and `tool_use` into separate `assistant` events with a single content block each. In the real native format, these would be one `assistant` event with multiple blocks in `content[]`. This means migrated sessions show slightly different grouping (separate cards per block) vs new sessions. This is cosmetic only — all content is preserved. Merging consecutive messages would be complex and error-prone, so we accept this difference for pre-existing sessions.

In `load_sessions()`, after loading each session, check if migration is needed:

```python
# After session = Session.model_validate_json(path.read_text()):
needs_migration = any(
    msg.get("type") in ("assistant_text", "tool_use", "user_message", "status_change")
    for msg in session.messages
)
if needs_migration:
    session.messages = self._migrate_messages(session.messages)
    migrated = True
```

- [ ] **Step 10: Update `search_sessions()` for native event types**

The `search_sessions()` method extracts text from messages for full-text search. Update it to handle native event format:

```python
def search_sessions(self, query: str) -> list[dict]:
    query_lower = query.lower()
    results = []
    for sid, session in self.sessions.items():
        for msg in session.messages:
            text = ""
            msg_type = msg.get("type")

            if msg_type == "assistant":
                # Extract text from content blocks
                for block in msg.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text += block.get("text", "")
            elif msg_type == "user":
                content = msg.get("message", {}).get("content", "")
                text = content if isinstance(content, str) else str(content)
            elif msg_type == "tool_result":
                text = str(msg.get("content", ""))

            if query_lower in text.lower():
                idx = text.lower().index(query_lower)
                start = max(0, idx - 50)
                end = min(len(text), idx + len(query) + 50)
                results.append({
                    "session_id": sid,
                    "session_name": session.name,
                    "snippet": text[start:end],
                    "message_type": msg_type,
                    "timestamp": msg.get("timestamp"),
                })
                break
    return results
```

- [ ] **Step 11: Update `_to_summary()` preview extraction for native format**

The `_to_summary()` method extracts a preview from the last message. Update it:

```python
@staticmethod
def _to_summary(s: Session) -> SessionSummary:
    preview = None
    if s.messages:
        last = s.messages[-1]
        msg_type = last.get("type")
        if msg_type == "assistant":
            for block in last.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    preview = block.get("text", "")[:100]
                    break
        elif msg_type == "user":
            content = last.get("message", {}).get("content", "")
            preview = (content if isinstance(content, str) else str(content))[:100]
        elif msg_type == "tool_result":
            preview = str(last.get("content", ""))[:100]
        elif msg_type == "result":
            preview = "Completed" if last.get("subtype") == "success" else "Error"
    return SessionSummary(
        id=s.id, name=s.name, project_dir=s.project_dir,
        status=s.status, model=s.model, created_at=s.created_at,
        updated_at=s.updated_at, total_cost_usd=s.total_cost_usd,
        current_model=s.current_model, context_percent=s.context_percent,
        git_branch=s.git_branch, message_count=len(s.messages),
        last_message_preview=preview, archived=s.archived,
        cron_job_id=s.cron_job_id,
    )
```

- [ ] **Step 12: Run existing tests**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/ -v --timeout=30 -x`

Some tests may fail if they assert on WSMessage format — fix those to use native format.

- [ ] **Step 11: Commit**

```bash
git add src/claude_code_remote/session_manager.py src/claude_code_remote/models.py src/claude_code_remote/websocket.py
git commit -m "feat: replace WSMessage format with native Claude Code stream-json passthrough"
```

---

## Task 2: App — Native Event Rendering

**Files:**
- Modify: `/Users/gldc/Developer/claude-code-remote-app/lib/types.ts`
- Modify: `/Users/gldc/Developer/claude-code-remote-app/lib/websocket.ts`
- Modify: `/Users/gldc/Developer/claude-code-remote-app/components/MessageCard.tsx`
- Create: `/Users/gldc/Developer/claude-code-remote-app/components/AssistantCard.tsx`
- Modify: `/Users/gldc/Developer/claude-code-remote-app/components/ToolUseCard.tsx`
- Modify: `/Users/gldc/Developer/claude-code-remote-app/components/ToolResultCard.tsx`

- [ ] **Step 1: Replace WSMessageType with native event types in types.ts**

```typescript
// Replace WSMessageType union:
export type NativeEventType =
  | 'assistant'       // assistant response (text + tool_use blocks in content[])
  | 'tool_result'     // tool execution result
  | 'user'            // user message
  | 'result'          // turn completion (replaces status_change)
  | 'rate_limit_event'// rate limiting
  | 'approval_request'// CCR-specific: tool approval needed
  | 'error'           // CCR-specific: error
  | 'ping';           // keepalive (dropped before storage)

// Replace WSMessageData:
export interface NativeEvent {
  type: NativeEventType;
  timestamp?: string;
  // Native events have varying shapes per type — use type-specific interfaces below
  [key: string]: any;
}

// Type-specific interfaces for rendering:
export interface AssistantEvent extends NativeEvent {
  type: 'assistant';
  message: {
    model?: string;
    content: Array<
      | { type: 'text'; text: string }
      | { type: 'tool_use'; name: string; input: Record<string, any>; id: string }
    >;
  };
}

export interface ToolResultEvent extends NativeEvent {
  type: 'tool_result';
  content: string;
  tool_use_id: string;
  is_error?: boolean;
}

export interface UserEvent extends NativeEvent {
  type: 'user';
  message: { role: 'user'; content: string | any[] };
}

export interface ResultEvent extends NativeEvent {
  type: 'result';
  subtype: 'success' | 'error';
  total_cost_usd?: number;
  duration_ms?: number;
  session_id?: string;
}

export interface ApprovalRequestEvent extends NativeEvent {
  type: 'approval_request';
  data: {
    tool_name: string;
    tool_input: Record<string, any>;
    description: string;
    resolved?: boolean;
    approved?: boolean;
  };
}
```

- [ ] **Step 2: Update VALID_WS_MESSAGE_TYPES in websocket.ts**

```typescript
const VALID_EVENT_TYPES = new Set([
  'assistant', 'tool_result', 'user', 'result',
  'rate_limit_event', 'approval_request', 'error', 'ping',
]);

// Update isValidWSMessage to use new types:
function isValidEvent(data: any): boolean {
  return data && typeof data.type === 'string' && VALID_EVENT_TYPES.has(data.type);
}
```

Update `useSessionStream` to use `NativeEvent` instead of `WSMessageData` throughout.

Update the Zustand store in `lib/store.ts`:

```typescript
// Replace all WSMessageData references:
import { NativeEvent } from './types';

interface AppState {
  // ...
  sessionMessages: Record<string, NativeEvent[]>;
  appendMessage: (sessionId: string, message: NativeEvent) => void;
  setMessages: (sessionId: string, messages: NativeEvent[]) => void;
  clearMessages: (sessionId: string) => void;
  // ...
}
```

Search the entire app codebase for `WSMessageData` and replace with `NativeEvent` everywhere.

- [ ] **Step 3: Rewrite MessageCard router for native event types**

```tsx
// components/MessageCard.tsx
import { AssistantCard } from './AssistantCard';

export function MessageCard({ message, ...props }) {
  switch (message.type) {
    case 'user': {
      const content = typeof message.message?.content === 'string'
        ? message.message.content
        : JSON.stringify(message.message?.content);
      return (
        <View style={styles.userBubble}>
          <CopyablePressable text={content}>
            <Text style={styles.userText}>{content}</Text>
          </CopyablePressable>
        </View>
      );
    }

    case 'assistant':
      return <AssistantCard event={message} isFirstInGroup={props.isFirstInGroup} />;

    case 'tool_result':
      return <ToolResultCard
        content={message.content}
        toolUseId={message.tool_use_id}
        isError={message.is_error}
      />;

    case 'approval_request':
      return <ApprovalCard sessionId={sessionId} {...message.data} />;

    case 'result': {
      const isSuccess = message.subtype === 'success';
      return (
        <View style={styles.divider}>
          <Text style={styles.dividerText}>
            {isSuccess ? 'Completed' : 'Error'}
            {showCost && message.total_cost_usd ? ` · $${message.total_cost_usd.toFixed(4)}` : ''}
          </Text>
        </View>
      );
    }

    case 'rate_limit_event':
      return (
        <View style={styles.divider}>
          <Text style={styles.dividerText}>Rate limited — retrying</Text>
        </View>
      );

    case 'error':
      return <ErrorCard message={message.data?.message || message.error || 'Unknown error'} />;

    // Legacy types — rendered for backward compat with pre-migration sessions
    case 'bash_output':
      return <BashOutputCard data={message.data} />;

    default:
      return null;
  }
}
```

- [ ] **Step 4: Create AssistantCard component**

This component renders a single `assistant` event, which contains multiple content blocks (text and tool_use) in its `message.content[]` array.

```tsx
// components/AssistantCard.tsx
import { AssistantTextCard } from './AssistantTextCard';
import { ToolUseCard } from './ToolUseCard';

interface AssistantCardProps {
  event: AssistantEvent;
  isFirstInGroup: boolean;
}

export function AssistantCard({ event, isFirstInGroup }: AssistantCardProps) {
  const content = event.message?.content || [];

  return (
    <View style={styles.container}>
      {isFirstInGroup && <ClaudeAvatar />}
      <View style={styles.blocks}>
        {content.map((block, i) => {
          if (block.type === 'text') {
            return <AssistantTextCard key={i} text={block.text} />;
          }
          if (block.type === 'tool_use') {
            return (
              <ToolUseCard
                key={i}
                toolName={block.name}
                toolInput={block.input}
                toolUseId={block.id}
              />
            );
          }
          return null;
        })}
      </View>
    </View>
  );
}
```

- [ ] **Step 5: Update ToolUseCard props**

Change `ToolUseCard` to accept direct props instead of `data` object:

```tsx
// From: { data: { tool_name, tool_input, tool_use_id } }
// To:   { toolName, toolInput, toolUseId }
interface ToolUseCardProps {
  toolName: string;
  toolInput: Record<string, any>;
  toolUseId: string;
}
```

Update the component to use the new prop names. The rendering logic stays the same — just the data access changes.

- [ ] **Step 6: Update ToolResultCard props**

Change `ToolResultCard` to accept native field names:

```tsx
// From: { data: { output, is_error, tool_use_id, content_type } }
// To:   { content, isError, toolUseId }
interface ToolResultCardProps {
  content: string;
  isError?: boolean;
  toolUseId?: string;
}
```

The content-type detection logic stays (checking for diff markers, etc.) — it just reads from `content` instead of `data.output`.

- [ ] **Step 7: Update avatar/grouping logic in session detail**

In `app/(tabs)/sessions/[id]/index.tsx`, the `isFirstInGroup` logic checks message types. Update all type references:

```tsx
// Update type checks throughout the grouping logic:
// 'assistant_text' → 'assistant'
// 'user_message' → 'user'
// 'status_change' → 'result'
//
// The existing logic checks if current is 'assistant_text' and previous is
// 'user_message' or 'status_change'. Replace all three type strings.
```

- [ ] **Step 8: Commit**

```bash
cd /Users/gldc/Developer/claude-code-remote-app
git add lib/types.ts lib/websocket.ts lib/store.ts components/MessageCard.tsx components/AssistantCard.tsx components/ToolUseCard.tsx components/ToolResultCard.tsx app/(tabs)/sessions/[id]/index.tsx
git commit -m "feat: migrate app to native Claude Code event format"
```

---

## Task 3: Hidden Sessions Store

**Files:**
- Modify: `src/claude_code_remote/config.py:13-19`
- Create: `src/claude_code_remote/hidden_sessions.py`
- Create: `tests/test_hidden_sessions.py`

- [ ] **Step 1: Write failing tests for HiddenSessionsStore**

```python
# tests/test_hidden_sessions.py
import json
from pathlib import Path
from claude_code_remote.hidden_sessions import HiddenSessionsStore


def test_hide_and_list(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-1")
    assert store.is_hidden("uuid-1")
    assert not store.is_permanently_hidden("uuid-1")


def test_permanently_hide(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-2", permanent=True)
    assert store.is_hidden("uuid-2")
    assert store.is_permanently_hidden("uuid-2")


def test_unhide(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-3")
    store.unhide("uuid-3")
    assert not store.is_hidden("uuid-3")


def test_unhide_permanent_not_allowed(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-4", permanent=True)
    store.unhide("uuid-4")
    assert store.is_hidden("uuid-4")  # permanent stays hidden


def test_list_hidden_non_permanent(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "hidden.json")
    store.hide("uuid-a")
    store.hide("uuid-b", permanent=True)
    store.hide("uuid-c")
    archived = store.list_hidden(include_permanent=False)
    assert set(archived) == {"uuid-a", "uuid-c"}


def test_persistence(tmp_path: Path):
    path = tmp_path / "hidden.json"
    store1 = HiddenSessionsStore(path)
    store1.hide("uuid-5")
    store1.hide("uuid-6", permanent=True)

    store2 = HiddenSessionsStore(path)
    assert store2.is_hidden("uuid-5")
    assert store2.is_permanently_hidden("uuid-6")


def test_empty_file(tmp_path: Path):
    store = HiddenSessionsStore(tmp_path / "nonexistent.json")
    assert not store.is_hidden("anything")
    assert store.list_hidden() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/test_hidden_sessions.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Add HIDDEN_SESSIONS_FILE to config.py**

In `src/claude_code_remote/config.py`, add after line 19 (`CRON_HISTORY_FILE`):

```python
HIDDEN_SESSIONS_FILE = STATE_DIR / "hidden_sessions.json"
```

Also add `native_max_age_days` to `DEFAULT_CONFIG`:

```python
DEFAULT_CONFIG = {
    "port": 8080,
    "max_concurrent_sessions": 5,
    "scan_directories": ["~/Developer"],
    "session_idle_timeout_minutes": None,
    "show_cost": False,
    "native_max_age_days": 7,
}
```

- [ ] **Step 4: Implement HiddenSessionsStore**

```python
# src/claude_code_remote/hidden_sessions.py
"""Non-destructive hidden sessions store for native Claude Code sessions."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class HiddenSessionsStore:
    """Tracks native session UUIDs that the user has hidden from the app.

    Two tiers:
    - hidden (archived): visible in archive view, can be unhidden
    - permanently hidden (deleted): not shown anywhere in app
    """

    def __init__(self, path: Path):
        self._path = path
        self._hidden: set[str] = set()
        self._permanent: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._hidden = set(data.get("hidden", []))
            self._permanent = set(data.get("permanent", []))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load hidden sessions: %s", e)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "hidden": sorted(self._hidden),
                    "permanent": sorted(self._permanent),
                },
                indent=2,
            )
        )
        os.chmod(self._path, 0o600)

    def hide(self, session_id: str, permanent: bool = False) -> None:
        if permanent:
            self._permanent.add(session_id)
            self._hidden.discard(session_id)
        else:
            if session_id not in self._permanent:
                self._hidden.add(session_id)
        self._save()

    def unhide(self, session_id: str) -> None:
        if session_id in self._permanent:
            return  # permanent hides cannot be undone from app
        self._hidden.discard(session_id)
        self._save()

    def is_hidden(self, session_id: str) -> bool:
        return session_id in self._hidden or session_id in self._permanent

    def is_permanently_hidden(self, session_id: str) -> bool:
        return session_id in self._permanent

    def list_hidden(self, include_permanent: bool = True) -> list[str]:
        if include_permanent:
            return sorted(self._hidden | self._permanent)
        return sorted(self._hidden)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/test_hidden_sessions.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_code_remote/config.py src/claude_code_remote/hidden_sessions.py tests/test_hidden_sessions.py
git commit -m "feat: add hidden sessions store for native session visibility control"
```

---

## Task 4: Enhance NativeSessionReader

**Files:**
- Modify: `src/claude_code_remote/native_sessions.py`
- Create: `tests/test_native_reader_interop.py`

- [ ] **Step 1: Write failing tests for new NativeSessionReader methods**

```python
# tests/test_native_reader_interop.py
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from claude_code_remote.native_sessions import NativeSessionReader


def _write_session(projects_dir: Path, project_name: str, session_id: str, ts: str, cwd: str = "/tmp/proj"):
    """Helper to write a minimal JSONL session file."""
    project_dir = projects_dir / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    jsonl = project_dir / f"{session_id}.jsonl"
    event = json.dumps({
        "type": "user",
        "sessionId": session_id,
        "cwd": cwd,
        "timestamp": ts,
        "message": {"role": "user", "content": "hello"},
    })
    jsonl.write_text(event + "\n")
    return jsonl


def test_get_active_pid_no_active(tmp_path: Path):
    reader = NativeSessionReader(claude_dir=tmp_path)
    assert reader.get_active_pid("some-uuid") is None


def test_get_active_pid_with_active(tmp_path: Path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    pid = os.getpid()  # use our own PID — guaranteed alive
    (sessions_dir / "test.json").write_text(
        json.dumps({"sessionId": "uuid-123", "pid": pid})
    )
    reader = NativeSessionReader(claude_dir=tmp_path)
    assert reader.get_active_pid("uuid-123") == pid


def test_list_sessions_recency_filter(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=30)).isoformat()
    recent_ts = (now - timedelta(hours=1)).isoformat()

    _write_session(projects_dir, "proj", "a" * 36, old_ts, "/Users/test/proj")
    _write_session(projects_dir, "proj", "b" * 36, recent_ts, "/Users/test/proj")

    reader = NativeSessionReader(claude_dir=tmp_path)
    sessions = reader.list_sessions(max_age_days=7)
    ids = [s.id for s in sessions]
    assert "b" * 36 in ids
    assert "a" * 36 not in ids


def test_list_sessions_respects_hidden(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    now = datetime.now(timezone.utc).isoformat()

    _write_session(projects_dir, "proj", "c" * 36, now, "/Users/test/proj")
    _write_session(projects_dir, "proj", "d" * 36, now, "/Users/test/proj")

    reader = NativeSessionReader(claude_dir=tmp_path)
    hidden = {"c" * 36}
    sessions = reader.list_sessions(hidden_ids=hidden)
    ids = [s.id for s in sessions]
    assert "d" * 36 in ids
    assert "c" * 36 not in ids


def test_list_sessions_hidden_returns_in_archived_mode(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    now = datetime.now(timezone.utc).isoformat()

    _write_session(projects_dir, "proj", "e" * 36, now, "/Users/test/proj")

    reader = NativeSessionReader(claude_dir=tmp_path)
    hidden = {"e" * 36}
    sessions = reader.list_sessions(hidden_ids=hidden, archived=True)
    ids = [s.id for s in sessions]
    assert "e" * 36 in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/test_native_reader_interop.py -v`
Expected: FAIL — `get_active_pid` not found, `list_sessions` signature mismatch

- [ ] **Step 3: Add `tool_result` to `DISPLAYED_TYPES` and add `get_active_pid()`**

In `src/claude_code_remote/native_sessions.py`, update `DISPLAYED_TYPES` to include tool results so native session history is complete:

```python
DISPLAYED_TYPES = {"user", "assistant", "tool_result"}
```

Add after `_load_active_sessions()` method:

```python
def get_active_pid(self, session_id: str) -> int | None:
    """Return the PID if this session is currently running natively, else None."""
    active = self._load_active_sessions()
    return active.get(session_id)
```

- [ ] **Step 4: Add filtering parameters to `list_sessions()`**

Modify `list_sessions()` signature and body:

```python
def list_sessions(
    self,
    max_age_days: int | None = None,
    hidden_ids: set[str] | None = None,
    archived: bool = False,
) -> list[DashboardSessionSummary]:
    """List native sessions with optional recency and visibility filters.

    Args:
        max_age_days: Only return sessions updated within this many days.
        hidden_ids: Set of session UUIDs that are hidden. When archived=False,
            these are excluded. When archived=True, ONLY these are returned.
        archived: If True, return hidden sessions instead of visible ones.
    """
    self._scan_sessions()

    now = datetime.now(timezone.utc)
    results = []
    for c in self._cache.values():
        s = c.summary
        if s.project_dir in _HIDDEN_PROJECT_DIRS:
            continue

        is_hidden = hidden_ids and s.id in hidden_ids

        if archived:
            if not is_hidden:
                continue
        else:
            if is_hidden:
                continue
            if max_age_days is not None:
                age = now - s.updated_at
                if age.days > max_age_days:
                    continue

        results.append(s)
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/test_native_reader_interop.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_code_remote/native_sessions.py tests/test_native_reader_interop.py
git commit -m "feat: add recency filter, hidden filter, and active PID detection to NativeSessionReader"
```

---

## Task 5: Add `source` and `native_pid` to Session Models

**Files:**
- Modify: `src/claude_code_remote/models.py:111-129`

- [ ] **Step 1: Add `source` and `native_pid` fields to SessionSummary**

```python
class SessionSummary(BaseModel):
    """Lightweight session info for list views (no messages)."""

    id: str
    name: str
    project_dir: str
    status: SessionStatus
    model: str | None
    created_at: datetime
    updated_at: datetime
    total_cost_usd: float
    current_model: str | None = None
    context_percent: int = 0
    git_branch: str | None = None
    message_count: int = 0
    last_message_preview: str | None = None
    archived: bool = False
    cron_job_id: str | None = None
    source: str = "ccr"
    native_pid: int | None = None
```

- [ ] **Step 2: Run existing tests**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/ -v --timeout=30 -x`
Expected: All tests pass (new fields have defaults)

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/models.py
git commit -m "feat: add source and native_pid fields to SessionSummary"
```

---

## Task 6: Wire Native Sessions into Main Routes

**Files:**
- Modify: `src/claude_code_remote/routes.py`
- Modify: `src/claude_code_remote/server.py`
- Create: `tests/test_native_interop.py`

- [ ] **Step 0: Write route-level integration tests**

```python
# tests/test_native_interop.py
"""Tests for native session interop in the main /api/sessions routes."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from claude_code_remote.models import DashboardSessionSummary
from claude_code_remote.hidden_sessions import HiddenSessionsStore


@pytest.fixture
def mock_native_reader():
    reader = MagicMock()
    reader.list_sessions.return_value = []
    reader.get_session.return_value = None
    reader.get_session_messages.return_value = ([], 0)
    reader.get_active_pid.return_value = None
    return reader


@pytest.fixture
def hidden_store(tmp_path):
    return HiddenSessionsStore(tmp_path / "hidden.json")


def _make_native(session_id="native-uuid-1234567890abcdef12345678", **kw):
    defaults = dict(
        id=session_id, name="my-project", project_dir="/Users/test/proj",
        source="native", status="completed", current_model="claude-sonnet-4-6",
        total_cost_usd=0.05, cost_is_estimated=True, message_count=10,
        git_branch="main", claude_session_id=session_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(kw)
    return DashboardSessionSummary(**defaults)


def _test_client(session_mgr=None, native_reader=None, hidden_store=None):
    from claude_code_remote.routes import create_router
    if session_mgr is None:
        session_mgr = MagicMock()
        session_mgr.list_sessions.return_value = []
        session_mgr.get_session.return_value = None
    app = FastAPI()
    router = create_router(
        session_mgr, MagicMock(), MagicMock(), [],
        native_reader=native_reader, hidden_store=hidden_store,
    )
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_list_includes_native(mock_native_reader):
    mock_native_reader.list_sessions.return_value = [_make_native()]
    client = _test_client(native_reader=mock_native_reader)
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    assert any(s["source"] == "native" for s in resp.json())


def test_get_native_by_id(mock_native_reader):
    native = _make_native()
    mock_native_reader.get_session.return_value = native
    mock_native_reader.get_session_messages.return_value = ([{"type": "user"}], 1)
    client = _test_client(native_reader=mock_native_reader)
    resp = client.get(f"/api/sessions/{native.id}")
    assert resp.status_code == 200
    assert resp.json()["source"] == "native"


def test_send_to_native_active_409(mock_native_reader):
    mock_native_reader.get_session.return_value = _make_native()
    mock_native_reader.get_active_pid.return_value = 12345
    client = _test_client(native_reader=mock_native_reader)
    resp = client.post(f"/api/sessions/{_make_native().id}/send", json={"prompt": "hi"})
    assert resp.status_code == 409


def test_hide_unhide(hidden_store):
    client = _test_client(hidden_store=hidden_store)
    assert client.post("/api/sessions/x/hide").status_code == 200
    assert hidden_store.is_hidden("x")
    assert client.post("/api/sessions/x/unhide").status_code == 200
    assert not hidden_store.is_hidden("x")


def test_hide_permanent(hidden_store):
    client = _test_client(hidden_store=hidden_store)
    assert client.post("/api/sessions/x/hide?permanent=true").status_code == 200
    assert hidden_store.is_permanently_hidden("x")
```

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/test_native_interop.py -v`
Expected: FAIL

- [ ] **Step 1: Update `create_router()` signature**

In `src/claude_code_remote/routes.py`, add parameters and imports:

```python
from claude_code_remote.models import SessionSummary  # add to existing import block
from claude_code_remote.native_sessions import NativeSessionReader
from claude_code_remote.hidden_sessions import HiddenSessionsStore

def create_router(
    ...,
    native_reader=None,
    hidden_store=None,
    native_max_age_days: int = 7,
) -> APIRouter:
```

- [ ] **Step 2: Enhance `GET /api/sessions` to merge native sessions**

```python
@router.get("/sessions")
async def list_sessions(
    request: Request,
    status: SessionStatus | None = None,
    project_dir: str | None = None,
    archived: bool | None = None,
):
    sessions = session_mgr.list_sessions(
        status=status, project_dir=project_dir, archived=archived
    )
    identity = _get_caller_identity(request)
    if identity is not None:
        sessions = [
            s for s in sessions
            if not (full := session_mgr.get_session(s.id))
            or not full.owner or full.owner == identity
            or identity in full.collaborators
        ]

    if native_reader and not status:
        ccr_claude_ids: set[str] = set()
        for s in sessions:
            full = session_mgr.get_session(s.id)
            if full and full.claude_session_id:
                ccr_claude_ids.add(full.claude_session_id)

        hidden_ids = set(hidden_store.list_hidden()) if hidden_store else set()
        is_archived = archived is True
        native_sessions = native_reader.list_sessions(
            max_age_days=None if is_archived else native_max_age_days,
            hidden_ids=hidden_ids, archived=is_archived,
        )

        for ns in native_sessions:
            if ns.id in ccr_claude_ids:
                continue
            if project_dir and project_dir.lower() not in ns.project_dir.lower():
                continue
            active_pid = native_reader.get_active_pid(ns.id)
            sessions.append(SessionSummary(
                id=ns.id, name=ns.name, project_dir=ns.project_dir,
                status=SessionStatus.RUNNING if active_pid else SessionStatus.IDLE,
                model=None, created_at=ns.created_at, updated_at=ns.updated_at,
                total_cost_usd=ns.total_cost_usd, current_model=ns.current_model,
                git_branch=ns.git_branch, message_count=ns.message_count,
                source="native", native_pid=active_pid,
            ))

    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions
```

- [ ] **Step 3: Add native fallthrough to `GET /api/sessions/{id}`**

```python
@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    _check_session_access(session_id, request)
    session = session_mgr.get_session(session_id)
    if session:
        return session

    if native_reader:
        native = native_reader.get_session(session_id)
        if native:
            messages, total = native_reader.get_session_messages(session_id)
            active_pid = native_reader.get_active_pid(session_id)
            return {
                **native.model_dump(),
                "messages": messages,
                "total_messages": total,
                "native_pid": active_pid,
            }

    raise HTTPException(status_code=404, detail="Session not found")
```

- [ ] **Step 4: Add auto-adopt to `POST /api/sessions/{id}/send`**

```python
@router.post("/sessions/{session_id}/send")
async def send_prompt(session_id: str, body: SendPromptRequest, request: Request):
    session = session_mgr.get_session(session_id)

    if not session and native_reader:
        native = native_reader.get_session(session_id)
        if not native:
            raise HTTPException(status_code=404, detail="Session not found")

        active_pid = native_reader.get_active_pid(session_id)
        if active_pid:
            raise HTTPException(
                status_code=409,
                detail=f"Session is active in terminal (PID {active_pid}). Close it first.",
            )

        identity = _get_caller_identity(request)
        try:
            adopted = session_mgr.create_session(
                SessionCreate(
                    name=native.name, project_dir=native.project_dir,
                    initial_prompt="",
                ),
                owner=identity,
            )
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        adopted.claude_session_id = native.claude_session_id
        session_mgr.persist_session(adopted.id)
        await session_mgr.send_prompt(adopted.id, body.prompt)
        return {"ok": True, "adopted": True, "new_session_id": adopted.id}

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    _check_session_access(session_id, request)
    await session_mgr.send_prompt(session_id, body.prompt)
    return {"ok": True}
```

- [ ] **Step 5: Add hide/unhide endpoints**

```python
@router.post("/sessions/{session_id}/hide")
async def hide_session(session_id: str, permanent: bool = False):
    if not hidden_store:
        raise HTTPException(503, "Hidden sessions store not configured")
    hidden_store.hide(session_id, permanent=permanent)
    return {"ok": True}

@router.post("/sessions/{session_id}/unhide")
async def unhide_session(session_id: str):
    if not hidden_store:
        raise HTTPException(503, "Hidden sessions store not configured")
    hidden_store.unhide(session_id)
    return {"ok": True}
```

- [ ] **Step 6: Wire in server.py**

```python
from claude_code_remote.hidden_sessions import HiddenSessionsStore
from claude_code_remote.config import HIDDEN_SESSIONS_FILE

# In create_app(), after native_reader = NativeSessionReader():
hidden_store = HiddenSessionsStore(HIDDEN_SESSIONS_FILE)

api_router = create_router(
    ...,
    native_reader=native_reader,
    hidden_store=hidden_store,
    native_max_age_days=config.get("native_max_age_days", 7),
)
```

- [ ] **Step 7: Run all tests**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/ -v --timeout=30 -x`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add src/claude_code_remote/routes.py src/claude_code_remote/server.py tests/test_native_interop.py
git commit -m "feat: merge native sessions into /api/sessions with auto-adopt and hide/unhide"
```

---

## Task 7: App — Interop Types, Hooks, and UI

**Files:**
- Modify: `/Users/gldc/Developer/claude-code-remote-app/lib/types.ts`
- Modify: `/Users/gldc/Developer/claude-code-remote-app/lib/api.ts`
- Modify: `/Users/gldc/Developer/claude-code-remote-app/components/SessionCard.tsx`
- Modify: `/Users/gldc/Developer/claude-code-remote-app/app/(tabs)/sessions/[id]/index.tsx`

- [ ] **Step 1: Add `source` and `native_pid` to SessionSummary and Session types**

```typescript
// In SessionSummary and Session:
source?: 'ccr' | 'native';
native_pid?: number | null;
```

- [ ] **Step 2: Add `useHideSession` and `useUnhideSession` hooks**

```typescript
export function useHideSession() {
  const baseUrl = useBaseUrl();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ sessionId, permanent = false }: { sessionId: string; permanent?: boolean }) => {
      return apiFetch(`${baseUrl}/api/sessions/${sessionId}/hide?permanent=${permanent}`, { method: 'POST' });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['sessions'] }); },
  });
}

export function useUnhideSession() {
  const baseUrl = useBaseUrl();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (sessionId: string) => {
      return apiFetch(`${baseUrl}/api/sessions/${sessionId}/unhide`, { method: 'POST' });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['sessions'] }); },
  });
}
```

- [ ] **Step 3: Add source badge and Live indicator to SessionCard**

```tsx
// Badge next to session name:
{session.source === 'native' && (
  <View style={{ backgroundColor: colors.surfaceVariant, borderRadius: 4, paddingHorizontal: 6, paddingVertical: 1, marginLeft: 6 }}>
    <Text style={{ fontSize: 10, color: colors.textSecondary }}>Terminal</Text>
  </View>
)}

// Replace status badge when native is active:
{session.native_pid ? (
  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
    <View style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: '#22c55e' }} />
    <Text style={{ fontSize: 11, color: '#22c55e' }}>Live</Text>
  </View>
) : (
  <StatusBadge status={session.status} />
)}
```

- [ ] **Step 4: Wire swipe actions for native sessions**

```tsx
// Swipe-right (delete) for native → permanent hide:
if (session.source === 'native') {
  hideSession.mutate({ sessionId: session.id, permanent: true });
} else {
  deleteSession.mutate(session.id);
}

// Swipe-left (archive) for native → hide:
if (session.source === 'native') {
  hideSession.mutate({ sessionId: session.id });
} else {
  archiveSession.mutate({ sessionId: session.id, archived: !session.archived });
}
```

- [ ] **Step 5: Handle adoption redirect and active-terminal blocking in session detail**

```tsx
// Disable input when native process is active:
const isNativeActive = session?.native_pid != null;
const canSend = session?.status !== 'running'
  && session?.status !== 'awaiting_approval'
  && !isNativeActive;

// Show message:
{isNativeActive && (
  <View style={{ padding: 12, alignItems: 'center' }}>
    <Text style={{ color: colors.textSecondary, fontSize: 13 }}>
      Active in terminal (PID {session.native_pid}) — close it there to send from here
    </Text>
  </View>
)}

// Handle adoption redirect on send:
// Note: useSendPrompt takes a plain string, not an object.
// Change from .mutate(prompt) to .mutateAsync(prompt) to get the response:
const handleSend = async (text: string) => {
  const result = await sendPrompt.mutateAsync(text);
  if (result?.adopted && result?.new_session_id) {
    router.replace(`/(tabs)/sessions/${result.new_session_id}`);
  }
};
```

- [ ] **Step 6: Commit**

```bash
cd /Users/gldc/Developer/claude-code-remote-app
git add lib/types.ts lib/api.ts components/SessionCard.tsx app/(tabs)/sessions/[id]/index.tsx
git commit -m "feat: native session interop UI — source badges, hide actions, adoption redirect"
```

---

## Task 8: Update CLAUDE.md and Final Verification

**Files:**
- Modify: `/Users/gldc/Developer/claude-code-remote/CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

Add under "Important Notes":

```markdown
- **Native event format:** The server passes Claude Code's stream-json events through to clients without translation. Messages stored in `session.messages` use the native format (`assistant`, `tool_result`, `user`, `result`). The only CCR-specific event type is `approval_request`. Old WSMessage-format sessions are migrated on load.
- **Native session interop:** The `/api/sessions` endpoints merge native Claude Code sessions (from `~/.claude/projects/`) with CCR sessions. Native sessions from the last 7 days appear automatically (configurable via `native_max_age_days` in config). Users can hide/unhide native sessions non-destructively. Sending a message to a native session "adopts" it as a CCR session. Active native processes (checked via PID) block concurrent access from the app.
```

Add to API Endpoints:

```markdown
- `POST /api/sessions/{id}/hide` -- Hide native session (add `?permanent=true` for permanent)
- `POST /api/sessions/{id}/unhide` -- Unhide a hidden native session
```

- [ ] **Step 2: Run full test suite**

Run: `cd /Users/gldc/Developer/claude-code-remote && python -m pytest tests/ -v --timeout=30`
Expected: All tests pass

- [ ] **Step 3: Manual smoke test**

1. Start server: `ccr start --no-auth`
2. `curl localhost:8080/api/sessions` — should show CCR + recent native sessions
3. `curl localhost:8080/api/sessions/<native-uuid>` — native session detail with messages in native format
4. Open an existing CCR session — messages should render correctly (migrated from old format)
5. Create a new CCR session, send a prompt — messages in native format over WebSocket
6. `curl -X POST localhost:8080/api/sessions/<native-uuid>/hide` — hides from list
7. `curl localhost:8080/api/sessions?archived=true` — hidden sessions appear

- [ ] **Step 4: Commit**

```bash
cd /Users/gldc/Developer/claude-code-remote
git add CLAUDE.md
git commit -m "docs: document native event format and session interop"
```
