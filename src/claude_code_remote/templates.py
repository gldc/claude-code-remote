"""Template persistence -- CRUD for session templates."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from claude_code_remote.models import Template, TemplateCreate

logger = logging.getLogger(__name__)


class TemplateStore:
    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.templates: dict[str, Template] = {}
        self._load()

    def _load(self) -> None:
        for path in self.template_dir.glob("*.json"):
            try:
                t = Template.model_validate_json(path.read_text())
                self.templates[t.id] = t
            except Exception as e:
                logger.error(f"Failed to load template {path}: {e}")

    def _save(self, template: Template) -> None:
        path = self.template_dir / f"{template.id}.json"
        path.write_text(template.model_dump_json(indent=2))

    def create(self, req: TemplateCreate) -> Template:
        t = Template(**req.model_dump())
        self.templates[t.id] = t
        self._save(t)
        return t

    def list(self) -> list[Template]:
        return list(self.templates.values())

    def get(self, template_id: str) -> Template | None:
        return self.templates.get(template_id)

    def update(self, template_id: str, req: TemplateCreate) -> Template:
        existing = self.templates.get(template_id)
        if not existing:
            raise ValueError(f"Template {template_id} not found")
        updated = Template(
            id=existing.id, created_at=existing.created_at, **req.model_dump()
        )
        self.templates[template_id] = updated
        self._save(updated)
        return updated

    def delete(self, template_id: str) -> None:
        self.templates.pop(template_id, None)
        path = self.template_dir / f"{template_id}.json"
        path.unlink(missing_ok=True)
