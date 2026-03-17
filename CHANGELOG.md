# Changelog

## [0.3.0] - 2026-03-17

### Added
- Native session interop -- native Claude Code terminal sessions appear in `/api/sessions` alongside CCR sessions
- Hidden sessions store -- non-destructive hide/unhide for native sessions (archive and permanent hide)
- JSONL sync -- session messages synced from native JSONL source of truth when switching between terminal and app
- Server-side normalization of native JSONL tool results to stream-JSON format
- Server hostname exposed in `/api/status` for native session badges in the app
- `POST /api/sessions/{id}/hide` and `/unhide` endpoints
- `native_max_age_days` config option (default: 7) for native session recency filtering
- `source` and `native_pid` fields on `SessionSummary` for native session identification
- Active PID detection to prevent concurrent access from app and terminal
- Batch-loaded active PIDs in session list to avoid N+1 filesystem reads

### Changed
- Replaced WSMessage format with native Claude Code stream-json passthrough -- server is now a thin relay
- Removed `WSMessageType` enum and `WSMessage` class from models
- Session messages stored in native event format (`assistant`, `tool_result`, `user`, `result`)
- Old WSMessage-format sessions automatically migrated on load
- `search_sessions()` and `_to_summary()` updated for native event structure

### Fixed
- JSONL sync uses timestamp comparison instead of message counts (counts were unreliable across different event type sets)
- JSONL sync runs at start of `send_prompt()` to catch terminal messages between CCR turns (previous guard blocked sync during active sessions)
- Session list preview no longer shows raw JSON from internal protocol messages
- Git status/diff/branches/log endpoints return empty results instead of 500 for non-git project directories
- Synthetic `result` event only emitted on process exit when CLI didn't send one (prevents duplicates)

## [0.2.0] - 2026-03-16

### Added
- File attachment uploads from mobile app
- Dashboard API with unified CCR + native session views, analytics, and cron management
- Native Claude Code session discovery from `~/.claude/projects/`
- Cron job scheduling with APScheduler
- Orphan process cleanup on `ccr stop` and `ccr start`
- Menubar status indicator

## [0.1.0] - 2026-03-14

### Added
- Initial release -- FastAPI server for managing Claude Code sessions remotely
- REST API + WebSocket for session lifecycle management
- Tailscale WhoIs authentication
- PreToolUse approval hook
- Expo push notifications
- Template and project management
- MCP server discovery
- Workflow engine
