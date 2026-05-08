"""Agent 调度器：APScheduler 定时任务管理"""

import asyncio
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.automation import AutomationRunner
from agents.orchestrator import Orchestrator
from common.logger import get_logger

logger = get_logger(__name__)


class AgentScheduler:
    """定时任务管理：每日扫描、每周分析、手动触发"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], automation_runner: AutomationRunner | None = None):
        self._orchestrator = Orchestrator(session_factory)
        self._automation = automation_runner or AutomationRunner(session_factory)
        self._scheduler = AsyncIOScheduler()
        self._setup_jobs()

    def _setup_jobs(self):
        # 每日扫描：周一至周五 18:00
        self._scheduler.add_job(
            self._run_daily,
            "cron",
            day_of_week="mon-fri",
            hour=18,
            minute=0,
            id="daily_scan",
            name="交易日收盘自动流程",
        )
        # 每周分析：周六 10:00
        self._scheduler.add_job(
            self._run_weekly,
            "cron",
            day_of_week="sat",
            hour=10,
            minute=0,
            id="weekly_analysis",
            name="每周产业链分析",
        )
        # 产业链发现：周日 8:00
        self._scheduler.add_job(
            self._run_chain_discovery,
            "cron",
            day_of_week="sun",
            hour=8,
            minute=0,
            id="chain_discovery",
            name="周末产业链发现与周报",
        )

    def start(self):
        self._scheduler.start()
        jobs = self._scheduler.get_jobs()
        logger.info(f"AgentScheduler started with {len(jobs)} jobs")
        for job in jobs:
            logger.info(f"  Job: {job.id} - {job.name} - next: {job.next_run_time}")

    def stop(self):
        self._scheduler.shutdown(wait=False)
        logger.info("AgentScheduler stopped")

    def get_jobs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": j.id,
                "name": j.name,
                "next_run": str(j.next_run_time),
                "trigger": str(j.trigger),
            }
            for j in self._scheduler.get_jobs()
        ]

    async def trigger_manual(self, workflow_type: str, **kwargs) -> dict[str, Any]:
        """手动触发工作流"""
        if workflow_type in {"daily", "daily_after_close"}:
            return await self._automation.run("daily_after_close", trigger="manual", params=kwargs)
        elif workflow_type == "weekly":
            return await self._automation.run("weekly_discovery", trigger="manual", params=kwargs)
        elif workflow_type == "deep_research":
            chain_id = kwargs.get("chain_id", "")
            if not chain_id:
                return {"error": "chain_id required for deep_research"}
            return await self._orchestrator.run_deep_research(chain_id)
        elif workflow_type == "risk_check":
            return await self._automation.run("risk_check", trigger="manual", params=kwargs)
        elif workflow_type == "chain_discovery":
            return await self._automation.run("chain_discovery", trigger="manual", params=kwargs)
        elif workflow_type in {"daily_scan", "weekly_analysis", "weekly_discovery"}:
            return await self._automation.run(workflow_type, trigger="manual", params=kwargs)
        else:
            return {"error": f"Unknown workflow_type: {workflow_type}"}

    async def _run_daily(self):
        logger.info("Cron trigger: daily_scan")
        try:
            await self._automation.run("daily_after_close", trigger="cron")
        except Exception as e:
            logger.error(f"Daily scan cron failed: {e}")

    async def _run_weekly(self):
        logger.info("Cron trigger: weekly_analysis")
        try:
            await self._automation.run("weekly_analysis", trigger="cron")
        except Exception as e:
            logger.error(f"Weekly analysis cron failed: {e}")

    async def _run_chain_discovery(self):
        logger.info("Cron trigger: chain_discovery")
        try:
            await self._automation.run("weekly_discovery", trigger="cron")
        except Exception as e:
            logger.error(f"Chain discovery cron failed: {e}")
