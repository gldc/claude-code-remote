"""Workflow orchestration -- multi-step session pipelines."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from .models import (
    Workflow,
    WorkflowStep,
    WorkflowStatus,
    WorkflowStepStatus,
)

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Persists workflows to JSON and executes steps via SessionManager."""

    def __init__(self, workflow_dir: Path):
        self.workflow_dir = workflow_dir
        self.workflow_dir.mkdir(parents=True, exist_ok=True)
        self.workflows: dict[str, Workflow] = {}
        self._load()

    def _load(self) -> None:
        for path in self.workflow_dir.glob("*.json"):
            try:
                wf = Workflow.model_validate_json(path.read_text())
                self.workflows[wf.id] = wf
            except Exception as e:
                logger.error("Failed to load workflow %s: %s", path, e)

    def _save(self, workflow: Workflow) -> None:
        path = self.workflow_dir / f"{workflow.id}.json"
        path.write_text(workflow.model_dump_json(indent=2))

    def create(self, name: str, steps: list[WorkflowStep]) -> Workflow:
        wf = Workflow(name=name, steps=steps)
        self.workflows[wf.id] = wf
        self._save(wf)
        return wf

    def add_step(self, workflow_id: str, step: WorkflowStep) -> Workflow | None:
        wf = self.workflows.get(workflow_id)
        if not wf:
            return None
        wf.steps.append(step)
        self._save(wf)
        return wf

    def get(self, workflow_id: str) -> Workflow | None:
        return self.workflows.get(workflow_id)

    def list(self) -> list[Workflow]:
        return list(self.workflows.values())

    def delete(self, workflow_id: str) -> bool:
        if workflow_id in self.workflows:
            del self.workflows[workflow_id]
            path = self.workflow_dir / f"{workflow_id}.json"
            path.unlink(missing_ok=True)
            return True
        return False

    async def run(self, workflow_id: str, session_mgr) -> Workflow:
        """Execute a workflow by topological order of steps."""
        wf = self.workflows.get(workflow_id)
        if not wf:
            raise ValueError(f"Workflow {workflow_id} not found")

        wf.status = WorkflowStatus.RUNNING
        self._save(wf)

        try:
            # Build dependency graph
            step_map = {step.id: step for step in wf.steps}
            completed: set[str] = set()

            while len(completed) < len(wf.steps):
                # Find steps ready to run (all deps completed)
                ready = [
                    step
                    for step in wf.steps
                    if step.id not in completed
                    and step.status == WorkflowStepStatus.PENDING
                    and all(dep in completed for dep in step.depends_on)
                ]

                if not ready:
                    # Check for stuck steps (deps failed)
                    stuck = [
                        s
                        for s in wf.steps
                        if s.id not in completed
                        and s.status == WorkflowStepStatus.PENDING
                    ]
                    if stuck:
                        for s in stuck:
                            s.status = WorkflowStepStatus.ERROR
                            completed.add(s.id)
                    break

                # Run ready steps in parallel
                tasks = []
                for step in ready:
                    step.status = WorkflowStepStatus.RUNNING
                    self._save(wf)
                    tasks.append(self._run_step(step, session_mgr))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for step, result in zip(ready, results):
                    if isinstance(result, Exception):
                        step.status = WorkflowStepStatus.ERROR
                        logger.error("Workflow step %s failed: %s", step.id, result)
                    else:
                        step.status = WorkflowStepStatus.COMPLETED
                        step.session_id = result
                    completed.add(step.id)
                    self._save(wf)

            # Determine final status
            if all(s.status == WorkflowStepStatus.COMPLETED for s in wf.steps):
                wf.status = WorkflowStatus.COMPLETED
            else:
                wf.status = WorkflowStatus.ERROR
        except Exception as e:
            wf.status = WorkflowStatus.ERROR
            logger.error("Workflow %s failed: %s", workflow_id, e)

        self._save(wf)
        return wf

    async def _run_step(self, step: WorkflowStep, session_mgr) -> str:
        """Create and run a session for a workflow step."""
        session = session_mgr.create_session(step.session_config)
        if step.session_config.initial_prompt:
            await session_mgr.send_prompt(
                session.id, step.session_config.initial_prompt
            )
        return session.id
