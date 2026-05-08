from datetime import date

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.models import DailyKline, CollectLog
from data_collector.cache.redis_cache import RedisCache


class IncrementalManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], cache: RedisCache):
        self.session_factory = session_factory
        self.cache = cache

    async def get_missing_trade_dates(self, code: str, start_date: date, end_date: date) -> list[date]:
        async with self.session_factory() as session:
            stmt = (
                select(DailyKline.trade_date)
                .where(
                    DailyKline.code == code,
                    DailyKline.trade_date >= start_date,
                    DailyKline.trade_date <= end_date,
                )
                .order_by(DailyKline.trade_date)
            )
            result = await session.execute(stmt)
            existing_dates = {row[0] for row in result.fetchall()}

        all_dates = []
        current = start_date
        from datetime import timedelta

        while current <= end_date:
            if current.weekday() < 5:  # 排除周末
                all_dates.append(current)
            current += timedelta(days=1)

        return [d for d in all_dates if d not in existing_dates]

    async def mark_as_collected(self, source: str, trade_date: date):
        date_str = trade_date.isoformat()
        await self.cache.set_incremental_marker(source, date_str)

    async def get_last_collected_date(self, source: str, code: str = None) -> date | None:
        async with self.session_factory() as session:
            if code:
                stmt = (
                    select(func.max(DailyKline.trade_date))
                    .where(DailyKline.code == code, DailyKline.source == source)
                )
            else:
                stmt = (
                    select(func.max(CollectLog.finished_at))
                    .where(CollectLog.source == source, CollectLog.status == "success")
                )
            result = await session.execute(stmt)
            val = result.scalar()
            if val is None:
                return None
            if isinstance(val, date):
                return val
            return val.date() if hasattr(val, "date") else None
