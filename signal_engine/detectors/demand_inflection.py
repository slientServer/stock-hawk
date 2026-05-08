"""Demand inflection detector based on disclosed revenue growth."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select

from common.models import FinancialReport
from signal_engine.base_detector import BaseDetector
from signal_engine.models import DetectionContext, SignalResult, SignalType


class DemandInflectionDetector(BaseDetector):
    signal_type = SignalType.DEMAND_INFLECTION

    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]:
        if not context.company_codes:
            return []

        signals: list[SignalResult] = []
        async with self._session_factory() as session:
            for code in context.company_codes[:30]:
                rows = (
                    (
                        await session.execute(
                            select(FinancialReport)
                            .where(FinancialReport.code == code)
                            .order_by(desc(FinancialReport.report_date))
                            .limit(2)
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(rows) < 2:
                    continue
                latest, previous = rows[0], rows[1]
                if latest.publish_date is None or latest.revenue_yoy is None:
                    continue
                latest_yoy = float(latest.revenue_yoy)
                previous_yoy = float(previous.revenue_yoy or 0)
                improvement = latest_yoy - previous_yoy
                if latest_yoy >= 10 and improvement >= 5:
                    strength = self._clamp(min(1.0, latest_yoy / 80 + improvement / 80), 0.3, 1.0)
                    signals.append(
                        self._make_signal(
                            chain_id=context.chain_id,
                            source_entity=code,
                            target_codes=[code],
                            strength=strength,
                            confidence=0.7,
                            detail=f"{code} 最新营收同比{latest_yoy:.1f}%，较上一期改善{improvement:.1f}pct，需求出现改善信号",
                            raw_data_ref=f"demand_inflection:{code}:{latest.report_date}",
                            trigger_date=datetime.combine(latest.publish_date, datetime.min.time()),
                            expire_days=90,
                        )
                    )
        return signals
