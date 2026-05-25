"""选股业务服务层：统一数据查询、评分计算，供 API 路由与 Agent 工具共享。

所有依赖此服务的模块只需从 common.stock_service 导入，不再跨层引用 api.routes.*。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models import DailyKline, FinancialReport, Signal, Stock, StockMainFlow
from knowledge_graph.service import chain_topology_with_fallback, graph_chains_with_fallback

# ─── 基础工具函数 ────────────────────────────────────────────────────────────────


def num(value: Any) -> float | None:
    """安全转换为 float。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct(value: float | None) -> float | None:
    return round(value * 100, 2) if value is not None else None


def normalize_code(value: Any) -> str | None:
    """将各种格式的股票代码统一为 6 位纯数字字符串。"""
    text = str(value or "").strip().upper()
    if not text:
        return None
    if "." in text:
        text = text.split(".", 1)[0]
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    if not text.isdigit():
        return None
    return text.zfill(6)


def target_codes(value: Any) -> list[str]:
    """从信号 target_codes 字段（可能是 JSON 字符串、list、dict）中解析股票代码列表。"""
    if isinstance(value, str):
        try:
            return target_codes(json.loads(value))
        except json.JSONDecodeError:
            code = normalize_code(value)
            return [code] if code else []
    if isinstance(value, list):
        return [code for item in value if (code := normalize_code(item))]
    if isinstance(value, dict):
        codes: list[str] = []
        for item in value.values():
            codes.extend(target_codes(item))
        return codes
    return []


def signal_codes(signal: Signal) -> set[str]:
    """提取一个信号关联的所有股票代码（target_codes + source_entity + detail 中的 6 位数字）。"""
    codes = set(target_codes(signal.target_codes))
    source = normalize_code(signal.source_entity)
    if source:
        codes.add(source)
    if signal.detail:
        codes.update(match.group(0) for match in re.finditer(r"(?<!\d)\d{6}(?!\d)", signal.detail))
    return codes


# ─── 数据库查询 ──────────────────────────────────────────────────────────────────


async def stock_name_map(db: AsyncSession, codes: set[str]) -> dict[str, str]:
    """批量查询股票名称映射 {code: name}。"""
    if not codes:
        return {}
    try:
        rows = (await db.execute(select(Stock.code, Stock.name).where(Stock.code.in_(codes)))).all()
    except Exception:
        return {}
    return {str(code): str(name) for code, name in rows if code and name}


async def data_counts(db: AsyncSession) -> dict[str, Any]:
    """全库各表记录数和覆盖统计。"""
    stock_count = (await db.execute(select(func.count()).select_from(Stock))).scalar() or 0
    kline_count = (await db.execute(select(func.count()).select_from(DailyKline))).scalar() or 0
    kline_stocks = (await db.execute(select(func.count(distinct(DailyKline.code))))).scalar() or 0
    financial_count = (await db.execute(select(func.count()).select_from(FinancialReport))).scalar() or 0
    financial_stocks = (
        await db.execute(select(func.count(distinct(FinancialReport.code))))
    ).scalar() or 0
    signal_count = (await db.execute(select(func.count()).select_from(Signal))).scalar() or 0
    latest_kline = (await db.execute(select(func.max(DailyKline.trade_date)))).scalar()
    return {
        "stock_count": stock_count,
        "kline_count": kline_count,
        "kline_stock_coverage": kline_stocks,
        "financial_count": financial_count,
        "financial_stock_coverage": financial_stocks,
        "signal_count": signal_count,
        "latest_kline_date": str(latest_kline) if latest_kline else None,
    }


async def candidate_data_counts(db: AsyncSession) -> dict[str, Any]:
    """针对候选池（图谱+信号交集）的 K 线 / 财报覆盖率统计。"""
    _, chain_by_code = await chain_maps()
    signal_by_code, _ = await signal_maps(db)
    candidate_codes = set(chain_by_code) | set(signal_by_code)
    candidate_count = len(candidate_codes)
    if not candidate_codes:
        return {
            "candidate_count": 0,
            "candidate_kline_coverage": 0,
            "candidate_financial_coverage": 0,
            "candidate_kline_coverage_ratio": None,
            "candidate_financial_coverage_ratio": None,
        }

    kline_coverage = (
        await db.execute(
            select(func.count(distinct(DailyKline.code))).where(DailyKline.code.in_(candidate_codes))
        )
    ).scalar() or 0
    financial_coverage = (
        await db.execute(
            select(func.count(distinct(FinancialReport.code))).where(
                FinancialReport.code.in_(candidate_codes)
            )
        )
    ).scalar() or 0
    return {
        "candidate_count": candidate_count,
        "candidate_kline_coverage": kline_coverage,
        "candidate_financial_coverage": financial_coverage,
        "candidate_kline_coverage_ratio": round(kline_coverage / candidate_count * 100, 1),
        "candidate_financial_coverage_ratio": round(financial_coverage / candidate_count * 100, 1),
    }


async def chain_maps() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    """构建产业链映射：(chains_list, {code: [{chain, segment}]})。

    单次调用会遍历所有产业链拓扑，结果可在调用方缓存以避免重复查询。
    """
    chains = await graph_chains_with_fallback()
    code_map: dict[str, list[dict[str, str]]] = defaultdict(list)
    for chain in chains:
        chain_name = chain.get("name") or chain.get("chain_name") or chain.get("chain_id")
        if not chain_name:
            continue
        topology = await chain_topology_with_fallback(chain_name)
        for segment in (topology or {}).get("segments", []):
            segment_name = segment.get("segment_name") or segment.get("name") or ""
            for company in segment.get("companies", []):
                code = company.get("code")
                if code:
                    code_map[str(code)].append({"chain": chain_name, "segment": segment_name})
    return chains, code_map


async def latest_financials(db: AsyncSession, codes: set[str]) -> dict[str, FinancialReport]:
    """批量查询每只股票最新一期财报。"""
    if not codes:
        return {}
    rows = (
        await db.execute(
            select(FinancialReport)
            .where(FinancialReport.code.in_(codes))
            .order_by(FinancialReport.code, desc(FinancialReport.report_date))
        )
    ).scalars().all()
    result: dict[str, FinancialReport] = {}
    for row in rows:
        result.setdefault(row.code, row)
    return result


async def recent_klines(
    db: AsyncSession, codes: set[str], days: int = 90
) -> dict[str, list[DailyKline]]:
    """批量查询最近 N 天各股 K 线（按 code 分组）。"""
    if not codes:
        return {}
    latest_date = (await db.execute(select(func.max(DailyKline.trade_date)))).scalar()
    start_date = latest_date - timedelta(days=days) if latest_date else None
    stmt = select(DailyKline).where(DailyKline.code.in_(codes))
    if start_date:
        stmt = stmt.where(DailyKline.trade_date >= start_date)
    rows = (await db.execute(stmt.order_by(DailyKline.code, DailyKline.trade_date))).scalars().all()
    grouped: dict[str, list[DailyKline]] = defaultdict(list)
    for row in rows:
        grouped[row.code].append(row)
    return grouped


async def signal_maps(db: AsyncSession) -> tuple[dict[str, list[Signal]], list[Signal]]:
    """查询最近 300 条信号，构建 {code: [signals]} 映射。"""
    rows = (
        await db.execute(
            select(Signal)
            .order_by(desc(Signal.trigger_date), desc(Signal.created_at))
            .limit(300)
        )
    ).scalars().all()
    by_code: dict[str, list[Signal]] = defaultdict(list)
    for s in rows:
        codes = set(target_codes(s.target_codes))
        src = str(s.source_entity or "")
        if src.isdigit() and len(src) == 6:
            codes.add(src)
        for code in codes:
            by_code[code].append(s)
    return by_code, list(rows)


# ─── 纯计算函数 ──────────────────────────────────────────────────────────────────


def kline_metrics(rows: list[DailyKline]) -> dict[str, Any]:
    """从 K 线列表计算常用指标（涨跌幅、回撤、成交额均值等）。"""
    closes = [num(row.close) for row in rows if row.close is not None]
    amounts = [num(row.amount) for row in rows[-20:] if row.amount is not None]
    if not closes:
        return {
            "latest_close": None,
            "return_5d": None,
            "return_20d": None,
            "drawdown_60d": None,
            "avg_amount_20d": None,
            "latest_trade_date": None,
        }

    def period_return(period: int) -> float | None:
        if len(closes) <= period or closes[-period - 1] in (None, 0):
            return None
        return (closes[-1] - closes[-period - 1]) / closes[-period - 1]

    high_60 = max(closes[-60:]) if closes else None
    drawdown = (closes[-1] / high_60 - 1) if high_60 else None
    return {
        "latest_close": round(closes[-1], 3),
        "return_5d": pct(period_return(5)),
        "return_20d": pct(period_return(20)),
        "drawdown_60d": pct(drawdown),
        "avg_amount_20d": round(sum(amounts) / len(amounts), 2) if amounts else None,
        "latest_trade_date": str(rows[-1].trade_date) if rows else None,
    }


def score_level(score: float) -> str:
    if score >= 75:
        return "核心候选"
    if score >= 60:
        return "卫星候选"
    if score >= 45:
        return "观察候选"
    return "数据不足"


def financial_points(financial: FinancialReport | None) -> float:
    if not financial:
        return 0.0
    points = 0.0
    revenue_yoy = num(financial.revenue_yoy)
    profit_yoy = num(financial.net_profit_yoy)
    roe_val = num(financial.roe)
    margin = num(financial.gross_margin)
    if revenue_yoy and revenue_yoy > 0:
        points += min(8.0, revenue_yoy / 20)
    if profit_yoy and profit_yoy > 0:
        points += min(10.0, profit_yoy / 25)
    if roe_val and roe_val > 8:
        points += min(5.0, (roe_val - 8) / 4)
    if margin and margin > 20:
        points += min(4.0, (margin - 20) / 8)
    return points


def financial_payload(financial: FinancialReport | None) -> dict[str, Any] | None:
    if not financial:
        return None
    return {
        "report_date": str(financial.report_date) if financial.report_date else None,
        "publish_date": str(financial.publish_date) if financial.publish_date else None,
        "revenue_yoy": num(financial.revenue_yoy),
        "net_profit_yoy": num(financial.net_profit_yoy),
        "gross_margin": num(financial.gross_margin),
        "roe": num(financial.roe),
        "pe_ratio": num(financial.pe_ratio),
    }


def risk_flags(
    stock: Stock,
    financial: FinancialReport | None,
    klines: list[DailyKline],
    k_metrics: dict[str, Any],
) -> tuple[list[str], float]:
    flags: list[str] = []
    penalty = 0.0
    drawdown = k_metrics["drawdown_60d"]
    if stock.is_st:
        flags.append("ST")
        penalty += 30
    if drawdown is not None and drawdown < -20:
        flags.append("60日回撤超过20%")
        penalty += min(12, abs(drawdown) / 2)
    if not financial:
        flags.append("缺少财报覆盖")
        penalty += 4
    if not klines:
        flags.append("缺少K线覆盖")
        penalty += 8
    return flags, penalty


def score_stock(
    code: str,
    stock: Stock,
    chain_by_code: dict[str, list[dict[str, str]]],
    stock_signals: list[Signal],
    financial: FinancialReport | None,
    klines: list[DailyKline],
) -> dict[str, Any]:
    k_metrics = kline_metrics(klines)
    signal_points = min(
        42.0,
        sum((num(s.strength) or 0) * (num(s.confidence) or 0.5) * 18 for s in stock_signals),
    )
    ret5 = (k_metrics["return_5d"] or 0) / 100
    ret20 = (k_metrics["return_20d"] or 0) / 100
    momentum_points = max(0.0, min(22.0, ret5 * 120 + ret20 * 55))
    fp = financial_points(financial)
    data_points = 0.0
    if code in chain_by_code:
        data_points += 5
    if klines:
        data_points += 5
    if financial:
        data_points += 5
    if stock.market_cap:
        data_points += 3

    flags, penalty = risk_flags(stock, financial, klines, k_metrics)
    score = max(0.0, min(100.0, signal_points + momentum_points + fp + data_points - penalty))
    chain_names = sorted({item["chain"] for item in chain_by_code.get(code, [])})
    latest_signal = stock_signals[0] if stock_signals else None
    logic_parts = []
    if latest_signal:
        logic_parts.append(str(latest_signal.detail or latest_signal.signal_type))
    if k_metrics["return_5d"] is not None:
        logic_parts.append(f"近5日涨跌幅 {k_metrics['return_5d']}%")
    if financial and financial.net_profit_yoy is not None:
        logic_parts.append(f"最新净利同比 {num(financial.net_profit_yoy):.1f}%")
    if not logic_parts:
        logic_parts.append("仅有基础行情/图谱数据，需补充信号或财报后再提高置信度")

    return {
        "code": code,
        "name": stock.name,
        "industry": stock.industry,
        "market": stock.market,
        "market_cap": num(stock.market_cap),
        "chain_names": chain_names,
        "segments": sorted(
            {item["segment"] for item in chain_by_code.get(code, []) if item.get("segment")}
        ),
        "score": round(score, 2),
        "tier": score_level(score),
        "signal_count": len(stock_signals),
        "latest_signal": str(latest_signal.detail) if latest_signal else None,
        "metrics": k_metrics,
        "financial": financial_payload(financial),
        "risk_flags": flags,
        "logic": "；".join(logic_parts),
        "data_quality": {
            "has_graph": code in chain_by_code,
            "has_kline": bool(klines),
            "has_financial": financial is not None,
        },
    }


# ─── 主流程：构建候选池 ──────────────────────────────────────────────────────────


async def build_picks(db: AsyncSession, limit: int = 30) -> dict[str, Any]:
    """构建选股候选池，综合图谱归属、信号、K线动量和财报评分。"""
    chains, chain_by_code = await chain_maps()
    signal_by_code, signals = await signal_maps(db)
    graph_codes = set(chain_by_code)
    signal_codes_set = set(signal_by_code)
    candidate_codes = graph_codes | signal_codes_set
    stocks = {
        stock.code: stock
        for stock in (
            await db.execute(select(Stock).where(Stock.code.in_(candidate_codes)))
        ).scalars().all()
    }
    financials = await latest_financials(db, set(stocks))
    klines = await recent_klines(db, set(stocks))
    items = [
        score_stock(
            code=code,
            stock=stock,
            chain_by_code=chain_by_code,
            stock_signals=signal_by_code.get(code, []),
            financial=financials.get(code),
            klines=klines.get(code, []),
        )
        for code, stock in stocks.items()
    ]
    items.sort(key=lambda item: item["score"], reverse=True)

    counts = await data_counts(db)
    financial_coverage = sum(1 for code in stocks if financials.get(code))
    kline_coverage = sum(1 for code in stocks if klines.get(code))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "universe": {
            "candidate_count": len(stocks),
            "graph_chain_count": len(chains),
            "signal_count": len(signals),
            "kline_coverage": kline_coverage,
            "financial_coverage": financial_coverage,
            **counts,
        },
        "methodology": (
            "候选池仅来自真实图谱归属或已入库信号；"
            "K线动量、财报增长和数据覆盖度只参与评分，不单独生成候选；未使用模拟数据。"
        ),
        "items": items[:limit],
    }


async def query_main_flows(db: AsyncSession, codes: set[str], period: int) -> list:
    """查询窗口期内的主力资金流数据。"""
    latest_date = (await db.execute(select(func.max(StockMainFlow.trade_date)))).scalar()
    if not latest_date:
        return []
    start_date = latest_date - timedelta(days=period * 2 + 5)
    stmt = (
        select(StockMainFlow)
        .where(StockMainFlow.code.in_(codes), StockMainFlow.trade_date >= start_date)
        .order_by(StockMainFlow.trade_date)
    )
    return (await db.execute(stmt)).scalars().all()
