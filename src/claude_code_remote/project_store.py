"""Project persistence for server-created projects."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from claude_code_remote.models import Project

logger = logging.getLogger(__name__)


class ProjectStore:
    """Persists server-created projects (blank + cloned) to a JSON file."""

    def __init__(self, projects_file: Path):
        self.projects_file = projects_file
        self.projects: dict[str, Project] = {}
        self._load()

    def _load(self) -> None:
        if not self.projects_file.exists():
            return
        try:
            data = json.loads(self.projects_file.read_text())
            for item in data:
                p = Project.model_validate(item)
                self.projects[p.id] = p
        except Exception as e:
            logger.error("Failed to load projects: %s", e)

    def _save(self) -> None:
        self.projects_file.parent.mkdir(parents=True, exist_ok=True)
        data = [p.model_dump(mode="json") for p in self.projects.values()]
        self.projects_file.write_text(json.dumps(data, indent=2))

    def add(self, project: Project) -> None:
        self.projects[project.id] = project
        self._save()

    def update_status(
        self, project_id: str, status: str, error_message: str | None = None
    ) -> Project | None:
        p = self.projects.get(project_id)
        if not p:
            return None
        p.status = status
        p.error_message = error_message
        self._save()
        return p

    def get(self, project_id: str) -> Project | None:
        return self.projects.get(project_id)

    def list(self) -> list[Project]:
        return list(self.projects.values())

    def merge_with_scanned(self, scanned: list[Project]) -> list[Project]:
        """Merge scanned projects with stored projects. Stored wins on path conflict."""
        stored_paths = {p.path for p in self.projects.values()}
        merged = list(self.projects.values())
        for p in scanned:
            if p.path not in stored_paths:
                merged.append(p)
        return merged
