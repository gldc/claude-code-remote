"""Approval rules engine -- auto-approve/deny tools based on saved rules."""

from __future__ import annotations

import fnmatch
import json
import logging
import os
from pathlib import Path

from .models import ApprovalRule

logger = logging.getLogger(__name__)


class ApprovalRulesStore:
    def __init__(self, rules_file: Path):
        self.rules_file = rules_file
        self.rules: dict[str, ApprovalRule] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.rules_file.exists():
                data = json.loads(self.rules_file.read_text())
                for item in data:
                    rule = ApprovalRule.model_validate(item)
                    self.rules[rule.id] = rule
        except Exception as e:
            logger.warning("Failed to load approval rules: %s", e)

    def _save(self) -> None:
        self.rules_file.parent.mkdir(parents=True, exist_ok=True)
        data = [r.model_dump(mode="json") for r in self.rules.values()]
        self.rules_file.write_text(json.dumps(data, indent=2))
        # Approval rules control tool execution — restrict to owner only
        os.chmod(self.rules_file, 0o600)

    def create(
        self,
        tool_pattern: str,
        action: str = "approve",
        project_dir: str | None = None,
    ) -> ApprovalRule:
        rule = ApprovalRule(
            tool_pattern=tool_pattern, action=action, project_dir=project_dir
        )
        self.rules[rule.id] = rule
        self._save()
        return rule

    def delete(self, rule_id: str) -> bool:
        if rule_id in self.rules:
            del self.rules[rule_id]
            self._save()
            return True
        return False

    def list(self) -> list[ApprovalRule]:
        return list(self.rules.values())

    def check(
        self, tool_name: str, project_dir: str | None = None
    ) -> ApprovalRule | None:
        """Find first matching rule for a tool invocation."""
        for rule in self.rules.values():
            if not fnmatch.fnmatch(tool_name, rule.tool_pattern):
                continue
            if rule.project_dir and project_dir and rule.project_dir != project_dir:
                continue
            return rule
        return None
