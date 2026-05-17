"""Agent 调度器：APScheduler 定时任务管理"""

import asyncio
from datetime import date
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
        self._session_factory = session_factory
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
        # 尾盘选股：周一至周五 14:50（盘中实时快照）
        self._scheduler.add_job(
            self._run_eod_screener,
            "cron",
            day_of_week="mon-fri",
            hour=14,
            minute=50,
            id="eod_screener",
            name="尾盘盘中自动选股",
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
        # ETF 板块轮动分析：周一至周五 18:30
        self._scheduler.add_job(
            self._run_etf_analysis,
            "cron",
            day_of_week="mon-fri",
            hour=18,
            minute=30,
            id="etf_analysis",
            name="ETF板块轮动定时分析",
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
        elif workflow_type == "eod_screener":
            return await self._run_eod_screener_manual(**kwargs)
        elif workflow_type == "etf_analysis":
            return await self._run_etf_analysis_manual()
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

    async def _run_eod_screener(self):
        logger.info("Cron trigger: eod_screener")
        try:
            result = await self._collect_and_run_eod_screener(date.today())
            logger.info(
                "尾盘选股完成: status=%s, trade_date=%s, count=%s",
                result.get("status"),
                result.get("trade_date"),
                result.get("count"),
            )
        except Exception as e:
            logger.error(f"EOD screener cron failed: {e}")

    async def _run_eod_screener_manual(self, **kwargs) -> dict[str, Any]:
        try:
            trade_date = self._parse_trade_date(kwargs.get("trade_date"))
            return await self._collect_and_run_eod_screener(trade_date)
        except Exception as e:
            logger.error(f"EOD screener manual failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def _run_etf_analysis(self):
        logger.info("Cron trigger: etf_analysis")
        try:
            from api.routes.etf_analysis import run_scheduled_etf_analysis

            result = await run_scheduled_etf_analysis(self._session_factory)
            logger.info(
                "ETF板块轮动分析完成: task=%s, etf_count=%s",
                result.get("task_id"),
                result.get("etf_count"),
            )
        except Exception as e:
            logger.error(f"ETF analysis cron failed: {e}")

    async def _run_etf_analysis_manual(self) -> dict[str, Any]:
        try:
            from api.routes.etf_analysis import run_scheduled_etf_analysis

            return await run_scheduled_etf_analysis(self._session_factory)
        except Exception as e:
            logger.error(f"ETF analysis manual failed: {e}")
            return {"status": "failed", "error": str(e)}

    async def _collect_and_run_eod_screener(self, trade_date: date | None = None) -> dict[str, Any]:
        from data_collector.cache.redis_cache import RedisCache
        from data_collector.sources.market_kline import KlineCollector
        from data_collector.storage import DataStorage
        from eod_screener.screener import EODScreener

        storage = DataStorage(self._session_factory)
        collector = KlineCollector(storage, RedisCache())
        collect_result = await collector.collect_full_market_daily(trade_date, lookback_days=30, mode="intraday")
        if collect_result.get("status") == "failed":
            return {
                "status": "blocked",
                "trade_date": collect_result.get("trade_date") or (str(trade_date) if trade_date else None),
                "count": 0,
                "collect_result": collect_result,
                "screen_result": None,
            }

        screener = EODScreener(self._session_factory)
        run_trade_date = self._parse_trade_date(collect_result.get("trade_date")) or trade_date
        screen_result = await screener.run_with_diagnostics(
            run_trade_date,
            data_mode=str(collect_result.get("data_mode") or "intraday"),
            quote_source=collect_result.get("source"),
            quote_time=collect_result.get("quote_time"),
        )
        return {
            "status": screen_result.get("status"),
            "trade_date": screen_result.get("trade_date"),
            "count": screen_result.get("count", 0),
            "collect_result": collect_result,
            "screen_result": screen_result,
        }

    @staticmethod
    def _parse_trade_date(value: Any) -> date | None:
        if value is None or isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None
