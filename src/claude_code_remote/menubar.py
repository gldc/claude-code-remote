"""macOS menubar status indicator for Claude Code Remote."""

import argparse

import httpx
import rumps


# Title states — rumps uses the title string as the menubar label
TITLE_OK = "● CCR"
TITLE_ATTENTION = "◉ CCR"
TITLE_DOWN = "○ CCR"

POLL_INTERVAL = 5  # seconds

# Statuses that mean "needs attention"
ATTENTION_STATUSES = {"awaiting_approval"}

# rumps keys menu items by their title at insertion time; changing .title later
# does NOT update the dict key.  We store the initial key as a constant so
# insert_after / del always use the correct lookup key.
SERVER_ITEM_KEY = "Server: Checking..."


class CCRMenuBarApp(rumps.App):
    def __init__(self, host: str, port: int):
        super().__init__(TITLE_DOWN, quit_button=None)
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.client = httpx.Client(timeout=3)

        self.server_item = rumps.MenuItem(SERVER_ITEM_KEY)
        self.server_item.set_callback(None)
        self.no_sessions_item = rumps.MenuItem("No sessions")
        self.no_sessions_item.set_callback(None)

        self.menu = [
            self.server_item,
            None,  # separator
            self.no_sessions_item,
            None,  # separator
            rumps.MenuItem("Quit Menubar", callback=self._quit),
        ]

    @rumps.timer(POLL_INTERVAL)
    def poll(self, _):
        """Poll the server for session data."""
        try:
            resp = self.client.get(f"{self.base_url}/api/sessions")
            resp.raise_for_status()
            sessions = resp.json()
        except Exception:
            self.title = TITLE_DOWN
            self.server_item.title = "Server: Not responding"
            self._clear_sessions()
            return

        self.server_item.title = f"Server: Running (port {self.port})"

        # Filter out archived sessions
        active_sessions = [s for s in sessions if not s.get("archived", False)]

        needs_attention = any(
            s.get("status") in ATTENTION_STATUSES for s in active_sessions
        )
        self.title = TITLE_ATTENTION if needs_attention else TITLE_OK

        self._update_session_menu(active_sessions)

    def _update_session_menu(self, sessions: list[dict]):
        """Rebuild session list in the menu."""
        self._clear_sessions()

        if not sessions:
            self.menu.insert_after(
                SERVER_ITEM_KEY,
                self.no_sessions_item,
            )
            return

        # Insert sessions after the first separator, in order
        prev_key = SERVER_ITEM_KEY
        for s in sessions:
            name = s.get("name", s.get("id", "unknown"))
            status = s.get("status", "unknown")
            suffix = " ⚠️" if status in ATTENTION_STATUSES else ""
            label = f"{name}: {status}{suffix}"
            item = rumps.MenuItem(label)
            item.set_callback(None)
            # Tag items so we can find them later for cleanup
            item._ccr_session = True
            self.menu.insert_after(prev_key, item)
            prev_key = label

    def _clear_sessions(self):
        """Remove all session menu items."""
        to_remove = [
            key
            for key, item in self.menu.items()
            if getattr(item, "_ccr_session", False)
        ]
        for key in to_remove:
            del self.menu[key]
        # Also remove the "No sessions" placeholder if present
        no_sessions_key = "No sessions"
        if no_sessions_key in self.menu:
            del self.menu[no_sessions_key]

    def _quit(self, _):
        self.client.close()
        rumps.quit_application()


def main():
    parser = argparse.ArgumentParser(description="CCR Menubar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    CCRMenuBarApp(host=args.host, port=args.port).run()


if __name__ == "__main__":
    main()
