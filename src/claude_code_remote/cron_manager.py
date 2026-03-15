"""Cron job management -- CRUD, scheduling, execution, and run history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from croniter import croniter

from claude_code_remote.models import (
    CronExecutionMode,
    CronJob,
    CronJobCreate,
    CronJobRun,
    CronJobUpdate,
    CronRunStatus,
    SessionStatus,
)

if TYPE_CHECKING:
    from claude_code_remote.session_manager import SessionManager

logger = logging.getLogger(__name__)


class CronManager:
    """Persists cron jobs to JSON and manages scheduled execution."""

    def __init__(
        self,
        cron_dir: Path,
        history_file: Path,
        session_mgr: SessionManager | None,
    ):
        self.cron_dir = cron_dir
        self.cron_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = history_file
        self.session_mgr = session_mgr
        self.jobs: dict[str, CronJob] = {}
        self._scheduler = None
        self._running_jobs: set[str] = set()
        self._load()

    def _load(self) -> None:
        for path in self.cron_dir.glob("*.json"):
            try:
                job = CronJob.model_validate_json(path.read_text())
                self.jobs[job.id] = job
            except Exception as e:
                logger.error(f"Failed to load cron job {path}: {e}")

    def _save(self, job: CronJob) -> None:
        path = self.cron_dir / f"{job.id}.json"
        path.write_text(job.model_dump_json(indent=2))

    def _validate_schedule(self, schedule: str) -> None:
        try:
            croniter(schedule)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid cron expression: {schedule!r} — {e}")

    def _compute_next_run(self, schedule: str) -> datetime:
        cron = croniter(schedule, datetime.now(timezone.utc))
        return cron.get_next(datetime).replace(tzinfo=timezone.utc)

    def create(self, req: CronJobCreate) -> CronJob:
        self._validate_schedule(req.schedule)
        now = datetime.now(timezone.utc)
        job = CronJob(
            **req.model_dump(),
            created_at=now,
            updated_at=now,
            next_run_at=self._compute_next_run(req.schedule) if req.enabled else None,
        )
        self.jobs[job.id] = job
        self._save(job)
        if job.enabled:
            self._register_scheduler_job(job)
        return job

    def list(self) -> list[CronJob]:
        return list(self.jobs.values())

    def get(self, job_id: str) -> CronJob | None:
        return self.jobs.get(job_id)

    def update(self, job_id: str, req: CronJobUpdate) -> CronJob:
        existing = self.jobs.get(job_id)
        if not existing:
            raise ValueError(f"Cron job {job_id} not found")

        update_data = req.model_dump(exclude_unset=True)

        if "schedule" in update_data:
            self._validate_schedule(update_data["schedule"])

        for field, value in update_data.items():
            setattr(existing, field, value)

        existing.updated_at = datetime.now(timezone.utc)

        # Recompute next_run if schedule or enabled changed
        if existing.enabled:
            existing.next_run_at = self._compute_next_run(existing.schedule)
        else:
            existing.next_run_at = None

        self.jobs[job_id] = existing
        self._save(existing)
        if existing.enabled:
            self._register_scheduler_job(existing)
        else:
            self._unregister_scheduler_job(job_id)
        return existing

    def delete(self, job_id: str) -> None:
        self._unregister_scheduler_job(job_id)
        self.jobs.pop(job_id, None)
        path = self.cron_dir / f"{job_id}.json"
        path.unlink(missing_ok=True)

    def toggle(self, job_id: str) -> CronJob:
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Cron job {job_id} not found")
        return self.update(job_id, CronJobUpdate(enabled=not job.enabled))

    # --- Run History ---

    def get_history(
        self, job_id: str, limit: int = 50, offset: int = 0
    ) -> list[CronJobRun]:
        runs: list[CronJobRun] = []
        if not self.history_file.exists():
            return runs
        for line in self.history_file.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                run = CronJobRun.model_validate_json(line)
                if run.cron_job_id == job_id:
                    runs.append(run)
            except Exception:
                continue
        # Sort by started_at descending (newest first)
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs[offset : offset + limit]

    def _record_run(self, run: CronJobRun) -> None:
        with open(self.history_file, "a") as f:
            f.write(run.model_dump_json() + "\n")

    # --- Scheduler ---

    def _register_scheduler_job(self, job: CronJob) -> None:
        """Register a single cron job with APScheduler."""
        if not self._scheduler:
            return
        from apscheduler.triggers.cron import CronTrigger

        try:
            trigger = CronTrigger.from_crontab(job.schedule)
            self._scheduler.add_job(
                self.execute_job,
                trigger=trigger,
                args=[job.id],
                id=job.id,
                replace_existing=True,
                name=job.name,
            )
        except Exception as e:
            logger.error(f"Failed to register cron job {job.id}: {e}")

    def _unregister_scheduler_job(self, job_id: str) -> None:
        """Remove a job from APScheduler."""
        if self._scheduler:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass  # Job may not be registered

    async def start_scheduler(self) -> None:
        """Start the APScheduler and register all enabled jobs."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        self._scheduler = AsyncIOScheduler()
        for job in self.jobs.values():
            if job.enabled:
                self._register_scheduler_job(job)
        self._scheduler.start()
        logger.info(
            f"Cron scheduler started with "
            f"{len([j for j in self.jobs.values() if j.enabled])} active jobs"
        )

    async def shutdown_scheduler(self) -> None:
        """Stop the APScheduler."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Cron scheduler shut down")

    # --- Execution ---

    def _substitute_template(self, template: str, job: CronJob) -> str:
        """Replace template variables with current values."""
        import subprocess

        now = datetime.now(timezone.utc)
        replacements = {
            "{{date}}": now.strftime("%Y-%m-%d"),
            "{{time}}": now.strftime("%H:%M:%S"),
            "{{datetime}}": now.isoformat(),
            "{{project}}": Path(job.project_dir).name,
            "{{run_number}}": str(len(self.get_history(job.id)) + 1),
        }
        # Try to get git branch
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=job.session_config.project_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            replacements["{{branch}}"] = (
                result.stdout.strip() if result.returncode == 0 else "unknown"
            )
        except Exception:
            replacements["{{branch}}"] = "unknown"

        prompt = template
        for key, value in replacements.items():
            prompt = prompt.replace(key, value)
        return prompt

    async def execute_job(self, job_id: str) -> None:
        """Execute a cron job -- spawn or resume session."""
        job = self.get(job_id)
        if not job:
            logger.error(f"Cron job {job_id} not found")
            return

        # Concurrent run prevention
        if job_id in self._running_jobs:
            logger.warning(f"Cron job {job_id} is already running, skipping")
            return
        self._running_jobs.add(job_id)

        run = CronJobRun(cron_job_id=job_id)

        try:
            # Determine prompt
            if job.prompt_template:
                prompt = self._substitute_template(job.prompt_template, job)
            else:
                prompt = job.session_config.initial_prompt

            if job.execution_mode == CronExecutionMode.SPAWN:
                # Create a new session
                session = self.session_mgr.create_session(job.session_config)
                session.cron_job_id = job.id
                self.session_mgr.persist_session(session.id)
                run.session_id = session.id
                await self.session_mgr.send_prompt(session.id, prompt)
            else:
                # Persistent mode -- reuse or create session
                if job.persistent_session_id:
                    existing = self.session_mgr.sessions.get(job.persistent_session_id)
                    if existing and existing.status != SessionStatus.ERROR:
                        run.session_id = job.persistent_session_id
                        await self.session_mgr.send_prompt(
                            job.persistent_session_id, prompt
                        )
                    else:
                        # Session gone -- create new
                        session = self.session_mgr.create_session(job.session_config)
                        session.cron_job_id = job.id
                        self.session_mgr.persist_session(session.id)
                        job.persistent_session_id = session.id
                        self._save(job)
                        run.session_id = session.id
                        await self.session_mgr.send_prompt(session.id, prompt)
                else:
                    # First run -- create session
                    session = self.session_mgr.create_session(job.session_config)
                    session.cron_job_id = job.id
                    self.session_mgr.persist_session(session.id)
                    job.persistent_session_id = session.id
                    self._save(job)
                    run.session_id = session.id
                    await self.session_mgr.send_prompt(session.id, prompt)

            run.status = CronRunStatus.SUCCESS
            run.completed_at = datetime.now(timezone.utc)
            # Retrieve cost from the session
            if run.session_id:
                session_obj = self.session_mgr.sessions.get(run.session_id)
                if session_obj:
                    run.cost_usd = session_obj.total_cost_usd

        except Exception as e:
            logger.error(f"Cron job {job_id} execution failed: {e}")
            run.status = CronRunStatus.ERROR
            run.error_message = str(e)
            run.completed_at = datetime.now(timezone.utc)

        finally:
            self._running_jobs.discard(job_id)
            self._record_run(run)
            # Update job state
            job.last_run_at = run.started_at
            job.last_run_status = run.status
            job.next_run_at = self._compute_next_run(job.schedule)
            job.updated_at = datetime.now(timezone.utc)
            self.jobs[job_id] = job
            self._save(job)
