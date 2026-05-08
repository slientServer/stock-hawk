"""Supply shortage detector - 供需紧张信号检测

基于 commodity_prices 表中的商品价格数据，检测产业链关联商品连续上涨信号。
触发条件：近5日涨幅 > 阈值（如5%），或连续3日以上上涨。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import and_, desc, select

from common.models import CommodityPrice
from signal_engine.base_detector import BaseDetector
from signal_engine.models import DetectionContext, SignalResult, SignalType


class SupplyShortageDetector(BaseDetector):
    signal_type = SignalType.SUPPLY_SHORTAGE

    # 触发阈值
    PRICE_RISE_THRESHOLD = 5.0  # 5日累计涨幅 > 5%
    CONSECUTIVE_RISE_DAYS = 3   # 连续上涨天数

    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]:
        signals: list[SignalResult] = []
        chain_id = context.chain_id

        async with self._session_factory() as session:
            # 查找与本产业链关联的商品（通过 chain_id 字段）
            cutoff = date.today() - timedelta(days=30)
            products_result = await session.execute(
                select(CommodityPrice.product_name)
                .where(
                    and_(
                        CommodityPrice.chain_id == chain_id,
                        CommodityPrice.price_date >= cutoff,
                    )
                )
                .distinct()
            )
            products = [row[0] for row in products_result.fetchall()]

            if not products:
                return []

            for product_name in products:
                rows = (
                    await session.execute(
                        select(CommodityPrice)
                        .where(
                            and_(
                                CommodityPrice.product_name == product_name,
                                CommodityPrice.price_date >= cutoff,
                            )
                        )
                        .order_by(desc(CommodityPrice.price_date))
                        .limit(30)
                    )
                ).scalars().all()

                if len(rows) < 3:
                    continue

                signal = self._analyze_price_trend(rows, chain_id, product_name, context)
                if signal:
                    signals.append(signal)

        return signals

    def _analyze_price_trend(
        self,
        rows: list,
        chain_id: str,
        product_name: str,
        context: DetectionContext,
    ) -> SignalResult | None:
        """分析价格趋势，判断是否触发供需紧张信号"""
        prices = [(r.price_date, float(r.price)) for r in rows if r.price and float(r.price) > 0]

        if len(prices) < 3:
            return None

        # 计算5日涨幅
        recent_5 = prices[:5] if len(prices) >= 5 else prices
        latest_price = recent_5[0][1]
        base_price = recent_5[-1][1]
        five_day_change = (latest_price - base_price) / base_price * 100 if base_price > 0 else 0

        # 计算连续上涨天数
        consecutive_up = 0
        for i in range(len(prices) - 1):
            if prices[i][1] > prices[i + 1][1]:
                consecutive_up += 1
            else:
                break

        triggered = (
            five_day_change >= self.PRICE_RISE_THRESHOLD
            or consecutive_up >= self.CONSECUTIVE_RISE_DAYS
        )

        if not triggered:
            return None

        # 信号强度
        strength_from_change = min(1.0, five_day_change / 15.0) if five_day_change > 0 else 0
        strength_from_days = min(1.0, consecutive_up / 7.0)
        strength = max(0.3, min(1.0, max(strength_from_change, strength_from_days)))

        confidence = min(0.9, 0.5 + len(prices) * 0.02)

        detail = (
            f"商品[{product_name}]供需紧张: "
            f"近5日涨幅{five_day_change:.1f}%, 连续上涨{consecutive_up}天, "
            f"最新价格{latest_price:.2f}"
        )

        return self._make_signal(
            chain_id=chain_id,
            source_entity=product_name,
            target_codes=context.company_codes[:10],
            strength=strength,
            confidence=confidence,
            detail=detail,
            raw_data_ref=f"supply_shortage:{product_name}:{prices[0][0]}",
            trigger_date=datetime.combine(prices[0][0], datetime.min.time()),
            expire_days=14,
            source="signal_engine:supply_shortage",
        )
