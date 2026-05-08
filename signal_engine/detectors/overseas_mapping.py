"""Overseas mapping detector - 海外映射信号检测

基于 overseas_stocks + overseas_mappings 表，检测海外对标股票涨幅明显领先A股的情况。
触发条件：海外标的近5日涨幅 vs A股对应标的涨幅，gap > 阈值（8%）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, desc, select

from common.models import DailyKline, OverseasMapping, OverseasStock
from signal_engine.base_detector import BaseDetector
from signal_engine.models import DetectionContext, SignalResult, SignalType


class OverseasMappingDetector(BaseDetector):
    signal_type = SignalType.OVERSEAS_MAPPING

    GAP_THRESHOLD = 8.0  # 海外领先A股涨幅阈值(%)
    LOOKBACK_DAYS = 5

    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]:
        if not context.company_codes:
            return []

        signals: list[SignalResult] = []
        chain_id = context.chain_id

        async with self._session_factory() as session:
            # 查询与本产业链公司相关的映射关系
            mappings = (
                await session.execute(
                    select(OverseasMapping).where(
                        OverseasMapping.a_code.in_(context.company_codes)
                    )
                )
            ).scalars().all()

            if not mappings:
                return []

            cutoff = date.today() - timedelta(days=self.LOOKBACK_DAYS + 5)

            for mapping in mappings:
                signal = await self._check_mapping_gap(
                    session, mapping, cutoff, chain_id
                )
                if signal:
                    signals.append(signal)

        return signals

    async def _check_mapping_gap(
        self, session, mapping, cutoff: date, chain_id: str
    ) -> SignalResult | None:
        """检查单个映射对的涨幅差距"""
        # 获取海外标的近期行情
        overseas_rows = (
            await session.execute(
                select(OverseasStock)
                .where(
                    and_(
                        OverseasStock.symbol == mapping.overseas_symbol,
                        OverseasStock.trade_date >= cutoff,
                    )
                )
                .order_by(desc(OverseasStock.trade_date))
                .limit(self.LOOKBACK_DAYS + 3)
            )
        ).scalars().all()

        if len(overseas_rows) < 2:
            return None

        # 获取A股标的近期行情
        a_rows = (
            await session.execute(
                select(DailyKline)
                .where(
                    and_(
                        DailyKline.code == mapping.a_code,
                        DailyKline.trade_date >= cutoff,
                    )
                )
                .order_by(desc(DailyKline.trade_date))
                .limit(self.LOOKBACK_DAYS + 3)
            )
        ).scalars().all()

        if len(a_rows) < 2:
            return None

        # 计算海外标的近N日涨幅
        overseas_change = self._calc_period_change(overseas_rows)
        # 计算A股标的近N日涨幅
        a_change = self._calc_period_change_kline(a_rows)

        if overseas_change is None or a_change is None:
            return None

        # 海外领先幅度
        gap = overseas_change - a_change

        if gap < self.GAP_THRESHOLD:
            return None

        # 信号强度与gap成正比
        strength = min(1.0, gap / 25.0)
        strength = max(0.3, strength)

        # 置信度受映射关系 confidence 影响
        mapping_confidence = float(mapping.confidence) if mapping.confidence else 0.6
        confidence = min(0.9, mapping_confidence * 0.8 + 0.2)

        relation_desc = {
            "benchmark": "对标",
            "competitor": "竞品",
            "upstream": "上游",
        }.get(mapping.relation_type or "", "关联")

        detail = (
            f"海外映射信号: {mapping.overseas_name}({mapping.overseas_symbol}) "
            f"近{self.LOOKBACK_DAYS}日涨{overseas_change:.1f}%, "
            f"A股{relation_desc}{mapping.a_name}({mapping.a_code})涨{a_change:.1f}%, "
            f"差距{gap:.1f}%"
        )

        return self._make_signal(
            chain_id=chain_id,
            source_entity=mapping.overseas_symbol,
            target_codes=[mapping.a_code],
            strength=strength,
            confidence=confidence,
            detail=detail,
            raw_data_ref=f"overseas_mapping:{mapping.overseas_symbol}:{mapping.a_code}:{date.today()}",
            trigger_date=datetime.combine(overseas_rows[0].trade_date, datetime.min.time()),
            expire_days=7,
            source="signal_engine:overseas_mapping",
        )

    @staticmethod
    def _calc_period_change(rows: list) -> float | None:
        """计算海外股票期间涨幅"""
        if len(rows) < 2:
            return None
        latest_close = float(rows[0].close) if rows[0].close else None
        oldest_close = float(rows[-1].close) if rows[-1].close else None
        if not latest_close or not oldest_close or oldest_close <= 0:
            return None
        return (latest_close - oldest_close) / oldest_close * 100

    @staticmethod
    def _calc_period_change_kline(rows: list) -> float | None:
        """计算A股K线期间涨幅"""
        if len(rows) < 2:
            return None
        latest_close = float(rows[0].close) if rows[0].close else None
        oldest_close = float(rows[-1].close) if rows[-1].close else None
        if not latest_close or not oldest_close or oldest_close <= 0:
            return None
        return (latest_close - oldest_close) / oldest_close * 100
