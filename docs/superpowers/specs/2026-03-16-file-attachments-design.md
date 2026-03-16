# File Attachments from Mobile App

## Problem

Users can only send text prompts from the mobile app. There's no way to share photos (e.g., UI bug screenshots) or files (e.g., PDF specs) with Claude from the phone. Users must manually transfer files to the Mac and reference them by path.

## Solution

Add file attachment support to the mobile app. Files are uploaded to the CCR server, saved to `claude-uploads/` in the session's project directory, and referenced by path in the prompt. Claude reads them using its existing `Read` tool (which supports images and PDFs natively). No changes to how Claude Code is spawned.

## Upload Endpoint

### `POST /api/sessions/{id}/upload`

- **Content type:** `multipart/form-data`
- **Accepts:** One or more files in the `files` form field
- **Auth:** Same Tailscale identity check as other session endpoints (`_check_session_access`)
- **Session state:** Upload allowed in any state except `completed` (400 if completed)
- **Storage:** `{session.project_dir}/claude-uploads/`
  - Creates directory if it doesn't exist
  - Auto-appends `claude-uploads/` to the project's `.gitignore` if not already present (creates `.gitignore` if needed)
- **Filename sanitization:**
  - Strip to basename only (no directory components)
  - Replace characters outside `[a-zA-Z0-9._-]` with `_`
  - Reject empty filenames after sanitization (400 error)
  - Verify resolved path stays within `claude-uploads/` (prevent path traversal)
- **Filename collision:** Appends `-1`, `-2`, etc. before the extension (e.g., `screenshot.png` -> `screenshot-1.png`)
- **File size:** No hard limit, but use streaming writes via `aiofiles` to avoid buffering entire file in memory (FastAPI's `UploadFile.read()` in chunks)
- **Response:**
```json
{
  "files": [
    {
      "name": "screenshot.png",
      "path": "./claude-uploads/screenshot.png",
      "size": 2048000
    }
  ]
}
```
- **Errors:** 404 if session not found, 403 if no access, 400 if no files provided, 400 if session is completed, 400 if filename invalid after sanitization

## Prompt Construction

When the user sends a message with attachments, the app constructs the prompt by prepending file references:

```
<attached-files>
These files were uploaded from the user's mobile device. Use the Read tool to view each one.
- ./claude-uploads/screenshot-2026-03-16-1042.png
- ./claude-uploads/design-spec.pdf
</attached-files>

Fix the layout bug shown in the screenshot
```

XML-style tags make the instruction unambiguous for Claude. The `Read` tool works with relative paths since Claude is spawned with `cwd=session.project_dir`.

This is done client-side before calling `POST /api/sessions/{id}/send` with the constructed prompt string. No changes to `SendPromptRequest` or `send_prompt` -- it's still a text prompt.

## App UI Changes

### InputBar

- **Attachment button:** Paperclip icon to the left of the text input
- **Action sheet on tap:** Three options:
  - "Take Photo" -- launches camera via `expo-image-picker` (`launchCameraAsync`)
  - "Photo Library" -- launches photo picker via `expo-image-picker` (`launchImageLibraryAsync`, `mediaTypes: ['images']` to exclude video)
  - "Choose File" -- launches file picker via `expo-document-picker` (no type restriction -- PDFs, text files, etc.)
- **Pending attachments:** Row of thumbnails (images) or file name badges (non-images) displayed above the input bar
  - Tap X on a thumbnail/badge to remove it before sending
  - Multiple attachments supported
- **Send flow:**
  1. User taps send
  2. App uploads all pending files to `POST /api/sessions/{id}/upload`
  3. If upload fails, show error and keep attachments (don't clear)
  4. If upload succeeds, construct prompt with file path references prepended
  5. Call `POST /api/sessions/{id}/send` with the constructed prompt
  6. If send fails after upload, files are already on disk (acceptable -- they don't cause harm)
  7. Pending attachments cleared on success

### Permissions

- Camera permission requested on first camera use (`expo-image-picker` handles this)
- Photo library permission requested on first use
- No special permissions needed for document picker

## Backend Implementation

### New file: `src/claude_code_remote/uploads.py`

Handles file storage, sanitization, and gitignore management:
- `sanitize_filename(filename: str) -> str` -- strips to basename, replaces unsafe chars, rejects empty
- `save_upload(project_dir: str, filename: str, content: bytes) -> dict` -- saves file with collision handling, returns metadata
- `ensure_gitignore(project_dir: str)` -- appends `claude-uploads/` to `.gitignore` if not present

### Modified file: `src/claude_code_remote/routes.py`

- Add `POST /api/sessions/{id}/upload` endpoint
- Accept `List[UploadFile]` from FastAPI's multipart support
- Read file content in chunks to avoid OOM on large files
- Call `save_upload` for each file
- Return file metadata list

### Modified file: `src/claude_code_remote/models.py`

- Add `UploadedFile` response model: `name: str`, `path: str`, `size: int`
- Add `UploadResponse` model: `files: list[UploadedFile]`

## App Implementation

### Added to `lib/api.ts`

- `useUploadFiles(sessionId)` -- mutation hook that uploads files via multipart FormData POST
- Returns list of uploaded file metadata (paths)

### Modified file: `components/InputBar.tsx`

- Add attachment button and action sheet
- Manage pending attachments state (list of `{ uri, name, type }`)
- Show attachment preview row above input
- On send: upload then construct prompt with XML-tagged file references

### Dependencies (require native rebuild)

- `expo-image-picker` -- NOT currently installed, needs `npx expo install expo-image-picker`
- `expo-document-picker` -- NOT currently installed, needs `npx expo install expo-document-picker`
- Both are native modules requiring an EAS dev client rebuild (`eas build --profile development`)

## What Does NOT Change

- `session_manager.py` `send_prompt` -- still receives a text prompt
- Claude Code CLI invocation -- still uses `-p` with text
- `SendPromptRequest` model -- still just `{ prompt: string }` (max 100,000 chars, file paths are short)
- WebSocket message format -- no changes
- Stream-json parsing -- no changes

## File Cleanup

Uploaded files persist in `claude-uploads/` indefinitely. They are:
- Gitignored (not committed)
- The user's responsibility to clean up
- NOT automatically deleted when a session is deleted (files belong to the project, not the session)

## Testing

- Upload a photo from camera, verify it lands in `claude-uploads/`
- Upload a photo from library, verify prompt includes path
- Upload a PDF, verify Claude can read it
- Upload with filename collision, verify `-1` suffix
- Verify `.gitignore` is created/updated on first upload
- Send message with no attachments -- unchanged behavior
- Remove attachment before sending -- works correctly
- Malicious filename (e.g., `../../.env`) -- sanitized to safe basename
- Upload to completed session -- returns 400
- Upload fails mid-send -- error shown, attachments preserved for retry
