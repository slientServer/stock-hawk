"""估值百分位检测：低估值 + 盈利改善信号"""

from datetime import date, datetime, timedelta

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.logger import get_logger
from common.models import FinancialReport
from signal_engine.base_detector import BaseDetector
from signal_engine.models import DetectionContext, SignalResult, SignalType

logger = get_logger(__name__)

PERCENTILE_THRESHOLD = 20  # PE 百分位 < 20% 算低估
HISTORY_YEARS = 3
MIN_HISTORY_POINTS = 6


class ValuationPercentileDetector(BaseDetector):
    """估值百分位检测器

    逻辑: 披露后的财报 PE 处于近3年 20% 分位以下 + 盈利同比改善 → 估值修复信号
    """

    signal_type = SignalType.VALUATION_PERCENTILE

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], llm_client=None):
        super().__init__(session_factory, llm_client)

    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]:
        signals: list[SignalResult] = []

        for code in context.company_codes[:15]:
            result = await self._check_valuation(code, context)
            if result:
                signals.append(result)

        return signals

    async def _check_valuation(self, code: str, context: DetectionContext) -> SignalResult | None:
        """检查个股估值百分位"""
        # 获取最新财报
        latest_reports = await self._get_reports(code, periods=2)
        if len(latest_reports) < 2:
            return None

        latest = latest_reports[0]
        prev = latest_reports[1]

        # 必须使用披露日作为信号触发日；缺 publish_date 时跳过，避免回测前视。
        if latest.publish_date is None:
            return None

        current_pe = float(latest.pe_ratio) if latest.pe_ratio is not None else None
        if current_pe is None or current_pe <= 0 or current_pe > 500:
            return None

        # 盈利同比改善判断：最新净利润同比为正，且高于上一期同比。
        if latest.net_profit_yoy is None:
            return None
        latest_profit_yoy = float(latest.net_profit_yoy)
        prev_profit_yoy = float(prev.net_profit_yoy) if prev.net_profit_yoy is not None else None
        profit_improving = latest_profit_yoy > 0 and (prev_profit_yoy is None or latest_profit_yoy > prev_profit_yoy)
        if not profit_improving:
            return None

        # 计算历史 PE 百分位
        percentile = await self._calc_pe_percentile(code, current_pe, context.run_date)
        if percentile is None:
            return None

        if percentile < PERCENTILE_THRESHOLD:
            strength = self._clamp((PERCENTILE_THRESHOLD + 10 - percentile) / 30, 0.3, 1.0)
            confidence = 0.65

            return self._make_signal(
                chain_id=context.chain_id,
                source_entity=code,
                target_codes=[code],
                strength=strength,
                confidence=confidence,
                detail=(
                    f"{code} PE={current_pe:.1f}，处于近{HISTORY_YEARS}年"
                    f"{percentile:.0f}%分位（低估），且净利润同比改善，"
                    f"存在估值修复机会"
                ),
                raw_data_ref=f"valuation:{code}:{context.run_date}",
                trigger_date=datetime.combine(latest.publish_date, datetime.min.time()),
                expire_days=60,
            )

        return None

    async def _get_reports(self, code: str, periods: int) -> list[FinancialReport]:
        async with self._session_factory() as session:
            stmt = (
                select(FinancialReport)
                .where(FinancialReport.code == code)
                .order_by(desc(FinancialReport.report_date))
                .limit(periods)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def _calc_pe_percentile(self, code: str, current_pe: float, as_of: date) -> float | None:
        """计算当前 PE 在历史中的百分位"""
        start = as_of - timedelta(days=HISTORY_YEARS * 365)

        async with self._session_factory() as session:
            stmt = (
                select(FinancialReport.pe_ratio)
                .where(
                    and_(
                        FinancialReport.code == code,
                        FinancialReport.report_date >= start,
                        FinancialReport.report_date <= as_of,
                        FinancialReport.pe_ratio > 0,
                    )
                )
                .order_by(FinancialReport.report_date)
            )
            result = await session.execute(stmt)
            historical_pes = [float(r[0]) for r in result.all() if r[0] and 0 < float(r[0]) < 500]

        if len(historical_pes) < MIN_HISTORY_POINTS:
            return None

        # 百分位 = 低于当前 PE 的比例
        below_count = sum(1 for pe in historical_pes if pe < current_pe)
        return (below_count / len(historical_pes)) * 100
