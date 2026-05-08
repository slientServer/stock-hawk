"""Base class for signal detectors."""

from __future__ import annotations

import abc
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signal_engine.models import DetectionContext, SignalResult, SignalType, as_decimal


class BaseDetector(abc.ABC):
    signal_type: SignalType

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._llm = llm_client

    async def detect(self, context: DetectionContext) -> list[SignalResult]:
        signals = await self._detect_impl(context)
        return [signal for signal in signals if signal is not None]

    @abc.abstractmethod
    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]: ...

    def _make_signal(
        self,
        *,
        chain_id: str,
        source_entity: str | None = None,
        target_codes: list[str] | None = None,
        strength: Decimal | float | str = Decimal("0.5"),
        confidence: Decimal | float | str = Decimal("0.6"),
        detail: str = "",
        raw_data_ref: str | None = None,
        trigger_date: datetime | None = None,
        expire_days: int = 30,
        source: str = "signal_engine",
    ) -> SignalResult:
        trigger = trigger_date or datetime.now()
        return SignalResult(
            signal_type=self.signal_type,
            chain_id=chain_id,
            source_entity=source_entity,
            target_codes=target_codes or [],
            strength=as_decimal(strength),
            confidence=as_decimal(confidence, default="0.6"),
            detail=detail,
            raw_data_ref=raw_data_ref,
            trigger_date=trigger,
            expire_date=trigger + timedelta(days=expire_days),
            source=source,
        )

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> Decimal:
        return Decimal(str(max(minimum, min(maximum, value)))).quantize(Decimal("0.001"))
