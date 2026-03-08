#!/usr/bin/env python3
"""PreToolUse hook that routes permission requests through the CCR API.

Only activates when CCR_SESSION_ID and CCR_API_URL env vars are set
(i.e., when spawned by the CCR server). For normal Claude Code sessions,
this hook does nothing and allows all tools.
"""

import fnmatch
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

CCR_SESSION_ID = os.environ.get("CCR_SESSION_ID", "")
CCR_API_URL = os.environ.get("CCR_API_URL", "")
CCR_SKIP_APPROVAL = os.environ.get("CCR_SKIP_APPROVAL", "")
CCR_APPROVAL_FAIL_MODE = os.environ.get("CCR_APPROVAL_FAIL_MODE", "deny")
APPROVAL_TIMEOUT = int(os.environ.get("CCR_APPROVAL_TIMEOUT", "300"))

# Tools that are safe to auto-approve (read-only, no side effects)
SAFE_TOOLS = {
    "Read",
    "Glob",
    "Grep",
    "WebSearch",
    "WebFetch",
    "Agent",
    "Task",
    "TaskOutput",
}

# Approval rules file
RULES_FILE = (
    Path.home() / ".local" / "state" / "claude-code-remote" / "approval_rules.json"
)


def allow():
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "permissionDecision": "allow",
                },
            }
        )
    )
    sys.stdout.flush()


def deny(reason="Denied"):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "permissionDecision": "deny",
                },
                "systemMessage": reason,
            }
        )
    )
    sys.stdout.flush()


def check_approval_rules(tool_name: str) -> str | None:
    """Check approval rules file. Returns 'approve', 'deny', or None."""
    try:
        if not RULES_FILE.exists():
            return None
        rules = json.loads(RULES_FILE.read_text())
        project_dir = os.environ.get("CCR_PROJECT_DIR", "")
        for rule in rules:
            pattern = rule.get("tool_pattern", "")
            if not fnmatch.fnmatch(tool_name, pattern):
                continue
            rule_proj = rule.get("project_dir")
            if rule_proj and project_dir and rule_proj != project_dir:
                continue
            return rule.get("action", "approve")
    except Exception:
        pass
    return None


def main():
    # Not a CCR session — allow everything (transparent passthrough)
    if not CCR_SESSION_ID or not CCR_API_URL:
        allow()
        return

    # Skip approval mode — auto-allow all tools
    if CCR_SKIP_APPROVAL:
        allow()
        return

    stdin_data = sys.stdin.read()
    try:
        hook_input = json.loads(stdin_data)
    except json.JSONDecodeError:
        allow()
        return

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # Check approval rules before anything else
    rule_action = check_approval_rules(tool_name)
    if rule_action == "approve":
        allow()
        return
    elif rule_action == "deny":
        deny(f"Denied by approval rule: {tool_name}")
        return

    # Safe tools auto-approve without routing to mobile app
    if tool_name in SAFE_TOOLS:
        allow()
        return

    # Dangerous tools (Write, Edit, Bash, etc.) route to app for approval
    payload = json.dumps(
        {
            "session_id": CCR_SESSION_ID,
            "tool_name": tool_name,
            "tool_input": tool_input,
        }
    ).encode()

    url = f"{CCR_API_URL}/api/internal/approval-request"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        # Long timeout — we block until the user decides in the app
        with urllib.request.urlopen(req, timeout=APPROVAL_TIMEOUT + 10) as resp:
            result = json.loads(resp.read().decode())
            if result.get("approved"):
                allow()
            else:
                deny(result.get("reason", "Denied by user"))
    except (urllib.error.URLError, Exception):
        # Server unreachable — default to deny for safety
        if CCR_APPROVAL_FAIL_MODE == "allow":
            allow()
        else:
            deny("CCR server unreachable — tool denied for safety")


if __name__ == "__main__":
    main()
    sys.exit(0)
