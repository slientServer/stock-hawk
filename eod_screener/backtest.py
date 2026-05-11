"""尾盘选股专用回测引擎"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import asc, desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.models import DailyKline, EodBacktestResult
from eod_screener.config import EODScreenerConfig
from eod_screener.screener import EODScreener

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    code: str
    name: str
    signal_date: str  # ISO date string
    entry_price: float
    exit_price: float
    exit_date: str
    exit_type: str  # take_profit / stop_loss / max_hold / no_data
    holding_days: int
    return_pct: float


class EODBacktestEngine:
    """
    尾盘选股专用回测

    交易模型:
    - 入场: 信号日收盘价
    - T+1起逐日判断:
      1. 开盘跳空触发止盈/止损 → 以开盘价成交
      2. 日内最低价触发止损 → 以止损价成交
      3. 日内最高价触发止盈 → 以止盈价成交
      4. 持有期满 → 以当日收盘价平仓
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: EODScreenerConfig | None = None,
    ):
        self._session_factory = session_factory
        self.config = config or EODScreenerConfig.load()

    async def run(
        self,
        start_date: date,
        end_date: date,
        codes: list[str] | None = None,
        *,
        persist: bool = True,
    ) -> dict:
        """运行回测"""
        task_id = f"eod_bt_{uuid.uuid4().hex[:8]}"
        logger.info(f"尾盘选股回测开始: {start_date} ~ {end_date}, task={task_id}")

        all_trades = await self._collect_trades(start_date, end_date, codes=codes)
        if not all_trades and not await self._get_trade_dates(start_date, end_date):
            return self._empty_result(task_id, start_date, end_date)

        # 统计
        stats = self._calculate_stats(all_trades)
        logger.info(
            f"回测完成: {len(all_trades)} 笔交易, "
            f"胜率={stats['win_rate']:.2%}, "
            f"平均收益={stats['avg_return']:.2f}%"
        )

        # 持久化
        if persist:
            await self._persist(task_id, start_date, end_date, stats, all_trades)

        return {
            "task_id": task_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            **stats,
            "trades": [asdict(t) for t in all_trades],
        }

    async def run_by_code(self, start_date: date, end_date: date, codes: list[str]) -> dict[str, dict]:
        """运行非持久化回测，并按股票代码聚合结果。"""
        unique_codes = sorted({code for code in codes if code})
        if not unique_codes:
            return {}

        trades = await self._collect_trades(start_date, end_date, codes=unique_codes)
        trades_by_code: dict[str, list[TradeRecord]] = {code: [] for code in unique_codes}
        for trade in trades:
            trades_by_code.setdefault(trade.code, []).append(trade)

        results: dict[str, dict] = {}
        for code in unique_codes:
            stats = self._calculate_stats(trades_by_code.get(code, []))
            results[code] = {
                "start_date": str(start_date),
                "end_date": str(end_date),
                **stats,
            }
        return results

    async def _collect_trades(
        self,
        start_date: date,
        end_date: date,
        codes: list[str] | None = None,
    ) -> list[TradeRecord]:
        trade_dates = await self._get_trade_dates(start_date, end_date)
        if not trade_dates:
            return []

        code_filter = sorted({code for code in codes if code}) if codes else None
        screener = EODScreener(self._session_factory, self.config)
        all_trades: list[TradeRecord] = []

        for td in trade_dates:
            selected = await screener.run(td, persist=False, include_backtest=False, codes=code_filter)

            for stock in selected:
                trade = await self._simulate_trade(
                    stock["code"],
                    stock.get("name", ""),
                    td,
                    float(stock["close_price"]),
                )
                if trade.exit_type != "no_data":
                    all_trades.append(trade)

        return all_trades

    async def _simulate_trade(
        self, code: str, name: str, signal_date: date, entry_price: float
    ) -> TradeRecord:
        """模拟单笔交易"""
        tp_price = entry_price * (1 + self.config.take_profit_pct / 100)
        sl_price = entry_price * (1 - self.config.stop_loss_pct / 100)

        future_klines = await self._get_future_klines(code, signal_date)

        # 从T+1开始判断
        holding = [k for k in future_klines if k.trade_date > signal_date]
        holding = holding[: self.config.max_hold_days]

        for i, kline in enumerate(holding, 1):
            open_p = float(kline.open or 0)
            high = float(kline.high or 0)
            low = float(kline.low or 0)
            close = float(kline.close or 0)

            if open_p <= 0:
                continue

            # 开盘跳空止盈
            if open_p >= tp_price:
                return TradeRecord(
                    code, name, str(signal_date), entry_price, open_p,
                    str(kline.trade_date), "take_profit", i,
                    round((open_p / entry_price - 1) * 100, 4),
                )
            # 开盘跳空止损
            if open_p <= sl_price:
                return TradeRecord(
                    code, name, str(signal_date), entry_price, open_p,
                    str(kline.trade_date), "stop_loss", i,
                    round((open_p / entry_price - 1) * 100, 4),
                )

            # 日内止损 (先判断low)
            if low <= sl_price:
                return TradeRecord(
                    code, name, str(signal_date), entry_price, sl_price,
                    str(kline.trade_date), "stop_loss", i,
                    round(-self.config.stop_loss_pct, 4),
                )
            # 日内止盈
            if high >= tp_price:
                return TradeRecord(
                    code, name, str(signal_date), entry_price, tp_price,
                    str(kline.trade_date), "take_profit", i,
                    round(self.config.take_profit_pct, 4),
                )

            # 持有期满
            if i >= self.config.max_hold_days:
                return TradeRecord(
                    code, name, str(signal_date), entry_price, close,
                    str(kline.trade_date), "max_hold", i,
                    round((close / entry_price - 1) * 100, 4),
                )

        # 无后续数据
        return TradeRecord(
            code, name, str(signal_date), entry_price, entry_price,
            str(signal_date), "no_data", 0, 0.0,
        )

    async def _get_trade_dates(self, start_date: date, end_date: date) -> list[date]:
        """从K线表获取区间内的交易日列表"""
        async with self._session_factory() as session:
            stmt = (
                select(DailyKline.trade_date)
                .where(
                    DailyKline.trade_date >= start_date,
                    DailyKline.trade_date <= end_date,
                )
                .distinct()
                .order_by(asc(DailyKline.trade_date))
            )
            rows = (await session.execute(stmt)).scalars().all()
        return list(rows)

    async def _get_future_klines(self, code: str, signal_date: date) -> list:
        """获取信号日之后的K线"""
        max_days = self.config.max_hold_days + 10  # 多取几天以覆盖非交易日
        async with self._session_factory() as session:
            stmt = (
                select(DailyKline)
                .where(
                    DailyKline.code == code,
                    DailyKline.trade_date >= signal_date,
                    DailyKline.trade_date <= signal_date + timedelta(days=max_days),
                )
                .order_by(asc(DailyKline.trade_date))
            )
            return (await session.execute(stmt)).scalars().all()

    @staticmethod
    def _calculate_stats(trades: list[TradeRecord]) -> dict:
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "avg_return": 0.0,
                "max_drawdown": 0.0,
                "profit_loss_ratio": 0.0,
                "win_count": 0,
                "loss_count": 0,
                "avg_holding_days": 0.0,
            }

        wins = [t for t in trades if t.return_pct > 0]
        losses = [t for t in trades if t.return_pct < 0]
        flat = [t for t in trades if t.return_pct == 0]

        win_rate = len(wins) / len(trades)
        avg_return = sum(t.return_pct for t in trades) / len(trades)
        max_dd = abs(min(t.return_pct for t in trades)) if trades else 0.0
        avg_holding = sum(t.holding_days for t in trades) / len(trades)

        avg_win = sum(t.return_pct for t in wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(t.return_pct for t in losses) / len(losses)) if losses else 1.0
        pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

        return {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 4),
            "avg_return": round(avg_return, 4),
            "max_drawdown": round(max_dd, 4),
            "profit_loss_ratio": round(pl_ratio, 4),
            "win_count": len(wins),
            "loss_count": len(losses),
            "avg_holding_days": round(avg_holding, 2),
        }

    async def _persist(
        self, task_id: str, start_date: date, end_date: date, stats: dict, trades: list[TradeRecord]
    ) -> None:
        async with self._session_factory() as session:
            row = EodBacktestResult(
                task_id=task_id,
                start_date=start_date,
                end_date=end_date,
                total_trades=stats["total_trades"],
                win_rate=Decimal(str(stats["win_rate"])),
                avg_return=Decimal(str(stats["avg_return"])),
                max_drawdown=Decimal(str(stats["max_drawdown"])),
                profit_loss_ratio=Decimal(str(stats["profit_loss_ratio"])),
                config_snapshot=self.config.to_dict(),
                result_detail={
                    "stats": stats,
                    "trades": [asdict(t) for t in trades[:500]],  # 限制存储量
                    "total_trade_count": len(trades),
                },
            )
            session.add(row)
            await session.commit()

    @staticmethod
    def _empty_result(task_id: str, start_date: date, end_date: date) -> dict:
        return {
            "task_id": task_id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "max_drawdown": 0.0,
            "profit_loss_ratio": 0.0,
            "win_count": 0,
            "loss_count": 0,
            "avg_holding_days": 0.0,
            "trades": [],
        }
