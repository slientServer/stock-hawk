"""Agent 调度器：ETF 分析、财经资讯、盘前选股、日K线与主力资金定时任务。"""

from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.logger import get_logger

logger = get_logger(__name__)


class AgentScheduler:
    """当前产品定时任务管理。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], automation_runner: Any | None = None):
        self._session_factory = session_factory
        self._scheduler = AsyncIOScheduler()
        self._setup_jobs()

    def _setup_jobs(self) -> None:
        self._scheduler.add_job(
            self._run_finance_news,
            "interval",
            hours=1,
            id="finance_news_hourly",
            name="财经资讯每小时拉取与今日小结",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._run_etf_analysis,
            "cron",
            day_of_week="mon-fri",
            hour=18,
            minute=30,
            id="etf_analysis",
            name="每日盘后 ETF 大模型轮动分析",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._run_pre_market_screen,
            "cron",
            day_of_week="mon-fri",
            hour=7,
            minute=0,
            id="pre_market_screen",
            name="每日盘前 7AM 短线选股",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._run_pre_market_perf_update,
            "cron",
            day_of_week="mon-fri",
            hour=16,
            minute=30,
            id="pre_market_perf",
            name="盘后绩效回填",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._run_daily_kline_update,
            "cron",
            day_of_week="mon-fri",
            hour=15,
            minute=30,
            id="daily_kline_update",
            name="每日收盘后全市场日K线更新",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._run_main_flow_update,
            "cron",
            day_of_week="mon-fri",
            hour=15,
            minute=45,
            id="main_flow_update",
            name="每日收盘后主力资金流更新",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._run_portfolio_monitor,
            "cron",
            day_of_week="mon-fri",
            hour="9-14",
            minute="*/5",
            id="portfolio_monitor",
            name="盘中每5分钟持仓+关注列表盯盘推送",
            max_instances=1,
            coalesce=True,
        )

    def start(self) -> None:
        self._scheduler.start()
        jobs = self._scheduler.get_jobs()
        logger.info("AgentScheduler started with %s jobs", len(jobs))
        for job in jobs:
            logger.info("  Job: %s - %s - next: %s", job.id, job.name, job.next_run_time)

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("AgentScheduler stopped")

    def get_jobs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": str(job.next_run_time),
                "trigger": str(job.trigger),
            }
            for job in self._scheduler.get_jobs()
        ]

    async def trigger_manual(self, workflow_type: str, **kwargs) -> dict[str, Any]:
        if workflow_type == "etf_analysis":
            return await self._run_etf_analysis_manual()
        if workflow_type in {"finance_news", "finance_news_hourly", "news_center"}:
            return await self._run_finance_news_manual(**kwargs)
        if workflow_type == "pre_market":
            return await self._run_pre_market_screen_manual(**kwargs)
        if workflow_type == "pre_market_perf":
            return await self._run_pre_market_perf_manual()
        if workflow_type == "daily_kline":
            return await self._run_daily_kline_update_manual()
        if workflow_type == "main_flow":
            return await self._run_main_flow_update_manual()
        return {"error": f"Unknown workflow_type: {workflow_type}"}

    async def _run_etf_analysis(self) -> None:
        logger.info("Cron trigger: etf_analysis")
        try:
            result = await self._run_etf_analysis_manual()
            logger.info("ETF 分析完成: %s", result.get("task_id") or result.get("status"))
        except Exception as e:
            logger.error("ETF analysis cron failed: %s", e)

    async def _run_etf_analysis_manual(self) -> dict[str, Any]:
        try:
            from api.routes.etf_analysis import run_scheduled_etf_analysis

            return await run_scheduled_etf_analysis(self._session_factory)
        except Exception as e:
            logger.error("ETF analysis manual failed: %s", e)
            return {"status": "failed", "error": str(e)}

    async def _run_finance_news(self) -> None:
        logger.info("Cron trigger: finance_news_hourly")
        try:
            result = await self._run_finance_news_manual()
            logger.info(
                "财经资讯刷新完成: fetched=%s inserted=%s",
                result.get("fetched_count"),
                result.get("inserted_count"),
            )
        except Exception as e:
            logger.error("Finance news cron failed: %s", e)

    async def _run_finance_news_manual(self, **kwargs) -> dict[str, Any]:
        try:
            from api.routes.news_center import run_scheduled_finance_news

            return await run_scheduled_finance_news(self._session_factory)
        except Exception as e:
            logger.error("Finance news manual failed: %s", e)
            return {"status": "failed", "error": str(e)}

    async def _run_pre_market_screen(self) -> None:
        logger.info("Cron trigger: pre_market_screen")
        try:
            result = await self._run_pre_market_screen_manual()
            logger.info(
                "盘前选股完成: aggressive=%s stable=%s",
                result.get("aggressive_count"),
                result.get("stable_count"),
            )
        except Exception as e:
            logger.error("Pre-market screen cron failed: %s", e)

    async def _run_pre_market_screen_manual(self, **kwargs) -> dict[str, Any]:
        try:
            from api.routes.pre_market import run_scheduled_pre_market_screen

            return await run_scheduled_pre_market_screen(self._session_factory)
        except Exception as e:
            logger.error("Pre-market screen manual failed: %s", e)
            return {"status": "failed", "error": str(e)}

    async def _run_pre_market_perf_update(self) -> None:
        logger.info("Cron trigger: pre_market_perf")
        try:
            result = await self._run_pre_market_perf_manual()
            logger.info("绩效回填完成: updated=%s", result.get("updated"))
        except Exception as e:
            logger.error("Pre-market perf cron failed: %s", e)

    async def _run_pre_market_perf_manual(self) -> dict[str, Any]:
        try:
            from api.routes.pre_market import run_scheduled_perf_update

            return await run_scheduled_perf_update(self._session_factory)
        except Exception as e:
            logger.error("Pre-market perf manual failed: %s", e)
            return {"status": "failed", "error": str(e)}

    # ── 日K线更新 ──────────────────────────────────────────────────────────────

    async def _run_daily_kline_update(self) -> None:
        logger.info("Cron trigger: daily_kline_update")
        try:
            result = await self._run_daily_kline_update_manual()
            logger.info(
                "全市场日K线更新完成: status=%s records=%s",
                result.get("status"),
                result.get("records_count"),
            )
        except Exception as e:
            logger.error("Daily kline update cron failed: %s", e)

    async def _run_daily_kline_update_manual(self) -> dict[str, Any]:
        try:
            from data_collector.sources.market_kline import KlineCollector
            from data_collector.storage import DataStorage
            from data_collector.cache.redis_cache import RedisCache

            storage = DataStorage(self._session_factory)
            cache = RedisCache()
            collector = KlineCollector(storage, cache)
            return await collector.collect_full_market_daily(lookback_days=5)
        except Exception as e:
            logger.error("Daily kline update manual failed: %s", e)
            return {"status": "failed", "error": str(e)}

    # ── 主力资金流更新 ──────────────────────────────────────────────────────────

    async def _run_main_flow_update(self) -> None:
        logger.info("Cron trigger: main_flow_update")
        try:
            result = await self._run_main_flow_update_manual()
            logger.info("主力资金流更新完成: records=%s", result.get("records"))
        except Exception as e:
            logger.error("Main flow update cron failed: %s", e)

    async def _run_main_flow_update_manual(self) -> dict[str, Any]:
        try:
            from datetime import date
            from data_collector.sources.main_flow import MainFlowCollector
            from data_collector.storage import DataStorage
            from data_collector.cache.redis_cache import RedisCache

            storage = DataStorage(self._session_factory)
            cache = RedisCache()
            collector = MainFlowCollector(storage, cache)
            records = await collector.collect_tushare_moneyflow(date.today())
            return {"status": "completed", "records": records}
        except Exception as e:
            logger.error("Main flow update manual failed: %s", e)
            return {"status": "failed", "error": str(e)}

    # ── 盯盘监控 ───────────────────────────────────────────────────────────────

    async def _run_portfolio_monitor(self) -> None:
        try:
            from api.routes.portfolio import check_and_notify_positions
            from api.routes.watchlist import check_and_notify_watchlist

            r1 = await check_and_notify_positions(self._session_factory)
            r2 = await check_and_notify_watchlist(self._session_factory)
            total = (r1.get("notified") or 0) + (r2.get("notified") or 0)
            if total > 0:
                logger.info(
                    "盯盘推送: portfolio=%s watchlist=%s",
                    r1.get("notified"), r2.get("notified"),
                )
        except Exception as e:
            logger.error("Portfolio/watchlist monitor failed: %s", e)
