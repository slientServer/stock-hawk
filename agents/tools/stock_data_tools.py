"""股票数据工具：封装 Agent 可调用的真实入库数据查询。"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.tools.base_tool import BaseTool, ToolResult
from common.models import DailyKline, FinancialReport, Signal, Stock
from common.stock_service import (
    build_picks,
    candidate_data_counts,
    chain_maps,
    data_counts,
    financial_payload,
    kline_metrics,
    normalize_code,
    num,
)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_stock_code(value: Any) -> str | None:
    return normalize_code(value)


def extract_stock_codes(text: str) -> list[str]:
    codes: list[str] = []
    for raw in re.findall(r"(?:SH|SZ|BJ)?\d{6}(?:\.(?:SH|SZ|BJ))?", text.upper()):
        code = normalize_stock_code(raw)
        if code and code not in codes:
            codes.append(code)
    return codes


def _codes_from_signal_payload(payload: Any) -> set[str]:
    codes: set[str] = set()
    if payload is None:
        return codes
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        values = []
        for item in payload.values():
            if isinstance(item, list):
                values.extend(item)
            else:
                values.append(item)
    else:
        values = [payload]

    for value in values:
        code = normalize_stock_code(value)
        if code:
            codes.add(code)
    return codes


class StockDataTools(BaseTool):
    """股票分析 Agent 的数据查询工具。"""

    tool_name = "stock_data_tools"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def query(self, action: str, **kwargs) -> ToolResult:
        actions = {
            "coverage": self.get_coverage,
            "list_chains": self.list_chains,
            "screen": self.screen_stocks,
            "snapshot": self.get_stock_snapshot,
            "compare": self.compare_stocks,
            "search": self.search_stocks,
        }
        fn = actions.get(action)
        if not fn:
            return ToolResult(success=False, error=f"Unknown stock data action: {action}")
        return await fn(**kwargs)

    async def get_coverage(self) -> ToolResult:
        async def _execute():
            async with self._session_factory() as session:
                counts = await data_counts(session)
                candidate_counts = await candidate_data_counts(session)
            return {**counts, **candidate_counts}

        return await self._safe_execute(_execute())

    async def list_chains(self) -> ToolResult:
        async def _execute():
            chains, _ = await chain_maps()
            result = []
            for chain in chains:
                name = chain.get("name") or chain.get("chain_name") or chain.get("chain_id")
                if name:
                    result.append(
                        {
                            "name": name,
                            "chain_id": chain.get("chain_id") or name,
                            "score": chain.get("score"),
                            "company_count": chain.get("company_count"),
                        }
                    )
            return result

        return await self._safe_execute(_execute())

    async def screen_stocks(
        self,
        limit: int = 20,
        chain_name: str | None = None,
        industry: str | None = None,
        min_score: float | None = None,
        risk_tolerance: str | None = None,
    ) -> ToolResult:
        async def _execute():
            bounded_limit = max(1, min(int(limit or 20), 100))
            async with self._session_factory() as session:
                picks = await build_picks(session, limit=100)

            items = list(picks.get("items") or [])
            if chain_name:
                items = [item for item in items if chain_name in (item.get("chain_names") or [])]
            if industry:
                items = [item for item in items if item.get("industry") == industry]
            if min_score is not None:
                items = [item for item in items if (item.get("score") or 0) >= min_score]
            if risk_tolerance == "low":
                items = [item for item in items if not item.get("risk_flags")]

            gaps = self._screening_gaps(picks, items)
            return {
                "generated_at": picks.get("generated_at"),
                "filters": {
                    "chain_name": chain_name,
                    "industry": industry,
                    "min_score": min_score,
                    "risk_tolerance": risk_tolerance,
                },
                "items": items[:bounded_limit],
                "universe": picks.get("universe") or {},
                "methodology": picks.get("methodology"),
                "data_gaps": gaps,
                "confidence": "medium" if items else "low",
            }

        return await self._safe_execute(_execute())

    async def get_stock_snapshot(
        self,
        code: str,
        days: int = 120,
        periods: int = 8,
    ) -> ToolResult:
        async def _execute():
            normalized = normalize_stock_code(code)
            if not normalized:
                raise ValueError(f"Invalid stock code: {code}")

            async with self._session_factory() as session:
                stock = (
                    await session.execute(select(Stock).where(Stock.code == normalized))
                ).scalar_one_or_none()
                financial_rows = (
                    await session.execute(
                        select(FinancialReport)
                        .where(FinancialReport.code == normalized)
                        .order_by(desc(FinancialReport.report_date))
                        .limit(max(1, min(int(periods or 8), 20)))
                    )
                ).scalars().all()
                kline_rows = list(
                    reversed(
                        (
                            await session.execute(
                                select(DailyKline)
                                .where(DailyKline.code == normalized)
                                .order_by(desc(DailyKline.trade_date))
                                .limit(max(1, min(int(days or 120), 500)))
                            )
                        ).scalars().all()
                    )
                )
                signal_rows = (
                    await session.execute(
                        select(Signal)
                        .order_by(desc(Signal.trigger_date), desc(Signal.created_at))
                        .limit(500)
                    )
                ).scalars().all()

            _, chain_by_code = await chain_maps()
            signals = self._filter_signals_for_code(signal_rows, normalized)[:20]
            data_gaps = []
            if not stock:
                data_gaps.append("股票基础信息缺失")
            if not kline_rows:
                data_gaps.append("K线数据缺失")
            if not financial_rows:
                data_gaps.append("财报数据缺失")
            if not signals:
                data_gaps.append("近期信号缺失")

            return {
                "code": normalized,
                "stock": self._stock_payload(stock),
                "chain_exposure": chain_by_code.get(normalized, []),
                "metrics": kline_metrics(kline_rows),
                "latest_financial": financial_payload(financial_rows[0]) if financial_rows else None,
                "financial_history": [self._financial_row_payload(row) for row in financial_rows],
                "recent_signals": [self._signal_payload(row) for row in signals],
                "data_quality": {
                    "has_stock": stock is not None,
                    "has_graph": normalized in chain_by_code,
                    "has_kline": bool(kline_rows),
                    "has_financial": bool(financial_rows),
                    "has_signal": bool(signals),
                },
                "data_gaps": data_gaps,
                "confidence": "medium" if stock and (kline_rows or financial_rows or signals) else "low",
            }

        return await self._safe_execute(_execute())

    async def compare_stocks(self, codes: list[str], days: int = 120, periods: int = 8) -> ToolResult:
        async def _execute():
            snapshots = []
            errors = []
            for raw_code in codes:
                result = await self.get_stock_snapshot(raw_code, days=days, periods=periods)
                if result.success:
                    snapshots.append(result.data)
                else:
                    errors.append({"code": raw_code, "error": result.error})
            gaps = []
            for item in snapshots:
                for gap in item.get("data_gaps", []):
                    label = f"{item.get('code')}: {gap}"
                    if label not in gaps:
                        gaps.append(label)
            return {
                "items": snapshots,
                "errors": errors,
                "data_gaps": gaps,
                "confidence": "medium" if snapshots else "low",
            }

        return await self._safe_execute(_execute())

    async def search_stocks(self, keyword: str, limit: int = 20) -> ToolResult:
        async def _execute():
            text = str(keyword or "").strip()
            if not text:
                return []

            stmt = select(Stock).where(Stock.name.contains(text) | Stock.code.contains(text))
            stmt = stmt.limit(max(1, min(int(limit or 20), 100)))
            async with self._session_factory() as session:
                rows = (await session.execute(stmt)).scalars().all()
            return [self._stock_payload(row) for row in rows]

        return await self._safe_execute(_execute())

    @staticmethod
    def _screening_gaps(picks: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
        gaps = []
        universe = picks.get("universe") or {}
        candidate_count = universe.get("candidate_count") or 0
        kline_ratio = universe.get("candidate_kline_coverage_ratio")
        financial_ratio = universe.get("candidate_financial_coverage_ratio")
        if kline_ratio is None and candidate_count:
            kline_ratio = round((universe.get("kline_coverage") or 0) / candidate_count * 100, 1)
        if financial_ratio is None and candidate_count:
            financial_ratio = round((universe.get("financial_coverage") or 0) / candidate_count * 100, 1)
        if not items:
            gaps.append("没有找到符合条件且具备图谱或信号支撑的候选标的")
        if candidate_count == 0:
            gaps.append("候选池为空，需要先灌入知识图谱或产生入库信号")
        if candidate_count and (kline_ratio or 0) < 80:
            gaps.append("候选池K线覆盖不足，动量和回撤判断置信度偏低")
        if candidate_count and (financial_ratio or 0) < 80:
            gaps.append("候选池财报覆盖不足，基本面评分置信度偏低")
        return gaps

    @staticmethod
    def _stock_payload(stock: Stock | None) -> dict[str, Any] | None:
        if not stock:
            return None
        return {
            "code": stock.code,
            "name": stock.name,
            "industry": stock.industry,
            "market": stock.market,
            "market_cap": num(stock.market_cap),
            "is_st": stock.is_st,
        }

    @staticmethod
    def _financial_row_payload(row: FinancialReport) -> dict[str, Any]:
        return {
            "report_date": str(row.report_date) if row.report_date else None,
            "publish_date": str(row.publish_date) if row.publish_date else None,
            "revenue": num(row.revenue),
            "revenue_yoy": num(row.revenue_yoy),
            "net_profit": num(row.net_profit),
            "net_profit_yoy": num(row.net_profit_yoy),
            "gross_margin": num(row.gross_margin),
            "roe": num(row.roe),
            "pe_ratio": num(row.pe_ratio),
            "pb_ratio": num(row.pb_ratio),
            "source": row.source,
        }

    @staticmethod
    def _signal_payload(signal: Signal) -> dict[str, Any]:
        return {
            "signal_type": signal.signal_type,
            "chain_id": signal.chain_id,
            "source_entity": signal.source_entity,
            "target_codes": signal.target_codes,
            "strength": num(signal.strength),
            "confidence": num(signal.confidence),
            "detail": signal.detail,
            "trigger_date": str(signal.trigger_date) if signal.trigger_date else None,
            "source": signal.source,
        }

    @staticmethod
    def _filter_signals_for_code(signals: list[Signal], code: str) -> list[Signal]:
        matched = []
        for signal in signals:
            codes = _codes_from_signal_payload(signal.target_codes)
            source = normalize_stock_code(signal.source_entity)
            if source:
                codes.add(source)
            if code in codes:
                matched.append(signal)
        return matched
