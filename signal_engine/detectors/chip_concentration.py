"""Shareholder concentration detector."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc, select

from common.models import ShareholderCount
from signal_engine.base_detector import BaseDetector
from signal_engine.models import DetectionContext, SignalResult, SignalType


class ChipConcentrationDetector(BaseDetector):
    signal_type = SignalType.CHIP_CONCENTRATION

    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]:
        if not context.company_codes:
            return []

        signals: list[SignalResult] = []
        async with self._session_factory() as session:
            for code in context.company_codes[:30]:
                row = (
                    await session.execute(
                        select(ShareholderCount)
                        .where(ShareholderCount.code == code)
                        .order_by(desc(ShareholderCount.end_date))
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if not row or row.holder_count_change is None:
                    continue
                change = float(row.holder_count_change)
                if change <= -5:
                    strength = self._clamp(abs(change) / 20, 0.3, 1.0)
                    signals.append(
                        self._make_signal(
                            chain_id=context.chain_id,
                            source_entity=code,
                            target_codes=[code],
                            strength=strength,
                            confidence=0.58,
                            detail=f"{code} 股东户数较上一期下降{abs(change):.1f}%，筹码集中度改善",
                            raw_data_ref=f"chip_concentration:{code}:{row.end_date}",
                            trigger_date=datetime.combine(row.end_date, datetime.min.time()),
                            expire_days=60,
                        )
                    )
        return signals
