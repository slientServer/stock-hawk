"""行情工具：Agent 调用的市场数据查询工具。

优先从 Redis 缓存读取实时行情（TTL=3s），缓存未命中时从 DB 最新 K 线兜底。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.tools.base_tool import BaseTool, ToolResult
from common.models import DailyKline, Stock
from common.stock_service import kline_metrics, normalize_code, num
from data_collector.cache.redis_cache import RedisCache


class MarketTools(BaseTool):
    """市场行情数据工具。

    支持的 action：
    - get_quote(code)              实时行情（Redis → DB 最新 K 线兜底）
    - get_quotes(codes)            批量实时行情
    - get_klines(code, days)       历史 K 线
    - get_metrics(code, days)      K 线衍生指标（涨跌幅、回撤、均量等）
    """

    tool_name = "market_tools"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cache: RedisCache,
    ):
        self._session_factory = session_factory
        self._cache = cache

    async def query(self, action: str, **kwargs) -> ToolResult:
        actions = {
            "get_quote": self._get_quote,
            "get_quotes": self._get_quotes,
            "get_klines": self._get_klines,
            "get_metrics": self._get_metrics,
        }
        fn = actions.get(action)
        if not fn:
            return ToolResult(success=False, error=f"Unknown market action: {action}. Valid: {list(actions)}")
        return await fn(**kwargs)

    # ─── 单只实时行情 ──────────────────────────────────────────────────────────────

    async def _get_quote(self, code: str) -> ToolResult:
        async def _execute():
            normalized = normalize_code(code)
            if not normalized:
                raise ValueError(f"Invalid stock code: {code}")
            # 先查 Redis 缓存（TTL=3s，交易时段由 RealtimeCollector 推送）
            cached = await self._cache.get_realtime_quote(normalized)
            if cached:
                cached["data_source"] = "realtime_cache"
                return cached
            # 缓存未命中：从 DB 最新 K 线兜底
            return await self._quote_from_db(normalized)

        return await self._safe_execute(_execute())

    # ─── 批量实时行情 ──────────────────────────────────────────────────────────────

    async def _get_quotes(self, codes: list[str]) -> ToolResult:
        async def _execute():
            results = []
            for raw in codes:
                result = await self._get_quote(raw)
                if result.success:
                    results.append(result.data)
                else:
                    results.append({"code": raw, "error": result.error})
            return results

        return await self._safe_execute(_execute())

    # ─── 历史 K 线 ───────────────────────────────────────────────────────────────

    async def _get_klines(self, code: str, days: int = 60) -> ToolResult:
        async def _execute():
            normalized = normalize_code(code)
            if not normalized:
                raise ValueError(f"Invalid stock code: {code}")
            bounded = max(1, min(int(days or 60), 500))
            async with self._session_factory() as session:
                rows = list(
                    reversed(
                        (
                            await session.execute(
                                select(DailyKline)
                                .where(DailyKline.code == normalized)
                                .order_by(desc(DailyKline.trade_date))
                                .limit(bounded)
                            )
                        ).scalars().all()
                    )
                )
            return {
                "code": normalized,
                "count": len(rows),
                "klines": [
                    {
                        "date": str(row.trade_date),
                        "open": num(row.open),
                        "high": num(row.high),
                        "low": num(row.low),
                        "close": num(row.close),
                        "volume": num(row.volume),
                        "amount": num(row.amount),
                        "change_pct": num(row.change_pct),
                    }
                    for row in rows
                ],
            }

        return await self._safe_execute(_execute())

    # ─── K 线衍生指标 ─────────────────────────────────────────────────────────────

    async def _get_metrics(self, code: str, days: int = 120) -> ToolResult:
        async def _execute():
            normalized = normalize_code(code)
            if not normalized:
                raise ValueError(f"Invalid stock code: {code}")
            bounded = max(20, min(int(days or 120), 500))
            async with self._session_factory() as session:
                rows = list(
                    reversed(
                        (
                            await session.execute(
                                select(DailyKline)
                                .where(DailyKline.code == normalized)
                                .order_by(desc(DailyKline.trade_date))
                                .limit(bounded)
                            )
                        ).scalars().all()
                    )
                )
            metrics = kline_metrics(rows)
            metrics["code"] = normalized
            metrics["data_source"] = "db_kline"
            return metrics

        return await self._safe_execute(_execute())

    # ─── 内部辅助 ─────────────────────────────────────────────────────────────────

    async def _quote_from_db(self, code: str) -> dict[str, Any]:
        """从 DB 最新 K 线构造行情快照（非实时，仅兜底）。"""
        async with self._session_factory() as session:
            kline = (
                await session.execute(
                    select(DailyKline)
                    .where(DailyKline.code == code)
                    .order_by(desc(DailyKline.trade_date))
                    .limit(1)
                )
            ).scalar_one_or_none()
            stock = (
                await session.execute(select(Stock).where(Stock.code == code))
            ).scalar_one_or_none()

        if not kline:
            return {"code": code, "data_source": "not_found", "error": "无行情数据"}
        return {
            "code": code,
            "name": stock.name if stock else None,
            "trade_date": str(kline.trade_date),
            "close": num(kline.close),
            "open": num(kline.open),
            "high": num(kline.high),
            "low": num(kline.low),
            "volume": num(kline.volume),
            "amount": num(kline.amount),
            "change_pct": num(kline.change_pct),
            "data_source": "db_kline_fallback",
        }
