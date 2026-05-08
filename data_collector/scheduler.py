from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from common.logger import get_logger

logger = get_logger(__name__)


class DataScheduler:
    """数据采集调度器"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._realtime_collector = None
        self._kline_collector = None
        self._fund_flow_collector = None
        self._financial_collector = None
        self._commodity_collector = None
        self._news_collector = None
        self._overseas_collector = None
        self._institutional_collector = None
        self._market_basic_collector = None
        self._main_flow_collector = None
        self._stock_codes: list[str] = []

    def configure(
        self,
        realtime_collector=None,
        kline_collector=None,
        fund_flow_collector=None,
        financial_collector=None,
        commodity_collector=None,
        news_collector=None,
        overseas_collector=None,
        institutional_collector=None,
        market_basic_collector=None,
        main_flow_collector=None,
        stock_codes: list[str] = None,
    ):
        """配置采集器实例"""
        self._realtime_collector = realtime_collector
        self._kline_collector = kline_collector
        self._fund_flow_collector = fund_flow_collector
        self._financial_collector = financial_collector
        self._commodity_collector = commodity_collector
        self._news_collector = news_collector
        self._overseas_collector = overseas_collector
        self._institutional_collector = institutional_collector
        self._market_basic_collector = market_basic_collector
        self._main_flow_collector = main_flow_collector
        self._stock_codes = stock_codes or []
        self._setup_jobs()

    def _setup_jobs(self):
        """设置定时任务"""
        # 盘中实时行情：交易日9:30-15:00，每3秒
        if self._realtime_collector and self._stock_codes:
            self.scheduler.add_job(
                self._job_realtime_quotes,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="9-14",
                    second="*/3",
                ),
                id="realtime_quotes",
                replace_existing=True,
                max_instances=1,
            )

        # 收盘后日K线：交易日15:30
        if self._kline_collector and self._stock_codes:
            self.scheduler.add_job(
                self._job_daily_kline,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=15,
                    minute=30,
                ),
                id="daily_kline",
                replace_existing=True,
            )

        # 北向资金：交易日16:00
        if self._fund_flow_collector:
            self.scheduler.add_job(
                self._job_fund_flow,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=16,
                    minute=0,
                ),
                id="fund_flow",
                replace_existing=True,
            )

        # 财报披露数据：交易日18:30，若 token 缺失会记录 blocked，不使用替代 mock。
        if self._financial_collector and self._stock_codes:
            self.scheduler.add_job(
                self._job_financial_report,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=18,
                    minute=30,
                ),
                id="financial_report",
                replace_existing=True,
            )

        # 新闻事件：交易日 9:00-16:00 每小时
        if self._news_collector:
            self.scheduler.add_job(
                self._job_news_events,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour="9-16",
                    minute=5,
                ),
                id="news_events",
                replace_existing=True,
            )

        # 商品价格：交易日 16:30
        if self._commodity_collector:
            self.scheduler.add_job(
                self._job_commodity_prices,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=16,
                    minute=30,
                ),
                id="commodity_prices",
                replace_existing=True,
            )

        # 海外行情（美股）：每天 6:00（美股收盘后）
        if self._overseas_collector:
            self.scheduler.add_job(
                self._job_overseas_stocks,
                CronTrigger(hour=6, minute=0),
                id="overseas_stocks",
                replace_existing=True,
            )

        # 机构持仓：每周六 10:00
        if self._institutional_collector:
            self.scheduler.add_job(
                self._job_institutional_holdings,
                CronTrigger(day_of_week="sat", hour=10, minute=0),
                id="institutional_holdings",
                replace_existing=True,
            )

        # 个股详情（市值+上市日期）：交易日 16:00
        if self._market_basic_collector:
            self.scheduler.add_job(
                self._job_stock_detail,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=16,
                    minute=0,
                ),
                id="stock_detail",
                replace_existing=True,
            )

        # 主力资金流：交易日 15:45
        if self._main_flow_collector and self._stock_codes:
            self.scheduler.add_job(
                self._job_main_flow,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=15,
                    minute=45,
                ),
                id="main_flow",
                replace_existing=True,
            )

    async def _job_realtime_quotes(self):
        """实时行情采集任务"""
        if not self._is_trading_time():
            return
        try:
            await self._realtime_collector.collect_and_cache(self._stock_codes)
        except Exception as e:
            logger.error(f"实时行情采集任务异常: {e}")

    async def _job_daily_kline(self):
        """日K线采集任务"""
        if not self._is_trading_day():
            return
        try:
            await self._kline_collector.collect_incremental(self._stock_codes)
        except Exception as e:
            logger.error(f"日K线采集任务异常: {e}")

    async def _job_fund_flow(self):
        """北向资金采集任务"""
        if not self._is_trading_day():
            return
        try:
            await self._fund_flow_collector.collect_north_flow()
        except Exception as e:
            logger.error(f"北向资金采集任务异常: {e}")

    async def _job_financial_report(self):
        """财报数据采集任务"""
        if not self._is_trading_day():
            return
        try:
            await self._financial_collector.collect_batch(self._stock_codes)
        except Exception as e:
            logger.error(f"财报采集任务异常: {e}")

    async def _job_news_events(self):
        """新闻事件采集任务"""
        if not self._is_trading_day():
            return
        try:
            await self._news_collector.collect_incremental(self._stock_codes[:30])
        except Exception as e:
            logger.error(f"新闻采集任务异常: {e}")

    async def _job_commodity_prices(self):
        """商品价格采集任务"""
        if not self._is_trading_day():
            return
        try:
            await self._commodity_collector.collect_incremental()
        except Exception as e:
            logger.error(f"商品价格采集任务异常: {e}")

    async def _job_overseas_stocks(self):
        """海外行情采集任务"""
        try:
            await self._overseas_collector.collect_incremental()
        except Exception as e:
            logger.error(f"海外行情采集任务异常: {e}")

    async def _job_institutional_holdings(self):
        """机构持仓采集任务"""
        try:
            await self._institutional_collector.collect_incremental()
        except Exception as e:
            logger.error(f"机构持仓采集任务异常: {e}")

    async def _job_stock_detail(self):
        """个股详情（市值+上市日期）采集任务"""
        if not self._is_trading_day():
            return
        try:
            await self._market_basic_collector.collect_stock_detail()
        except Exception as e:
            logger.error(f"个股详情采集任务异常: {e}")

    async def _job_main_flow(self):
        """主力资金流采集任务"""
        if not self._is_trading_day():
            return
        try:
            await self._main_flow_collector.collect_incremental(self._stock_codes)
        except Exception as e:
            logger.error(f"主力资金流采集任务异常: {e}")

    def _is_trading_day(self) -> bool:
        """判断今日是否为交易日（简单实现：工作日）"""
        from datetime import date as date_cls
        today = date_cls.today()
        return today.weekday() < 5

    def _is_trading_time(self) -> bool:
        """判断当前是否为交易时间段 9:30-11:30, 13:00-15:00"""
        from datetime import datetime
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        current_minutes = now.hour * 60 + now.minute
        morning_start = 9 * 60 + 30
        morning_end = 11 * 60 + 30
        afternoon_start = 13 * 60
        afternoon_end = 15 * 60
        return (morning_start <= current_minutes <= morning_end) or (
            afternoon_start <= current_minutes <= afternoon_end
        )

    def start(self):
        self.scheduler.start()
        logger.info("数据采集调度器已启动")

    def shutdown(self):
        self.scheduler.shutdown()
        logger.info("数据采集调度器已停止")
