"""Claude Code Remote — macOS menu bar app."""

import os
import shutil
import subprocess
import rumps

from claude_code_remote import config, services, tailscale

MENUBAR_PLIST_LABEL = "com.user.claude-code-remote-menubar"
MENUBAR_PLIST_PATH = os.path.expanduser(
    f"~/Library/LaunchAgents/{MENUBAR_PLIST_LABEL}.plist"
)

MENUBAR_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{ccr_path}</string>
        <string>menubar</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
"""

# Icon states
ICON_GREEN = "● CC"
ICON_GRAY = "○ CC"
ICON_RED = "◉ CC"


class RemoteCLIApp(rumps.App):
    def __init__(self):
        super().__init__(ICON_GRAY, quit_button=None)
        self.tailscale_ip = tailscale.get_ip()
        self.tailscale_dns = tailscale.get_dns_name()

        self.status_item = rumps.MenuItem("Status: Stopped")
        self.status_item.set_callback(None)

        self.ip_item = rumps.MenuItem(
            f"Tailscale IP: {self.tailscale_ip or 'Not connected'}"
        )
        self.ip_item.set_callback(None)

        self.dns_item = rumps.MenuItem(
            f"MagicDNS: {self.tailscale_dns or 'Not available'}"
        )
        self.dns_item.set_callback(None)

        self.open_voice_item = rumps.MenuItem("Open Voice UI")
        self.open_terminal_item = rumps.MenuItem("Open Terminal")
        self.toggle_item = rumps.MenuItem("Start Services")

        log_menu = rumps.MenuItem("View Logs")
        log_menu.add(rumps.MenuItem("ttyd.log"))
        log_menu.add(rumps.MenuItem("voice-wrapper.log"))

        self.autostart_item = rumps.MenuItem("Auto-start on Login")

        quit_item = rumps.MenuItem("Quit")

        self.menu = [
            self.status_item,
            None,
            self.ip_item,
            self.dns_item,
            self.open_voice_item,
            self.open_terminal_item,
            None,
            self.toggle_item,
            None,
            log_menu,
            self.autostart_item,
            None,
            quit_item,
        ]

        self.cfg = config.load_config()
        if self.cfg["auto_start_services"]:
            self._start_services()

        self.autostart_item.state = self._is_login_plist_installed()

    @rumps.timer(5)
    def health_check(self, _):
        """Poll PID files and process liveness every 5 seconds."""
        self.tailscale_ip = tailscale.get_ip()
        self.tailscale_dns = tailscale.get_dns_name()
        self.ip_item.title = (
            f"Tailscale IP: {self.tailscale_ip or 'Not connected'}"
        )
        self.dns_item.title = (
            f"MagicDNS: {self.tailscale_dns or 'Not available'}"
        )

        svc_status = services.get_status()
        alive = sum(svc_status.values())
        if alive == 3 and self.tailscale_ip:
            self.title = ICON_GREEN
            self.status_item.title = "Status: Running (all services healthy)"
            self.toggle_item.title = "Stop Services"
        elif alive == 0:
            self.title = ICON_GRAY
            self.status_item.title = "Status: Stopped"
            self.toggle_item.title = "Start Services"
        else:
            self.title = ICON_RED
            down = [n for n, up in svc_status.items() if not up]
            self.status_item.title = f"Status: Degraded ({', '.join(down)} down)"
            self.toggle_item.title = "Stop Services"

        # Update URL menu items availability
        has_ip = self.tailscale_ip is not None
        self.open_voice_item.set_callback(
            self.open_voice_ui if has_ip else None
        )
        self.open_terminal_item.set_callback(
            self.open_terminal if has_ip else None
        )

    @rumps.clicked("Open Voice UI")
    def open_voice_ui(self, _):
        host = self.tailscale_dns or self.tailscale_ip
        if host:
            subprocess.run(["open", f"http://{host}:8080"])

    @rumps.clicked("Open Terminal")
    def open_terminal(self, _):
        host = self.tailscale_dns or self.tailscale_ip
        if host:
            subprocess.run(["open", f"http://{host}:7681"])

    @rumps.clicked("Start Services")
    def toggle_services(self, _):
        if self.toggle_item.title == "Start Services":
            self._start_services()
        else:
            self._stop_services()

    def _start_services(self):
        subprocess.Popen(
            ["ccr", "start"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _stop_services(self):
        subprocess.run(
            ["ccr", "stop"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @rumps.clicked("ttyd.log")
    def view_ttyd_log(self, _):
        log_path = config.LOG_DIR / "ttyd.log"
        if log_path.exists():
            subprocess.run(["open", "-a", "Console", str(log_path)])

    @rumps.clicked("voice-wrapper.log")
    def view_voice_log(self, _):
        log_path = config.LOG_DIR / "voice-wrapper.log"
        if log_path.exists():
            subprocess.run(["open", "-a", "Console", str(log_path)])

    @rumps.clicked("Auto-start on Login")
    def toggle_autostart(self, sender):
        if sender.state:
            self._uninstall_login_plist()
            sender.state = False
        else:
            self._install_login_plist()
            sender.state = True

    def _is_login_plist_installed(self):
        return os.path.exists(MENUBAR_PLIST_PATH)

    def _install_login_plist(self):
        ccr_path = shutil.which("ccr") or "ccr"
        plist_content = MENUBAR_PLIST_TEMPLATE.format(
            label=MENUBAR_PLIST_LABEL,
            ccr_path=ccr_path,
        )
        os.makedirs(os.path.dirname(MENUBAR_PLIST_PATH), exist_ok=True)
        with open(MENUBAR_PLIST_PATH, "w") as f:
            f.write(plist_content)

    def _uninstall_login_plist(self):
        if os.path.exists(MENUBAR_PLIST_PATH):
            os.remove(MENUBAR_PLIST_PATH)

    @rumps.clicked("Quit")
    def quit_app(self, _):
        if self.toggle_item.title == "Stop Services":
            response = rumps.alert(
                title="Quit Claude Code Remote",
                message="Services are still running. Stop them before quitting?",
                ok="Stop & Quit",
                cancel="Quit (keep running)",
            )
            if response == 1:  # "Stop & Quit"
                self._stop_services()
        rumps.quit_application()


if __name__ == "__main__":
    RemoteCLIApp().run()
