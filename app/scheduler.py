"""APScheduler integration for cron-triggered agent runs."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.models.execution import TriggerType
from app.services.repos import AgentAlreadyRunningError
from app.services.stuck_runs import sweep_stuck_runs

if TYPE_CHECKING:
    from app.services.agent_runner import AgentRunner
    from app.services.activity_registry import ActivityRegistry
    from app.services.repos import AgentRepository, ExecutionRepository
    from app.services.task_registry import TaskRegistry

logger = logging.getLogger(__name__)
STUCK_RUN_SWEEPER_JOB_ID = "stuck-run-sweeper"


def validate_cron(cron_schedule: str) -> CronTrigger:
    """Parse a 5-field crontab string; raises ValueError if invalid."""
    return CronTrigger.from_crontab(cron_schedule)


class AgentScheduler:
    """Manages cron jobs that trigger agent runs."""

    def __init__(
        self,
        agent_repo: AgentRepository,
        execution_repo: ExecutionRepository,
        runner: AgentRunner,
        task_registry: TaskRegistry,
        *,
        activity: ActivityRegistry | None = None,
        stuck_threshold_seconds: int = 1800,
        stuck_sweep_interval_seconds: int = 60,
        on_stuck_failed: Callable[[str], Awaitable[object]] | None = None,
    ) -> None:
        self._agents = agent_repo
        self._executions = execution_repo
        self._runner = runner
        self._tasks = task_registry
        self._activity = activity
        self._stuck_threshold_seconds = stuck_threshold_seconds
        self._stuck_sweep_interval_seconds = stuck_sweep_interval_seconds
        self._on_stuck_failed = on_stuck_failed
        self._scheduler = AsyncIOScheduler()

    @property
    def scheduler(self) -> AsyncIOScheduler:
        return self._scheduler

    def start(self) -> None:
        if not self._scheduler.running:
            self._schedule_stuck_run_sweeper()
            self._scheduler.start()
            logger.info("APScheduler started")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("APScheduler shut down")

    async def reload_all(self) -> None:
        """Clear and re-register jobs for all agents with cron schedules."""
        self._scheduler.remove_all_jobs()
        self._schedule_stuck_run_sweeper()
        agents = await self._agents.list_with_cron()
        loaded = 0
        for agent in agents:
            try:
                self.schedule_agent(agent.id, agent.cron_schedule)
                loaded += 1
            except ValueError as exc:
                logger.error(
                    "Skipping invalid cron for agent %s (%s): %s",
                    agent.id,
                    agent.cron_schedule,
                    exc,
                )
        logger.info("Loaded %d cron job(s)", loaded)

    def _schedule_stuck_run_sweeper(self) -> None:
        if self._stuck_sweep_interval_seconds <= 0:
            return
        self._scheduler.add_job(
            self._sweep_stuck_runs,
            trigger=IntervalTrigger(
                seconds=self._stuck_sweep_interval_seconds,
            ),
            id=STUCK_RUN_SWEEPER_JOB_ID,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    async def _sweep_stuck_runs(self) -> None:
        failed = await sweep_stuck_runs(
            executions=self._executions,
            threshold_seconds=self._stuck_threshold_seconds,
            activity=self._activity,
            task_registry=self._tasks,
            on_failed=self._on_stuck_failed,
        )
        if failed:
            logger.warning("Failed %d stuck execution(s)", failed)

    def schedule_agent(self, agent_id: str, cron_schedule: Optional[str]) -> None:
        """
        Schedule (or unschedule) an agent.

        Validates cron BEFORE removing any existing job so a bad update
        cannot wipe a previously valid schedule.
        Raises ValueError on invalid cron expressions.
        """
        job_id = f"agent:{agent_id}"

        if not cron_schedule:
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
                logger.info("Unscheduled agent %s", agent_id)
            return

        trigger = validate_cron(cron_schedule)

        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

        self._scheduler.add_job(
            self._cron_fire,
            trigger=trigger,
            id=job_id,
            args=[agent_id],
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info("Scheduled agent %s with cron '%s'", agent_id, cron_schedule)

    def unschedule_agent(self, agent_id: str) -> None:
        job_id = f"agent:{agent_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info("Unscheduled agent %s", agent_id)

    async def _cron_fire(self, agent_id: str) -> None:
        agent = await self._agents.get(agent_id)
        if agent is None:
            logger.warning("Cron fire: agent %s not found", agent_id)
            return
        if agent.paused:
            logger.info("Skipping cron run for agent %s: paused", agent_id)
            return

        try:
            log = await self._runner.start_run(
                agent_id,
                trigger_type=TriggerType.cron,
            )
        except AgentAlreadyRunningError:
            logger.info(
                "Skipping cron run for agent %s: already has status=running",
                agent_id,
            )
            return

        if log is None:
            logger.warning("Cron fire: agent %s not found", agent_id)
            return

        self._tasks.create_task(
            self._runner.execute(log.id),
            name=f"cron-run-{log.id}",
        )
        logger.info("Cron started execution %s for agent %s", log.id, agent_id)
