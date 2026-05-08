"""Persistence helpers for signal scan results."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.models import ChainScore, Signal
from signal_engine.models import ScoreResult, SignalResult


class SignalHistory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def save_signals(self, signals: list[SignalResult]) -> int:
        if not signals:
            return 0

        refs = [signal.raw_data_ref for signal in signals if signal.raw_data_ref]
        existing: set[str] = set()
        async with self._session_factory() as session:
            if refs:
                rows = await session.execute(select(Signal.raw_data_ref).where(Signal.raw_data_ref.in_(refs)))
                existing = {row[0] for row in rows.all() if row[0]}

            inserted = 0
            for signal in signals:
                if signal.raw_data_ref and signal.raw_data_ref in existing:
                    continue
                session.add(Signal(**signal.to_record()))
                inserted += 1
            await session.commit()
            return inserted

    async def save_score(self, result: ScoreResult) -> None:
        record = result.to_record()
        async with self._session_factory() as session:
            stmt = insert(ChainScore).values(**record)
            update_cols = {
                "score": stmt.excluded.score,
                "score_detail": stmt.excluded.score_detail,
                "signal_count": stmt.excluded.signal_count,
            }
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["chain_id", "score_date"],
                    set_=update_cols,
                )
            )
            await session.commit()
