# File Attachments Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users attach photos and files from their phone when sending messages to Claude Code sessions.

**Architecture:** The app picks files via expo-image-picker/expo-document-picker, uploads them to a new server endpoint that saves to `claude-uploads/` in the project directory, and prepends file path references to the text prompt. Claude reads the files with its existing `Read` tool. No changes to how Claude Code is spawned.

**Tech Stack:** Python/FastAPI (backend), React Native/Expo (app), expo-image-picker, expo-document-picker

**Spec:** `docs/superpowers/specs/2026-03-16-file-attachments-design.md`

---

## File Map

### Backend (claude-code-remote)

| File | Action | Purpose |
|------|--------|---------|
| `src/claude_code_remote/uploads.py` | Create | File storage, sanitization, gitignore management |
| `src/claude_code_remote/models.py` | Modify | Add `UploadedFile` and `UploadResponse` models |
| `src/claude_code_remote/routes.py` | Modify | Add `POST /api/sessions/{id}/upload` endpoint |
| `tests/test_uploads.py` | Create | Tests for upload logic |

### App (claude-code-remote-app)

| File | Action | Purpose |
|------|--------|---------|
| `lib/api.ts` | Modify | Add `useUploadFiles` mutation hook |
| `components/InputBar.tsx` | Modify | Add attachment button, preview row, upload-then-send flow |
| `components/AttachmentPreview.tsx` | Create | Thumbnail/badge row for pending attachments |
| `package.json` | Modify | Add expo-image-picker, expo-document-picker |

---

## Chunk 1: Backend — Upload Module and Endpoint

### Task 1: Add Pydantic models for upload response

**Files:**
- Modify: `src/claude_code_remote/models.py` (append after line 536)

- [ ] **Step 1: Add the models**

Append to the end of `models.py`:

```python


# --- Uploads ---


class UploadedFile(BaseModel):
    name: str
    path: str
    size: int


class UploadResponse(BaseModel):
    files: list[UploadedFile]
```

- [ ] **Step 2: Verify import**

Run: `python -c "from claude_code_remote.models import UploadedFile, UploadResponse; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_code_remote/models.py
git commit -m "feat(uploads): add UploadedFile and UploadResponse models"
```

---

### Task 2: Create uploads.py with tests

**Files:**
- Create: `src/claude_code_remote/uploads.py`
- Create: `tests/test_uploads.py`

- [ ] **Step 1: Write tests**

Create `tests/test_uploads.py`:

```python
"""Tests for file upload utilities."""

import os
from pathlib import Path

import pytest

from claude_code_remote.uploads import sanitize_filename, save_upload, ensure_gitignore


def test_sanitize_filename_basic():
    assert sanitize_filename("screenshot.png") == "screenshot.png"


def test_sanitize_filename_strips_directory():
    # basename("../../.env") = ".env", lstrip(".") = "env"
    assert sanitize_filename("../../.env") == "env"


def test_sanitize_filename_replaces_unsafe_chars():
    assert sanitize_filename("my file (1).png") == "my_file__1_.png"


def test_sanitize_filename_preserves_safe_chars():
    assert sanitize_filename("my-file_v2.3.pdf") == "my-file_v2.3.pdf"


def test_sanitize_filename_rejects_empty():
    with pytest.raises(ValueError):
        sanitize_filename("")


def test_sanitize_filename_rejects_dots_only():
    with pytest.raises(ValueError):
        sanitize_filename("...")


def test_save_upload(tmp_path):
    result = save_upload(str(tmp_path), "test.png", b"fake image data")
    assert result["name"] == "test.png"
    assert result["path"] == "./claude-uploads/test.png"
    assert result["size"] == len(b"fake image data")
    assert (tmp_path / "claude-uploads" / "test.png").exists()
    assert (tmp_path / "claude-uploads" / "test.png").read_bytes() == b"fake image data"


def test_save_upload_collision(tmp_path):
    save_upload(str(tmp_path), "test.png", b"first")
    result = save_upload(str(tmp_path), "test.png", b"second")
    assert result["name"] == "test-1.png"
    assert result["path"] == "./claude-uploads/test-1.png"
    assert (tmp_path / "claude-uploads" / "test-1.png").read_bytes() == b"second"


def test_save_upload_multiple_collisions(tmp_path):
    save_upload(str(tmp_path), "test.png", b"1")
    save_upload(str(tmp_path), "test.png", b"2")
    result = save_upload(str(tmp_path), "test.png", b"3")
    assert result["name"] == "test-2.png"


def test_save_upload_no_extension_collision(tmp_path):
    save_upload(str(tmp_path), "README", b"1")
    result = save_upload(str(tmp_path), "README", b"2")
    assert result["name"] == "README-1"


def test_save_upload_creates_directory(tmp_path):
    assert not (tmp_path / "claude-uploads").exists()
    save_upload(str(tmp_path), "test.txt", b"data")
    assert (tmp_path / "claude-uploads").is_dir()


def test_save_upload_path_traversal_blocked(tmp_path):
    """Filenames that resolve outside claude-uploads/ should be sanitized."""
    result = save_upload(str(tmp_path), "../../../etc/passwd", b"data")
    assert "etc" not in result["path"] or "claude-uploads" in result["path"]
    # File must be inside claude-uploads
    saved_path = tmp_path / "claude-uploads" / result["name"]
    assert saved_path.exists()


def test_ensure_gitignore_creates(tmp_path):
    ensure_gitignore(str(tmp_path))
    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert "claude-uploads/" in gitignore.read_text()


def test_ensure_gitignore_appends(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    ensure_gitignore(str(tmp_path))
    content = (tmp_path / ".gitignore").read_text()
    assert "node_modules/" in content
    assert "claude-uploads/" in content


def test_ensure_gitignore_idempotent(tmp_path):
    ensure_gitignore(str(tmp_path))
    ensure_gitignore(str(tmp_path))
    content = (tmp_path / ".gitignore").read_text()
    assert content.count("claude-uploads/") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_uploads.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement uploads.py**

Create `src/claude_code_remote/uploads.py`:

```python
"""File upload utilities — storage, sanitization, and gitignore management."""

from __future__ import annotations

import os
import re
from pathlib import Path

UPLOAD_DIR_NAME = "claude-uploads"


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename: strip directories, replace unsafe chars.

    Raises ValueError if filename is empty after sanitization.
    """
    # Strip to basename only
    name = os.path.basename(filename)
    # Replace unsafe characters
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    # Strip leading dots (hidden files)
    name = name.lstrip(".")
    if not name:
        raise ValueError("Filename is empty after sanitization")
    return name


def _resolve_collision(upload_dir: Path, name: str) -> str:
    """Generate a unique filename by appending -1, -2, etc."""
    if not (upload_dir / name).exists():
        return name

    stem, _, ext = name.rpartition(".")
    if not stem:
        # No extension (e.g., "README")
        stem = name
        ext = ""

    counter = 1
    while True:
        if ext:
            candidate = f"{stem}-{counter}.{ext}"
        else:
            candidate = f"{stem}-{counter}"
        if not (upload_dir / candidate).exists():
            return candidate
        counter += 1


def save_upload(project_dir: str, filename: str, content: bytes) -> dict:
    """Save an uploaded file to claude-uploads/ in the project directory.

    Returns dict with name, path (relative), and size.
    """
    safe_name = sanitize_filename(filename)
    upload_dir = Path(project_dir) / UPLOAD_DIR_NAME
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Resolve collisions
    final_name = _resolve_collision(upload_dir, safe_name)
    dest = upload_dir / final_name

    # Verify path stays within upload_dir (defense in depth)
    if not dest.resolve().is_relative_to(upload_dir.resolve()):
        raise ValueError(f"Path traversal detected: {final_name}")

    dest.write_bytes(content)

    return {
        "name": final_name,
        "path": f"./{UPLOAD_DIR_NAME}/{final_name}",
        "size": len(content),
    }


def ensure_gitignore(project_dir: str) -> None:
    """Ensure claude-uploads/ is in the project's .gitignore."""
    gitignore_path = Path(project_dir) / ".gitignore"
    entry = f"{UPLOAD_DIR_NAME}/"

    if gitignore_path.exists():
        content = gitignore_path.read_text()
        if entry in content:
            return
        # Ensure we start on a new line
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore_path.write_text(content)
    else:
        gitignore_path.write_text(f"{entry}\n")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_uploads.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_code_remote/uploads.py tests/test_uploads.py
git commit -m "feat(uploads): add file upload utilities with sanitization and gitignore management"
```

---

### Task 3: Add upload endpoint to routes.py

**Files:**
- Modify: `src/claude_code_remote/routes.py`

- [ ] **Step 1: Add the upload endpoint**

Add imports at the top of `routes.py` (after existing imports around line 39):

```python
from fastapi import UploadFile, File
from claude_code_remote.uploads import save_upload, ensure_gitignore
from claude_code_remote.models import UploadedFile, UploadResponse
```

Note: `UploadFile` and `File` need to be added to the existing `from fastapi import ...` line at line 13. Merge them:

```python
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
```

Add the endpoint after the `send_prompt` endpoint (find `async def send_prompt`), after the `return {"ok": True}` on the line after it:

```python
    @router.post("/sessions/{session_id}/upload")
    async def upload_files(
        session_id: str,
        request: Request,
        files: list[UploadFile] = File(...),
    ):
        """Upload files to the session's project directory."""
        _check_session_access(session_id, request)
        session = session_mgr.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session.status.value == "completed":
            raise HTTPException(
                status_code=400, detail="Cannot upload to a completed session"
            )
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        ensure_gitignore(session.project_dir)

        # Note: reads entire file into memory. The spec calls for streaming
        # writes via aiofiles, but for v1 this is simpler and acceptable since
        # the user controls what they upload (no untrusted input). If OOM
        # becomes an issue with very large files, refactor to stream chunks.
        uploaded = []
        for f in files:
            content = await f.read()
            try:
                result = save_upload(session.project_dir, f.filename or "unnamed", content)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            uploaded.append(UploadedFile(**result))

        return UploadResponse(files=uploaded)
```

- [ ] **Step 2: Verify import**

Run: `python -c "from claude_code_remote.routes import create_router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: All tests pass (existing + new)

- [ ] **Step 4: Commit**

```bash
git add src/claude_code_remote/routes.py
git commit -m "feat(uploads): add POST /api/sessions/{id}/upload endpoint"
```

---

## Chunk 2: App — Dependencies, API Hook, and InputBar Changes

### Task 4: Install native dependencies

**Files:**
- Modify: `/Users/gldc/Developer/claude-code-remote-app/package.json`

- [ ] **Step 1: Install expo-image-picker and expo-document-picker**

Run:
```bash
cd /Users/gldc/Developer/claude-code-remote-app
npx expo install expo-image-picker expo-document-picker
```
Expected: Both packages added to `package.json` dependencies

- [ ] **Step 2: Commit**

```bash
cd /Users/gldc/Developer/claude-code-remote-app
git add package.json package-lock.json
git commit -m "feat(uploads): add expo-image-picker and expo-document-picker dependencies"
```

**Note:** These are native modules. A dev client rebuild (`eas build --profile development`) will be needed before testing on device. However, the JS code can be written and committed first.

---

### Task 5: Add upload API hook

**Files:**
- Modify: `/Users/gldc/Developer/claude-code-remote-app/lib/api.ts`

- [ ] **Step 1: Add the upload mutation hook**

Add after the `useSendPrompt` function (find the closing `}` of `useSendPrompt` around line 193), before `useApproveToolUse`:

```typescript
export interface UploadedFile {
  name: string;
  path: string;
  size: number;
}

export function useUploadFiles(sessionId: string) {
  const baseUrl = useBaseUrl();
  return useMutation({
    mutationFn: async (files: { uri: string; name: string; type: string }[]) => {
      const formData = new FormData();
      for (const file of files) {
        formData.append('files', {
          uri: file.uri,
          name: file.name,
          type: file.type,
        } as unknown as Blob);
      }
      const resp = await fetch(`${baseUrl}/api/sessions/${sessionId}/upload`, {
        method: 'POST',
        body: formData,
        // Do NOT set Content-Type — fetch sets it with the boundary for multipart
      });
      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(`Upload failed: ${resp.status} ${body}`);
      }
      return resp.json() as Promise<{ files: UploadedFile[] }>;
    },
  });
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/gldc/Developer/claude-code-remote-app
git add lib/api.ts
git commit -m "feat(uploads): add useUploadFiles mutation hook"
```

---

### Task 6: Create AttachmentPreview component

**Files:**
- Create: `/Users/gldc/Developer/claude-code-remote-app/components/AttachmentPreview.tsx`

- [ ] **Step 1: Create the component**

Create `/Users/gldc/Developer/claude-code-remote-app/components/AttachmentPreview.tsx`:

```tsx
import { View, Text, Image, TouchableOpacity, ScrollView, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useColors, useThemedStyles, type ColorPalette, FontSize, Spacing, BorderRadius } from '../constants/theme';

export interface PendingAttachment {
  uri: string;
  name: string;
  type: string;
}

interface Props {
  attachments: PendingAttachment[];
  onRemove: (index: number) => void;
}

export function AttachmentPreview({ attachments, onRemove }: Props) {
  const colors = useColors();
  const styles = useThemedStyles(colors, makeStyles);

  if (!attachments.length) return null;

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.container}
      contentContainerStyle={styles.content}
    >
      {attachments.map((att, i) => {
        const isImage = att.type.startsWith('image/');
        return (
          <View key={`${att.name}-${i}`} style={styles.item}>
            {isImage ? (
              <Image source={{ uri: att.uri }} style={styles.thumbnail} />
            ) : (
              <View style={styles.fileBadge}>
                <Ionicons name="document" size={20} color={colors.textMuted} />
              </View>
            )}
            <Text style={styles.name} numberOfLines={1}>
              {att.name}
            </Text>
            <TouchableOpacity
              style={styles.removeButton}
              onPress={() => onRemove(i)}
              hitSlop={{ top: 8, right: 8, bottom: 8, left: 8 }}
            >
              <Ionicons name="close-circle" size={18} color={colors.textMuted} />
            </TouchableOpacity>
          </View>
        );
      })}
    </ScrollView>
  );
}

const makeStyles = (c: ColorPalette) =>
  StyleSheet.create({
    container: {
      maxHeight: 80,
    },
    content: {
      paddingHorizontal: Spacing.md,
      paddingVertical: Spacing.xs,
      gap: Spacing.sm,
    },
    item: {
      width: 64,
      alignItems: 'center',
      position: 'relative',
    },
    thumbnail: {
      width: 52,
      height: 52,
      borderRadius: BorderRadius.md,
      backgroundColor: c.card,
    },
    fileBadge: {
      width: 52,
      height: 52,
      borderRadius: BorderRadius.md,
      backgroundColor: c.card,
      borderWidth: 1,
      borderColor: c.cardBorder,
      alignItems: 'center',
      justifyContent: 'center',
    },
    name: {
      fontSize: FontSize.xs,
      color: c.textMuted,
      marginTop: 2,
      width: 60,
      textAlign: 'center',
    },
    removeButton: {
      position: 'absolute',
      top: -4,
      right: -2,
    },
  });
```

- [ ] **Step 2: Commit**

```bash
cd /Users/gldc/Developer/claude-code-remote-app
git add components/AttachmentPreview.tsx
git commit -m "feat(uploads): add AttachmentPreview component"
```

---

### Task 7: Update InputBar with attachment support

**Files:**
- Modify: `/Users/gldc/Developer/claude-code-remote-app/components/InputBar.tsx`

- [ ] **Step 1: Replace InputBar.tsx**

Replace the entire file `/Users/gldc/Developer/claude-code-remote-app/components/InputBar.tsx` with:

```tsx
import { useState, useEffect } from 'react';
import { View, TextInput, TouchableOpacity, StyleSheet, ActionSheetIOS, Platform, Alert } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import * as DocumentPicker from 'expo-document-picker';
import * as Haptics from 'expo-haptics';
import { useColors, useThemedStyles, type ColorPalette, FontSize, Spacing, BorderRadius, ComponentSize } from '../constants/theme';
import { CommandAutocomplete } from './CommandAutocomplete';
import { AttachmentPreview, type PendingAttachment } from './AttachmentPreview';
import type { SlashCommand } from '../constants/commands';

interface InputBarProps {
  onSend: (text: string, attachments?: PendingAttachment[]) => void;
  onCommand?: (command: SlashCommand) => void;
  disabled?: boolean;
  placeholder?: string;
  initialText?: string | null;
}

export function InputBar({ onSend, onCommand, disabled, placeholder, initialText }: InputBarProps) {
  const [text, setText] = useState('');
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);

  useEffect(() => {
    if (initialText) {
      setText(initialText);
    }
  }, [initialText]);
  const colors = useColors();
  const styles = useThemedStyles(colors, makeStyles);

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed && !attachments.length) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onSend(trimmed, attachments.length > 0 ? attachments : undefined);
    setText('');
    setAttachments([]);
  };

  const handleCommandSelect = (command: SlashCommand) => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    setText('');
    setAttachments([]);
    if (command.type === 'app') {
      onCommand?.(command);
    } else {
      onSend(`/${command.name}`);
    }
  };

  const handleAttach = () => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    if (Platform.OS === 'ios') {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: ['Cancel', 'Take Photo', 'Photo Library', 'Choose File'],
          cancelButtonIndex: 0,
        },
        (buttonIndex) => {
          if (buttonIndex === 1) pickCamera();
          else if (buttonIndex === 2) pickLibrary();
          else if (buttonIndex === 3) pickDocument();
        }
      );
    } else {
      // Android: use Alert as a simple menu
      Alert.alert('Attach', 'Choose an option', [
        { text: 'Take Photo', onPress: pickCamera },
        { text: 'Photo Library', onPress: pickLibrary },
        { text: 'Choose File', onPress: pickDocument },
        { text: 'Cancel', style: 'cancel' },
      ]);
    }
  };

  const pickCamera = async () => {
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert('Permission needed', 'Camera access is required to take photos.');
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      quality: 0.8,
    });
    if (!result.canceled && result.assets.length > 0) {
      const asset = result.assets[0];
      setAttachments((prev) => [
        ...prev,
        {
          uri: asset.uri,
          name: asset.fileName || `photo-${Date.now()}.jpg`,
          type: asset.mimeType || 'image/jpeg',
        },
      ]);
    }
  };

  const pickLibrary = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.8,
      allowsMultipleSelection: true,
    });
    if (!result.canceled) {
      const newAttachments = result.assets.map((asset) => ({
        uri: asset.uri,
        name: asset.fileName || `image-${Date.now()}.jpg`,
        type: asset.mimeType || 'image/jpeg',
      }));
      setAttachments((prev) => [...prev, ...newAttachments]);
    }
  };

  const pickDocument = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      multiple: true,
    });
    if (!result.canceled) {
      const newAttachments = result.assets.map((asset) => ({
        uri: asset.uri,
        name: asset.name,
        type: asset.mimeType || 'application/octet-stream',
      }));
      setAttachments((prev) => [...prev, ...newAttachments]);
    }
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const showAutocomplete = text.startsWith('/') && text.trim().length > 0;
  const canSend = (text.trim().length > 0 || attachments.length > 0) && !disabled;

  return (
    <View style={styles.container}>
      {showAutocomplete && (
        <CommandAutocomplete filter={text.trim()} onSelect={handleCommandSelect} />
      )}
      <AttachmentPreview attachments={attachments} onRemove={removeAttachment} />
      <View style={styles.inputRow}>
        <TouchableOpacity
          onPress={handleAttach}
          disabled={disabled}
          style={styles.attachButton}
        >
          <Ionicons
            name="attach"
            size={22}
            color={disabled ? colors.textMuted : colors.textSecondary}
          />
        </TouchableOpacity>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={setText}
          placeholder={placeholder || 'Message Claude...'}
          placeholderTextColor={colors.textMuted}
          multiline
          maxLength={10000}
          editable={!disabled}
          onSubmitEditing={handleSend}
          blurOnSubmit={false}
        />
        <TouchableOpacity
          style={[styles.sendButton, canSend && styles.sendButtonActive]}
          onPress={handleSend}
          disabled={!canSend}
        >
          <Ionicons
            name="arrow-up"
            size={18}
            color={canSend ? colors.buttonText : colors.textMuted}
          />
        </TouchableOpacity>
      </View>
    </View>
  );
}

const makeStyles = (c: ColorPalette) =>
  StyleSheet.create({
    container: {
      paddingHorizontal: Spacing.md,
      paddingTop: Spacing.sm,
      paddingBottom: Spacing.xl,
      backgroundColor: c.background,
      borderTopWidth: StyleSheet.hairlineWidth,
      borderTopColor: c.cardBorder,
    },
    inputRow: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      backgroundColor: c.card,
      borderRadius: BorderRadius.xl,
      borderWidth: 1,
      borderColor: c.cardBorder,
      paddingLeft: 4,
      paddingRight: 4,
      paddingVertical: 4,
      gap: Spacing.xs,
    },
    attachButton: {
      width: ComponentSize.sendButton,
      height: ComponentSize.sendButton,
      alignItems: 'center',
      justifyContent: 'center',
    },
    input: {
      flex: 1,
      color: c.text,
      fontSize: FontSize.md,
      maxHeight: 120,
      paddingVertical: Spacing.sm,
      lineHeight: 21,
    },
    sendButton: {
      width: ComponentSize.sendButton,
      height: ComponentSize.sendButton,
      borderRadius: ComponentSize.sendButton / 2,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: c.cardBorder,
    },
    sendButtonActive: {
      backgroundColor: c.primary,
    },
  });
```

- [ ] **Step 2: Commit**

```bash
cd /Users/gldc/Developer/claude-code-remote-app
git add components/InputBar.tsx
git commit -m "feat(uploads): add attachment button, camera/library/file pickers to InputBar"
```

---

### Task 8: Wire upload-then-send flow in session detail

**Files:**
- Modify: `/Users/gldc/Developer/claude-code-remote-app/app/(tabs)/sessions/[id]/index.tsx`

- [ ] **Step 1: Update session detail to handle attachments**

In `app/(tabs)/sessions/[id]/index.tsx`, make these changes:

1. Add `useUploadFiles` to the import from `lib/api`:

Find:
```typescript
import { useSession, usePauseSession, useSendPrompt, useExportSession, useShowCost } from '../../../../lib/api';
```
Replace with:
```typescript
import { useSession, usePauseSession, useSendPrompt, useExportSession, useShowCost, useUploadFiles } from '../../../../lib/api';
```

2. Add the `PendingAttachment` type import:

Find:
```typescript
import { InputBar } from '../../../../components/InputBar';
```
Replace with:
```typescript
import { InputBar } from '../../../../components/InputBar';
import type { PendingAttachment } from '../../../../components/AttachmentPreview';
```

3. Add the upload hook after `useSendPrompt`:

Find:
```typescript
  const sendPrompt = useSendPrompt(id);
```
Add after:
```typescript
  const uploadFiles = useUploadFiles(id);
```

4. Update the `onSend` handler in the InputBar JSX to handle attachments:

Find:
```tsx
  <InputBar
    onSend={(text) => {
      sendPrompt.mutate(text);
    }}
```
Replace with:
```tsx
  <InputBar
    onSend={async (text, attachments) => {
      let prompt = text;
      if (attachments?.length) {
        try {
          const result = await uploadFiles.mutateAsync(attachments);
          const paths = result.files.map((f) => `- ${f.path}`).join('\n');
          prompt = `<attached-files>\nThese files were uploaded from the user\'s mobile device. Use the Read tool to view each one.\n${paths}\n</attached-files>\n\n${text}`;
        } catch {
          Alert.alert('Upload Failed', 'Could not upload attachments. Please try again.');
          return;
        }
      }
      if (prompt.trim()) {
        sendPrompt.mutate(prompt);
      }
    }}
```

5. Update the `disabled` prop to include upload pending state:

Find:
```tsx
    disabled={sendPrompt.isPending}
```
Replace with:
```tsx
    disabled={sendPrompt.isPending || uploadFiles.isPending}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/gldc/Developer/claude-code-remote-app
git add app/\(tabs\)/sessions/\[id\]/index.tsx
git commit -m "feat(uploads): wire upload-then-send flow in session detail screen"
```

---

## Chunk 3: Verification

### Task 9: Backend smoke test

- [ ] **Step 1: Run backend tests**

Run: `pytest tests/test_uploads.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run all backend tests**

Run: `pytest tests/ -v --tb=short -q`
Expected: No new failures

- [ ] **Step 3: Manual upload test via curl**

Start server: `ccr start --no-auth`

```bash
# Create a test file
echo "test content" > /tmp/test-upload.txt

# Upload it
curl -X POST "http://127.0.0.1:8080/api/sessions/<session-id>/upload" \
  -F "files=@/tmp/test-upload.txt" | python3 -m json.tool
```

Expected: `{ "files": [{ "name": "test-upload.txt", "path": "./claude-uploads/test-upload.txt", "size": 13 }] }`

Verify the file exists in the session's project directory under `claude-uploads/`.

Stop server: `ccr stop`

### Task 10: App build check

- [ ] **Step 1: TypeScript check**

Run: `cd /Users/gldc/Developer/claude-code-remote-app && npx tsc --noEmit`
Expected: No type errors

**Note:** Full device testing requires a dev client rebuild:
```bash
eas build --profile development --platform ios
```
This can be done after merge as it takes ~10 minutes.
