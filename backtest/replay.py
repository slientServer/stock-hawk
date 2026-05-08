"""Historical signal replay."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import asc, select

from common.models import DailyKline, Signal, Stock

FORWARD_WINDOWS = [5, 10, 20, 30, 60, 90]


@dataclass(slots=True)
class SignalSample:
    signal_id: int
    signal_type: str
    chain_id: str | None
    target_code: str
    trigger_date: date
    strength: float
    confidence: float
    entry_price: float
    returns: dict[int, float] = field(default_factory=dict)
    max_drawdown: float = 0.0
    valid: bool = False
    stock_name: str | None = None


class SignalReplay:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    async def collect_samples(
        self,
        start_date: date,
        end_date: date,
        signal_type: str | None = None,
        chain_id: str | None = None,
    ) -> list[SignalSample]:
        stmt = select(Signal).where(
            Signal.trigger_date >= datetime.combine(start_date, time.min),
            Signal.trigger_date <= datetime.combine(end_date, time.max),
        )
        if signal_type:
            stmt = stmt.where(Signal.signal_type == signal_type)
        if chain_id:
            stmt = stmt.where(Signal.chain_id == chain_id)
        stmt = stmt.order_by(asc(Signal.trigger_date), asc(Signal.id))

        async with self._session_factory() as session:
            signals = (await session.execute(stmt)).scalars().all()
            codes_by_signal: list[tuple[Signal, list[str]]] = []
            all_codes: set[str] = set()
            for signal in signals:
                codes = self._target_codes(signal)
                codes_by_signal.append((signal, codes))
                all_codes.update(codes)

            stock_names: dict[str, str | None] = {}
            if all_codes:
                rows = await session.execute(select(Stock.code, Stock.name).where(Stock.code.in_(all_codes)))
                stock_names = {code: name for code, name in rows}

            samples: list[SignalSample] = []
            for signal, codes in codes_by_signal:
                for code in codes:
                    samples.append(await self._build_sample(session, signal, code, stock_names.get(code)))
            return samples

    async def _build_sample(self, session, signal: Signal, code: str, stock_name: str | None = None) -> SignalSample:
        trigger_date = self._as_date(signal.trigger_date)
        stmt = (
            select(DailyKline)
            .where(
                DailyKline.code == code,
                DailyKline.trade_date >= trigger_date,
                DailyKline.trade_date <= trigger_date + timedelta(days=max(FORWARD_WINDOWS) + 10),
            )
            .order_by(asc(DailyKline.trade_date))
        )
        rows = (await session.execute(stmt)).scalars().all()
        entry = self._float(rows[0].close) if rows else 0.0
        returns: dict[int, float] = {}
        max_drawdown = 0.0
        if entry > 0:
            lows = [self._float(row.low) for row in rows if self._float(row.low) > 0]
            max_drawdown = max([(entry - low) / entry for low in lows] or [0.0])
            for window in FORWARD_WINDOWS:
                target_date = trigger_date + timedelta(days=window)
                exit_row = next((row for row in rows if row.trade_date >= target_date), None)
                if exit_row and self._float(exit_row.close) > 0:
                    returns[window] = self._float(exit_row.close) / entry - 1

        return SignalSample(
            signal_id=int(signal.id),
            signal_type=signal.signal_type or "",
            chain_id=signal.chain_id,
            target_code=code,
            trigger_date=trigger_date,
            strength=self._float(signal.strength),
            confidence=self._float(signal.confidence),
            entry_price=entry,
            returns=returns,
            max_drawdown=max(0.0, max_drawdown),
            valid=entry > 0 and bool(returns),
            stock_name=stock_name,
        )

    @classmethod
    def _target_codes(cls, signal: Signal) -> list[str]:
        codes: list[str] = []
        payload = signal.target_codes
        values: list[Any]
        if isinstance(payload, list):
            values = payload
        elif isinstance(payload, dict):
            values = []
            for value in payload.values():
                values.extend(value if isinstance(value, list) else [value])
        else:
            values = [payload]
        if signal.source_entity:
            values.append(signal.source_entity)
        for value in values:
            code = cls._normalize_code(value)
            if code and code not in codes:
                codes.append(code)
        return codes

    @staticmethod
    def _normalize_code(value: Any) -> str | None:
        text = str(value or "").strip().upper()
        if "." in text:
            text = text.split(".", 1)[0]
        if text.startswith(("SH", "SZ", "BJ")):
            text = text[2:]
        return text.zfill(6) if text.isdigit() else None

    @staticmethod
    def _as_date(value: datetime | date | None) -> date:
        if isinstance(value, datetime):
            return value.date()
        return value or date.today()

    @staticmethod
    def _float(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, Decimal):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
