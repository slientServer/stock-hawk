"""板块联动检测：同产业链公司集体上涨信号"""

from datetime import date, timedelta
from statistics import median

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.logger import get_logger
from common.models import DailyKline
from signal_engine.base_detector import BaseDetector
from signal_engine.models import DetectionContext, SignalResult, SignalType

logger = get_logger(__name__)

LOOKBACK_DAYS = 10
CALC_DAYS = 5
MEDIAN_GAIN_THRESHOLD = 0.03  # 中位数涨幅 > 3%
UP_RATIO_THRESHOLD = 0.60  # 上涨比例 > 60%


class SectorLinkageDetector(BaseDetector):
    """板块联动检测器

    逻辑: 同产业链公司近5日涨幅中位数 > 3% 且上涨比例 > 60%
    """

    signal_type = SignalType.SECTOR_LINKAGE

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], llm_client=None):
        super().__init__(session_factory, llm_client)

    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]:
        if len(context.company_codes) < 3:
            return []

        gains: dict[str, float] = {}
        for code in context.company_codes[:30]:
            gain = await self._calc_period_gain(code, context.run_date)
            if gain is not None:
                gains[code] = gain

        if len(gains) < 3:
            return []

        gain_values = list(gains.values())
        median_gain = median(gain_values)
        up_count = sum(1 for g in gain_values if g > 0)
        up_ratio = up_count / len(gain_values)

        if median_gain >= MEDIAN_GAIN_THRESHOLD and up_ratio >= UP_RATIO_THRESHOLD:
            strength = self._clamp(median_gain / 0.10, 0.3, 1.0)
            confidence = self._clamp(up_ratio, 0.5, 0.9)

            top_stocks = sorted(gains.items(), key=lambda x: x[1], reverse=True)[:5]
            top_text = ", ".join(f"{c}(+{g*100:.1f}%)" for c, g in top_stocks)

            return [
                self._make_signal(
                    chain_id=context.chain_id,
                    source_entity=context.chain_id,
                    target_codes=list(gains.keys()),
                    strength=strength,
                    confidence=confidence,
                    detail=(
                        f"板块联动：{len(gains)}只股票中{up_count}只上涨"
                        f"（{up_ratio*100:.0f}%），中位数涨幅{median_gain*100:.1f}%。"
                        f"领涨: {top_text}"
                    ),
                    raw_data_ref=f"sector_linkage:{context.chain_id}:{context.run_date}",
                )
            ]

        return []

    async def _calc_period_gain(self, code: str, as_of: date) -> float | None:
        """计算个股近 CALC_DAYS 日涨幅"""
        start = as_of - timedelta(days=LOOKBACK_DAYS)
        async with self._session_factory() as session:
            stmt = (
                select(DailyKline.trade_date, DailyKline.close)
                .where(
                    and_(
                        DailyKline.code == code,
                        DailyKline.trade_date >= start,
                        DailyKline.trade_date <= as_of,
                    )
                )
                .order_by(DailyKline.trade_date)
            )
            result = await session.execute(stmt)
            rows = result.all()

        if len(rows) < CALC_DAYS + 1:
            return None

        recent = rows[-CALC_DAYS - 1 :]
        start_close = float(recent[0].close) if recent[0].close else None
        end_close = float(recent[-1].close) if recent[-1].close else None

        if not start_close or not end_close or start_close == 0:
            return None

        return (end_close - start_close) / start_close
