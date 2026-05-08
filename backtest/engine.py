"""Backtest engine for persisted signal samples."""

import logging
import uuid
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import distinct, func, select

from backtest.replay import FORWARD_WINDOWS, SignalReplay
from backtest.statistics import BacktestStatistics
from common.models import BacktestResult, DailyKline, Signal

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._replay = SignalReplay(session_factory)
        self._stats = BacktestStatistics()

    async def run(
        self,
        start_date,
        end_date,
        signal_type: str | None = None,
        chain_id: str | None = None,
        persist: bool = True,
    ) -> dict:
        task_id = f"backtest_{uuid.uuid4().hex[:8]}"
        # 补采回测所需的 K 线数据
        await self._ensure_kline_coverage(start_date, end_date, signal_type, chain_id)
        samples = await self._replay.collect_samples(start_date, end_date, signal_type=signal_type, chain_id=chain_id)
        stats = self._stats.calculate(samples, signal_type or "all")
        row_id = await self._save_result(task_id, start_date, end_date, signal_type, stats, samples) if persist else None
        return self._to_payload(row_id, task_id, start_date, end_date, signal_type, stats, samples)

    async def run_all_types(self, start_date, end_date, chain_id: str | None = None) -> list[dict]:
        async with self._session_factory() as session:
            rows = (await session.execute(select(distinct(Signal.signal_type)).where(Signal.signal_type.isnot(None)))).all()
        return [await self.run(start_date, end_date, signal_type=row[0], chain_id=chain_id) for row in rows]

    async def _ensure_kline_coverage(self, start_date, end_date, signal_type, chain_id):
        """检查回测涉及的股票是否有足够 K 线数据，缺失则自动补采。"""
        # 1. 查出回测区间的信号及其 target_codes
        stmt = select(Signal).where(
            Signal.trigger_date >= datetime.combine(start_date, time.min),
            Signal.trigger_date <= datetime.combine(end_date, time.max),
        )
        if signal_type:
            stmt = stmt.where(Signal.signal_type == signal_type)
        if chain_id:
            stmt = stmt.where(Signal.chain_id == chain_id)

        async with self._session_factory() as session:
            signals = (await session.execute(stmt)).scalars().all()

        # 2. 提取所有需要的股票代码
        codes_needed: set[str] = set()
        for signal in signals:
            for code in SignalReplay._target_codes(signal):
                codes_needed.add(code)

        if not codes_needed:
            return

        # 3. 检查哪些代码在回测需要的日期范围内缺 K 线
        # 回测需要从 start_date 到 end_date + max_window 的 K 线
        kline_end = date.today()  # 只能采集到今天
        kline_start = start_date if isinstance(start_date, date) else date.fromisoformat(str(start_date))

        async with self._session_factory() as session:
            # 查每只股票已有的 K 线记录数
            result = await session.execute(
                select(DailyKline.code, func.count(DailyKline.id))
                .where(
                    DailyKline.code.in_(codes_needed),
                    DailyKline.trade_date >= kline_start,
                    DailyKline.trade_date <= kline_end,
                )
                .group_by(DailyKline.code)
            )
            coverage = {row[0]: row[1] for row in result.fetchall()}

        # 认为少于 3 条记录的股票需要补采
        codes_to_collect = [code for code in codes_needed if coverage.get(code, 0) < 3]

        if not codes_to_collect:
            return

        logger.info(f"回测补采 K 线: {len(codes_to_collect)} 只股票缺失数据，开始采集")

        # 4. 调用 KlineCollector 补采
        try:
            from data_collector.sources.market_kline import KlineCollector
            from data_collector.storage import DataStorage
            from data_collector.cache.redis_cache import RedisCache

            storage = DataStorage(self._session_factory)
            cache = RedisCache()
            await cache.connect()
            try:
                collector = KlineCollector(storage, cache)
                await collector.collect_batch(codes_to_collect, start_date=kline_start)
                logger.info(f"回测补采完成: {len(codes_to_collect)} 只股票")
            finally:
                await cache.close()
        except Exception as e:
            logger.warning(f"回测补采 K 线失败（不影响回测继续）: {e}")

    async def _save_result(self, task_id, start_date, end_date, signal_type, stats, samples) -> int:
        # 取最短可用窗口的 win_rate
        win_rate = 0
        for w in [5, 10, 20, 30]:
            if stats.win_rate.get(w):
                win_rate = stats.win_rate[w]
                break
        row = BacktestResult(
            task_id=task_id,
            signal_type=signal_type,
            start_date=start_date,
            end_date=end_date,
            total_signals=stats.total_signals,
            win_rate=self._decimal(win_rate),
            avg_return_30d=self._decimal(stats.avg_return.get(30, 0)),
            avg_return_60d=self._decimal(stats.avg_return.get(60, 0)),
            avg_return_90d=self._decimal(stats.avg_return.get(90, 0)),
            max_drawdown=self._decimal(stats.max_drawdown),
            result_detail={
                "stats": asdict(stats),
                "sample_count": len(samples),
                "valid_sample_count": stats.valid_signals,
                "samples": [self._sample_payload(sample) for sample in samples],
                "samples_preview": [self._sample_payload(sample) for sample in samples[:20]],
            },
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    @staticmethod
    def _to_payload(row_id, task_id, start_date, end_date, signal_type, stats, samples) -> dict:
        return {
            "status": "completed",
            "id": row_id,
            "task_id": task_id,
            "signal_type": signal_type,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_signals": stats.total_signals,
            "valid_signals": stats.valid_signals,
            "win_rate": stats.win_rate,
            "avg_return": stats.avg_return,
            "max_drawdown": stats.max_drawdown,
            "avg_return_30d": stats.avg_return.get(30, 0),
            "avg_return_60d": stats.avg_return.get(60, 0),
            "avg_return_90d": stats.avg_return.get(90, 0),
            "result_detail": {
                "stats": asdict(stats),
                "sample_count": len(samples),
                "valid_sample_count": stats.valid_signals,
                "samples": [BacktestEngine._sample_payload(sample) for sample in samples],
                "samples_preview": [BacktestEngine._sample_payload(sample) for sample in samples[:20]],
            },
        }

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(round(float(value or 0), 4)))

    @staticmethod
    def _sample_payload(sample) -> dict:
        payload = asdict(sample)
        payload["trigger_date"] = str(sample.trigger_date)
        return payload
