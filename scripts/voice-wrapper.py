#!/usr/bin/env python3
"""Voice dictation wrapper for ttyd terminal on iPhone.

Serves a page with the ttyd terminal in an iframe and a native text input
field at the bottom. Dictation works in the native input, then text is
injected into the tmux session via `tmux send-keys`.
"""

import subprocess
import shutil

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

TMUX = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
TAILSCALE = shutil.which("tailscale") or "/usr/local/bin/tailscale"
TTYD_PORT = 7681
WRAPPER_PORT = 8080
TMUX_SESSION = "claude"


app = FastAPI()


def get_tailscale_ip():
    result = subprocess.run(
        [TAILSCALE, "ip", "-4"], capture_output=True, text=True
    )
    return result.stdout.strip()


class TextInput(BaseModel):
    text: str


class KeyInput(BaseModel):
    key: str


@app.get("/", response_class=HTMLResponse)
async def index():
    ip = get_tailscale_ip()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Claude Code Remote</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{
            height: 100%;
            background: #1a1a1a;
            overflow: hidden;
            font-family: -apple-system, system-ui, sans-serif;
            touch-action: manipulation;
        }}
        .container {{
            display: flex;
            flex-direction: column;
            height: 100vh;
            height: 100dvh;
        }}
        .terminal-frame {{
            flex: 1;
            border: none;
            width: 100%;
        }}
        .quick-keys {{
            display: flex;
            gap: 4px;
            padding: 4px 6px;
            background: #252525;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }}
        .quick-keys button {{
            padding: 8px 14px;
            font-size: 14px;
            font-family: 'Menlo', monospace;
            border: 1px solid #555;
            border-radius: 4px;
            background: #333;
            color: #ccc;
            cursor: pointer;
            white-space: nowrap;
            flex-shrink: 0;
        }}
        .quick-keys button:active {{
            background: #555;
        }}
        .input-bar {{
            display: flex;
            gap: 6px;
            padding: 6px;
            background: #2d2d2d;
            border-top: 1px solid #444;
        }}
        .input-bar input {{
            flex: 1;
            padding: 10px 12px;
            font-size: 16px;
            border: 1px solid #555;
            border-radius: 8px;
            background: #1a1a1a;
            color: #fff;
            outline: none;
        }}
        .input-bar input:focus {{
            border-color: #007aff;
        }}
        .input-bar button {{
            padding: 10px 18px;
            font-size: 16px;
            font-weight: 600;
            border: none;
            border-radius: 8px;
            background: #007aff;
            color: #fff;
            cursor: pointer;
            white-space: nowrap;
        }}
        .input-bar button:active {{
            background: #005bb5;
        }}
        .copy-overlay {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.85);
            z-index: 100;
            flex-direction: column;
            padding: 12px;
        }}
        .copy-overlay.active {{
            display: flex;
        }}
        .copy-overlay textarea {{
            flex: 1;
            background: #1a1a1a;
            color: #e0e0e0;
            border: 1px solid #555;
            border-radius: 8px;
            padding: 12px;
            font-family: Menlo, monospace;
            font-size: 14px;
            line-height: 1.4;
            resize: none;
            -webkit-user-select: text;
            user-select: text;
            -webkit-overflow-scrolling: touch;
        }}
        .copy-hint {{
            color: #888;
            font-size: 13px;
            text-align: center;
            padding: 6px;
        }}
        .copy-overlay .close-btn {{
            margin-top: 8px;
            padding: 12px;
            font-size: 16px;
            font-weight: 600;
            border: none;
            border-radius: 8px;
            background: #555;
            color: #fff;
            cursor: pointer;
        }}
    </style>
</head>
<body>
    <div class="container">
        <iframe class="terminal-frame" src="http://{ip}:{TTYD_PORT}"></iframe>
        <div class="quick-keys">
            <button onclick="sendKey('Up')">&#9650;</button>
            <button onclick="sendKey('Down')">&#9660;</button>
            <button onclick="sendKey('Tab')">Tab</button>
            <button onclick="sendKey('Escape')">Esc</button>
            <button onclick="sendKey('C-c')">Ctrl+C</button>
            <button onclick="sendKey('Enter')">Enter</button>
            <button onclick="sendKey('C-l')">Clear</button>
            <button onclick="newSession()">New</button>
            <button onclick="resumeSession()">Resume</button>
            <button onclick="copyPane()">Copy</button>
        </div>
        <div class="input-bar">
            <input type="text" id="cmd"
                   placeholder="Dictate or type here..."
                   autocomplete="off"
                   autocorrect="on"
                   enterkeyhint="send" />
            <button onclick="sendText()">Send</button>
        </div>
    </div>
    <div class="copy-overlay" id="copyOverlay">
        <div class="copy-hint">Long-press to select, then Copy</div>
        <textarea id="copyText" readonly></textarea>
        <button class="close-btn" onclick="closeCopy()">Close</button>
    </div>
    <script>
        const input = document.getElementById('cmd');

        input.addEventListener('keydown', (e) => {{
            if (e.key === 'Enter') {{
                e.preventDefault();
                sendText();
            }}
        }});

        async function sendText(override) {{
            const text = override || input.value.trim();
            if (!text) return;

            try {{
                await fetch('/send', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ text }})
                }});
                if (!override) {{
                    input.value = '';
                    input.focus();
                }}
            }} catch (err) {{
                console.error('Send failed:', err);
            }}
        }}

        async function sendKey(key) {{
            try {{
                await fetch('/key', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ key }})
                }});
            }} catch (err) {{
                console.error('Key send failed:', err);
            }}
        }}

        async function copyPane() {{
            try {{
                const resp = await fetch('/copy');
                const data = await resp.json();
                const overlay = document.getElementById('copyOverlay');
                const textarea = document.getElementById('copyText');
                textarea.value = data.text;
                overlay.classList.add('active');
                // Scroll to bottom so most recent output is visible
                textarea.scrollTop = textarea.scrollHeight;
            }} catch (err) {{
                console.error('Copy failed:', err);
            }}
        }}

        async function newSession() {{
            // Exit current Claude session, then start a fresh one
            await sendText('/exit');
            setTimeout(() => sendText('claude'), 1500);
        }}

        async function resumeSession() {{
            // Exit current Claude session, then open resume picker
            await sendText('/exit');
            setTimeout(() => sendText('claude --resume'), 1500);
        }}

        function closeCopy() {{
            document.getElementById('copyOverlay').classList.remove('active');
            input.focus();
        }}

        // Auto-reconnect: reload iframe when tab becomes visible again
        const terminal = document.querySelector('.terminal-frame');
        document.addEventListener('visibilitychange', () => {{
            if (document.visibilityState === 'visible') {{
                terminal.src = terminal.src;
            }}
        }});

        input.focus();
    </script>
</body>
</html>"""


@app.post("/send")
async def send_text(payload: TextInput):
    """Send literal text to tmux, then press Enter."""
    subprocess.run(
        [TMUX, "send-keys", "-t", TMUX_SESSION, "-l", payload.text],
        timeout=5,
    )
    subprocess.run(
        [TMUX, "send-keys", "-t", TMUX_SESSION, "Enter"],
        timeout=5,
    )
    return {"status": "sent"}


@app.post("/key")
async def send_key(payload: KeyInput):
    """Send a special key (Escape, C-c, Enter, etc.) to tmux."""
    subprocess.run(
        [TMUX, "send-keys", "-t", TMUX_SESSION, payload.key],
        timeout=5,
    )
    return {"status": "sent"}


@app.get("/copy")
async def copy_pane():
    """Capture full tmux pane scrollback for copying."""
    result = subprocess.run(
        [TMUX, "capture-pane", "-t", TMUX_SESSION, "-p", "-S", "-"],
        capture_output=True, text=True, timeout=5,
    )
    return {"text": result.stdout}


if __name__ == "__main__":
    ip = get_tailscale_ip()
    print(f"Voice wrapper: http://{ip}:{WRAPPER_PORT}")
    print(f"Terminal (ttyd): http://{ip}:{TTYD_PORT}")
    uvicorn.run(app, host=ip, port=WRAPPER_PORT)
