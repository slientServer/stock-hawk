"""个股完整分析 API：聚合真实入库数据，生成并保存分析结果。"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.llm_client import LLMClient
from api.deps import get_db, get_session_factory
from common.models import (
    DailyKline,
    FinancialReport,
    FundFlow,
    NewsEvent,
    Signal,
    Stock,
    StockAnalysisReport,
    StockMainFlow,
)
from data_collector.cache.redis_cache import RedisCache
from data_collector.sources.financial_report import FinancialReportCollector
from data_collector.sources.fund_flow import FundFlowCollector
from data_collector.sources.main_flow import MainFlowCollector
from data_collector.sources.market_basic import StockBasicCollector
from data_collector.sources.market_kline import KlineCollector
from data_collector.sources.market_realtime import RealtimeCollector
from data_collector.sources.news_crawler import NewsEventCollector
from data_collector.storage import DataStorage
from signal_engine import SignalEngine

router = APIRouter(prefix="/stock-analysis", tags=["个股分析"])
TASKS: dict[str, dict[str, Any]] = {}

SOURCE_POLICY = (
    "仅使用系统已入库的股票基础信息、K线、财报、主力资金、北向资金、新闻事件、信号数据，"
    "以及可获取的实时行情；缺失数据必须标注，不得补造。"
)

ACTION_LABELS = {
    "buy": "买入",
    "add": "加仓",
    "hold": "持有",
    "watch": "观察",
    "reduce": "减仓",
    "avoid": "回避",
}


def _append_unique(items: list[str], value: str | None) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _unique_texts(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        _append_unique(result, str(value) if value is not None else None)
    return result


class StockAnalysisRunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    lookback_days: int = Field(default=180, ge=30, le=500)
    use_llm: bool = True
    save: bool = True
    auto_collect: bool = True


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _set_task(task_id: str, **updates: Any) -> dict[str, Any]:
    task = TASKS.setdefault(
        task_id,
        {
            "task_id": task_id,
            "status": "queued",
            "progress": 0,
            "step": "排队中",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "result": None,
            "error_message": "",
        },
    )
    task.update(updates)
    task["updated_at"] = _now_iso()
    return task


def _task_payload(task: dict[str, Any]) -> dict[str, Any]:
    return dict(task)


def _normalize_code(value: Any) -> str | None:
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


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def _money_text(value: float | None) -> str:
    if value is None:
        return "缺失"
    if abs(value) >= 100000000:
        return f"{value / 100000000:.2f}亿"
    if abs(value) >= 10000:
        return f"{value / 10000:.2f}万"
    return f"{value:.2f}"


def _target_codes(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            return _target_codes(json.loads(value))
        except json.JSONDecodeError:
            code = _normalize_code(value)
            return [code] if code else []
    if isinstance(value, list):
        return [code for item in value if (code := _normalize_code(item))]
    if isinstance(value, dict):
        codes: list[str] = []
        for item in value.values():
            codes.extend(_target_codes(item))
        return codes
    return []


def _stock_payload(stock: Stock | None, code: str) -> dict[str, Any]:
    if not stock:
        return {"code": code, "name": None, "industry": None, "market": None, "market_cap": None, "is_st": None}
    return {
        "code": stock.code,
        "name": stock.name,
        "industry": stock.industry,
        "market": stock.market,
        "market_cap": _num(stock.market_cap),
        "is_st": stock.is_st,
    }


def _kline_payload(row: DailyKline) -> dict[str, Any]:
    return {
        "trade_date": str(row.trade_date) if row.trade_date else None,
        "open": _num(row.open),
        "close": _num(row.close),
        "high": _num(row.high),
        "low": _num(row.low),
        "volume": row.volume,
        "amount": _num(row.amount),
        "turnover_rate": _num(row.turnover_rate),
        "source": row.source,
    }


def _financial_payload(row: FinancialReport | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "report_date": str(row.report_date) if row.report_date else None,
        "publish_date": str(row.publish_date) if row.publish_date else None,
        "revenue": _num(row.revenue),
        "revenue_yoy": _num(row.revenue_yoy),
        "net_profit": _num(row.net_profit),
        "net_profit_yoy": _num(row.net_profit_yoy),
        "gross_margin": _num(row.gross_margin),
        "roe": _num(row.roe),
        "pe_ratio": _num(row.pe_ratio),
        "pb_ratio": _num(row.pb_ratio),
        "source": row.source,
    }


def _signal_matches_code(signal: Signal, code: str) -> bool:
    codes = set(_target_codes(signal.target_codes))
    source = _normalize_code(signal.source_entity)
    if source:
        codes.add(source)
    if signal.detail:
        codes.update(match.group(0) for match in re.finditer(r"(?<!\d)\d{6}(?!\d)", signal.detail))
    return code in codes


def _signal_payload(row: Signal) -> dict[str, Any]:
    return {
        "id": row.id,
        "signal_type": row.signal_type,
        "chain_id": row.chain_id,
        "source_entity": row.source_entity,
        "target_codes": row.target_codes,
        "strength": _num(row.strength),
        "confidence": _num(row.confidence),
        "detail": row.detail,
        "trigger_date": row.trigger_date.isoformat(timespec="seconds") if row.trigger_date else None,
        "source": row.source,
    }


def _period_return(closes: list[float], period: int) -> float | None:
    if len(closes) <= period or not closes[-period - 1]:
        return None
    return (closes[-1] / closes[-period - 1] - 1) * 100


def _kline_metrics(rows: list[DailyKline]) -> dict[str, Any]:
    closes = [_num(row.close) for row in rows if row.close is not None]
    closes = [value for value in closes if value is not None]
    if not closes:
        return {
            "latest_close": None,
            "latest_trade_date": None,
            "return_5d": None,
            "return_20d": None,
            "return_60d": None,
            "drawdown_60d": None,
            "ma5": None,
            "ma20": None,
            "ma60": None,
            "support_20": None,
            "resistance_20": None,
            "volume_ratio": None,
            "latest_turnover_rate": None,
            "avg_amount_20d": None,
        }

    def avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    highs = [_num(row.high) for row in rows[-20:] if row.high is not None]
    lows = [_num(row.low) for row in rows[-20:] if row.low is not None]
    volumes = [float(row.volume or 0) for row in rows if row.volume is not None]
    prev_volumes = volumes[-21:-1] if len(volumes) >= 21 else volumes[:-1]
    latest_volume = volumes[-1] if volumes else None
    avg_prev_volume = avg(prev_volumes)
    amounts = [_num(row.amount) for row in rows[-20:] if row.amount is not None]
    latest = rows[-1]
    high_60 = max(closes[-60:]) if closes else None
    drawdown = (closes[-1] / high_60 - 1) * 100 if high_60 else None
    return {
        "latest_close": _round(closes[-1], 3),
        "latest_trade_date": str(latest.trade_date) if latest.trade_date else None,
        "return_5d": _round(_period_return(closes, 5)),
        "return_20d": _round(_period_return(closes, 20)),
        "return_60d": _round(_period_return(closes, 60)),
        "drawdown_60d": _round(drawdown),
        "ma5": _round(avg(closes[-5:]), 3),
        "ma20": _round(avg(closes[-20:]), 3),
        "ma60": _round(avg(closes[-60:]), 3),
        "support_20": _round(min(lows), 3) if lows else None,
        "resistance_20": _round(max(highs), 3) if highs else None,
        "volume_ratio": _round(latest_volume / avg_prev_volume, 2) if latest_volume and avg_prev_volume else None,
        "latest_turnover_rate": _num(latest.turnover_rate),
        "avg_amount_20d": _round(sum(amounts) / len(amounts), 2) if amounts else None,
    }


def _stock_flow_payload(row: StockMainFlow) -> dict[str, Any]:
    return {
        "trade_date": str(row.trade_date) if row.trade_date else None,
        "main_net": _num(row.main_net),
        "main_buy": _num(row.main_buy),
        "main_sell": _num(row.main_sell),
        "retail_net": _num(row.retail_net),
        "main_net_pct": _num(row.main_net_pct),
        "source": row.source,
    }


def _stock_flow_summary(rows: list[StockMainFlow]) -> dict[str, Any]:
    if not rows:
        return {
            "latest_date": None,
            "latest_main_net": None,
            "latest_main_net_pct": None,
            "main_net_5d": None,
            "main_net_20d": None,
            "positive_days_20": 0,
            "trend": [],
        }
    nets = [_num(row.main_net) or 0 for row in rows]
    recent_20 = nets[-20:]
    return {
        "latest_date": str(rows[-1].trade_date) if rows[-1].trade_date else None,
        "latest_main_net": _round(_num(rows[-1].main_net)),
        "latest_main_net_pct": _round(_num(rows[-1].main_net_pct)),
        "main_net_5d": _round(sum(nets[-5:])),
        "main_net_20d": _round(sum(recent_20)),
        "positive_days_20": sum(1 for value in recent_20 if value > 0),
        "trend": [_stock_flow_payload(row) for row in rows[-20:]],
    }


def _fund_flow_payload(row: FundFlow) -> dict[str, Any]:
    return {
        "trade_date": str(row.trade_date) if row.trade_date else None,
        "north_buy": _num(row.north_buy),
        "north_sell": _num(row.north_sell),
        "north_net": _num(row.north_net),
        "source": row.source,
    }


def _market_flow_summary(rows: list[FundFlow]) -> dict[str, Any]:
    if not rows:
        return {
            "latest_date": None,
            "latest_valid_date": None,
            "north_net_latest": None,
            "north_net_5d": None,
            "north_net_20d": None,
            "valid_net_count": 0,
            "trend": [],
        }

    values = [_num(row.north_net) for row in rows]

    def sum_valid(items: list[float | None]) -> float | None:
        valid = [value for value in items if value is not None]
        return _round(sum(valid)) if valid else None

    latest_valid_date = None
    latest_valid_value = None
    for row, value in zip(reversed(rows), reversed(values), strict=False):
        if value is not None:
            latest_valid_date = str(row.trade_date) if row.trade_date else None
            latest_valid_value = value
            break

    return {
        "latest_date": str(rows[-1].trade_date) if rows[-1].trade_date else None,
        "latest_valid_date": latest_valid_date,
        "north_net_latest": _round(latest_valid_value),
        "north_net_5d": sum_valid(values[-5:]),
        "north_net_20d": sum_valid(values[-20:]),
        "valid_net_count": sum(1 for value in values if value is not None),
        "trend": [_fund_flow_payload(row) for row in rows[-20:]],
    }


async def _stored_quote(db: AsyncSession, code: str, kline_rows: list[DailyKline] | None = None) -> dict[str, Any] | None:
    rows = kline_rows
    if rows is None:
        rows = list(
            reversed(
                (
                    await db.execute(
                        select(DailyKline)
                        .where(DailyKline.code == code)
                        .order_by(desc(DailyKline.trade_date))
                        .limit(2)
                    )
                ).scalars().all()
            )
        )
    if not rows:
        return None
    latest = rows[-1]
    price = _num(latest.close)
    if not price:
        return None
    previous = _num(rows[-2].close) if len(rows) >= 2 else _num(latest.open)
    change_pct = (price / previous - 1) * 100 if previous else None
    return {
        "code": code,
        "price": _round(price, 3),
        "change_pct": _round(change_pct),
        "quote_time": str(latest.trade_date) if latest.trade_date else None,
        "quote_source": "daily_kline",
        "is_realtime": False,
    }


async def _quote_for_code(db: AsyncSession, code: str, kline_rows: list[DailyKline]) -> dict[str, Any] | None:
    collector = RealtimeCollector(RedisCache())
    try:
        rows = await collector.fetch_realtime([code])
    except Exception:
        rows = []
    finally:
        await collector.close()

    for row in rows:
        price = _num(row.get("price"))
        previous = _num(row.get("yesterday_close"))
        if str(row.get("code")) == code and price and price > 0:
            return {
                "code": code,
                "name": row.get("name"),
                "price": _round(price, 3),
                "change_pct": _round((price / previous - 1) * 100 if previous else None),
                "quote_time": row.get("timestamp"),
                "quote_source": row.get("source") or "realtime",
                "is_realtime": True,
            }
    return await _stored_quote(db, code, kline_rows)


def _event_codes(event: NewsEvent) -> set[str]:
    return set(_target_codes(event.related_codes))


def _event_text(event: NewsEvent) -> str:
    return f"{event.title or ''} {event.content or ''}"


def _event_matches_stock(event: NewsEvent, code: str, name: str | None) -> bool:
    text = _event_text(event)
    if code in _event_codes(event) or code in text:
        return True
    return bool(name and name in text)


def _event_matches_industry(event: NewsEvent, industry: str | None) -> bool:
    return bool(industry and industry in _event_text(event))


def _event_payload(event: NewsEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "content": (event.content or "")[:500] or None,
        "publish_time": event.publish_time.isoformat(timespec="seconds") if event.publish_time else None,
        "source": event.source,
        "related_codes": event.related_codes,
        "event_type": event.event_type,
        "sentiment": event.sentiment,
    }


def _result_record_count(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        for key in ("records_count", "signal_count", "records", "count", "total"):
            number = _num(value.get(key))
            if number is not None:
                return int(number)
    if hasattr(value, "records_count"):
        number = _num(getattr(value, "records_count"))
        if number is not None:
            return int(number)
    if hasattr(value, "signal_count"):
        number = _num(getattr(value, "signal_count"))
        if number is not None:
            return int(number)
    return 0


def _result_status(value: Any, records: int) -> str:
    status = getattr(value, "status", None)
    if status:
        return str(status)
    if isinstance(value, dict) and value.get("status"):
        return str(value["status"])
    return "completed" if records > 0 else "completed_empty"


def _result_detail(value: Any) -> str:
    if hasattr(value, "as_dict"):
        value = value.as_dict()
    if isinstance(value, dict):
        parts = []
        for key in ("status", "records_count", "codes_succeeded", "warnings", "errors", "blocking_issues"):
            item = value.get(key)
            if item:
                parts.append(f"{key}={item}")
        return "；".join(parts)[:500]
    return str(value)[:500]


async def _chain_names_for_code(code: str) -> list[str]:
    try:
        from knowledge_graph.neo4j_client import Neo4jClient

        client = await Neo4jClient.get_instance()
        rows = await client.run(
            """
            MATCH (company:Company {code: $code})-[r:BELONGS_TO]->(s:Segment)
            WHERE r._active IS NULL OR r._active = true
            RETURN DISTINCT s.chain_name AS name
            LIMIT 5
            """,
            code=code,
        )
    except Exception:
        return []
    names = []
    for row in rows:
        name = row.get("name")
        if name and name not in names:
            names.append(name)
    return names


async def _supplement_missing_stock_data(
    code: str,
    context: dict[str, Any],
    lookback_days: int,
    session_factory,
) -> dict[str, Any]:
    """Try to fill missing stock-analysis inputs from real collectors before scoring."""
    quality = context.get("data_quality") or {}
    needs_stock = not quality.get("has_stock")
    needs_quote_or_kline = not quality.get("has_quote") or not quality.get("has_kline")
    needs_financial = not quality.get("has_financial")
    needs_main_flow = not quality.get("has_main_flow")
    needs_market_flow = not quality.get("has_market_flow")
    needs_events = (
        not quality.get("has_news")
        or not quality.get("has_announcement_clues")
    )
    needs_signals = not quality.get("has_recent_signals")

    if not any([
        needs_stock,
        needs_quote_or_kline,
        needs_financial,
        needs_main_flow,
        needs_market_flow,
        needs_events,
        needs_signals,
    ]):
        return {"attempted": False, "steps": []}

    storage = DataStorage(session_factory)
    cache = RedisCache()
    await cache.connect()
    steps: list[dict[str, Any]] = []

    async def run_step(name: str, fn) -> None:
        try:
            value = await fn()
            records = _result_record_count(value)
            steps.append({
                "name": name,
                "status": _result_status(value, records),
                "records": records,
                "detail": _result_detail(value),
            })
        except Exception as e:
            steps.append({"name": name, "status": "failed", "records": 0, "error": str(e)[:500]})

    try:
        if needs_stock:
            await run_step("stock_basic", lambda: StockBasicCollector(storage).collect_stock_list())
            await run_step("stock_detail", lambda: StockBasicCollector(storage).collect_stock_detail([code]))
        if needs_quote_or_kline:
            start_date = date.today() - timedelta(days=max(lookback_days, 240))
            await run_step("kline", lambda: KlineCollector(storage, cache).collect_batch([code], start_date=start_date))
        if needs_financial:
            await run_step("financial_report", lambda: FinancialReportCollector(storage).collect_financial_report(code, years=3))
        if needs_main_flow:
            await run_step("stock_main_flow", lambda: MainFlowCollector(storage, cache).collect_single(code, days=45))
        if needs_market_flow:
            start_date = date.today() - timedelta(days=min(max(lookback_days, 90), 365))
            await run_step("north_flow", lambda: FundFlowCollector(storage, cache).collect_north_flow(start_date=start_date))
        if needs_events:
            news_collector = NewsEventCollector(storage)
            await run_step("stock_news", lambda: news_collector.collect_stock_news([code], limit_per_stock=20))
            if not quality.get("has_policy_events"):
                await run_step("market_news", lambda: news_collector.collect_latest_news(limit=100))
        if needs_signals:
            chain_names = await _chain_names_for_code(code)
            if chain_names:
                engine = SignalEngine(session_factory)
                for chain_name in chain_names[:3]:
                    await run_step(f"signal_scan:{chain_name}", lambda chain_name=chain_name: engine.scan_chain(chain_name))
            else:
                steps.append({
                    "name": "signal_scan",
                    "status": "skipped",
                    "records": 0,
                    "detail": "知识图谱中未找到该股票所属产业链，无法定向扫描信号",
                })
    finally:
        await cache.close()

    return {"attempted": True, "steps": steps}


async def _build_stock_context(db: AsyncSession, code: str, lookback_days: int) -> dict[str, Any]:
    started_at = datetime.now()
    stock = (await db.execute(select(Stock).where(Stock.code == code))).scalar_one_or_none()
    kline_rows = list(reversed((await db.execute(
        select(DailyKline).where(DailyKline.code == code).order_by(desc(DailyKline.trade_date)).limit(lookback_days)
    )).scalars().all()))
    financial_rows = (await db.execute(
        select(FinancialReport).where(FinancialReport.code == code).order_by(desc(FinancialReport.report_date)).limit(8)
    )).scalars().all()
    main_flow_rows = list(reversed((await db.execute(
        select(StockMainFlow).where(StockMainFlow.code == code).order_by(desc(StockMainFlow.trade_date)).limit(30)
    )).scalars().all()))
    fund_flow_rows = list(reversed((await db.execute(
        select(FundFlow).order_by(desc(FundFlow.trade_date)).limit(30)
    )).scalars().all()))
    signal_rows = (await db.execute(
        select(Signal).order_by(desc(Signal.trigger_date), desc(Signal.created_at)).limit(500)
    )).scalars().all()
    event_rows = (await db.execute(
        select(NewsEvent)
        .where(NewsEvent.publish_time >= started_at - timedelta(days=lookback_days))
        .order_by(desc(NewsEvent.publish_time))
        .limit(600)
    )).scalars().all()

    stock_payload = _stock_payload(stock, code)
    name = stock_payload.get("name")
    industry = stock_payload.get("industry")
    matched_events = [row for row in event_rows if _event_matches_stock(row, code, name)]
    policy_events = [
        row for row in event_rows
        if row.event_type == "policy" and (_event_matches_stock(row, code, name) or _event_matches_industry(row, industry))
    ]
    announcement_events = [
        row for row in matched_events
        if row.event_type in {"earnings", "capital", "personnel"} or any(word in _event_text(row) for word in ["公告", "披露", "预告", "年报", "季报"])
    ]
    recent_signals = [row for row in signal_rows if _signal_matches_code(row, code)][:20]
    quote = await _quote_for_code(db, code, kline_rows)
    metrics = _kline_metrics(kline_rows)

    data_gaps: list[str] = []
    data_notes: list[str] = []
    source_limits: list[str] = []
    if not stock:
        _append_unique(data_gaps, "股票基础信息缺失")
    if not quote:
        _append_unique(data_gaps, "实时行情和入库收盘价均缺失")
    elif not quote.get("is_realtime"):
        _append_unique(data_notes, "实时行情不可用，使用最新入库K线收盘价")
    if not kline_rows:
        _append_unique(data_gaps, "K线数据缺失")
    if not financial_rows:
        _append_unique(data_gaps, "财报数据缺失")
    if not main_flow_rows:
        _append_unique(data_gaps, "个股主力资金流缺失")
    if not fund_flow_rows:
        _append_unique(data_notes, "市场北向资金流记录缺失")
    elif not any(_num(row.north_net) is not None for row in fund_flow_rows):
        _append_unique(data_notes, "北向资金净买额字段缺失，数据源披露口径调整后仅保留日期记录")
    if not event_rows:
        _append_unique(data_notes, f"近{lookback_days}天新闻事件源无入库记录")
    elif not matched_events:
        _append_unique(data_notes, f"近{lookback_days}天未匹配到该股资讯")
    _append_unique(source_limits, "系统当前未接入结构化公告源，公告仅使用新闻事件中的公告线索")
    if event_rows and not announcement_events:
        _append_unique(data_notes, f"近{lookback_days}天未匹配到该股公告线索")
    if event_rows and not policy_events:
        _append_unique(data_notes, f"近{lookback_days}天未匹配到该股或所属行业政策事件")
    if not signal_rows:
        _append_unique(data_notes, "近期信号源无入库记录")
    elif not recent_signals:
        _append_unique(data_notes, "近期信号未覆盖该股票")

    news_payload = [_event_payload(row) for row in matched_events[:30]]
    policy_payload = [_event_payload(row) for row in policy_events[:20]]
    announcement_payload = [_event_payload(row) for row in announcement_events[:20]]
    sentiment_counts = Counter(row.sentiment or "unknown" for row in matched_events)
    flow_summary = _stock_flow_summary(main_flow_rows)
    market_flow = _market_flow_summary(fund_flow_rows)
    market_heat = _market_heat(metrics, flow_summary, news_payload, policy_payload, recent_signals)
    data_quality = {
        "has_stock": stock is not None,
        "has_quote": quote is not None,
        "has_realtime_quote": bool(quote and quote.get("is_realtime")),
        "has_kline": bool(kline_rows),
        "has_financial": bool(financial_rows),
        "has_main_flow": bool(main_flow_rows),
        "has_market_flow": bool(fund_flow_rows),
        "has_market_flow_net": bool(market_flow.get("valid_net_count")),
        "has_news": bool(matched_events),
        "has_announcement_clues": bool(announcement_events),
        "has_policy_events": bool(policy_events),
        "has_recent_signals": bool(recent_signals),
    }

    return {
        "generated_at": started_at.isoformat(timespec="seconds"),
        "code": code,
        "stock": stock_payload,
        "quote": quote,
        "kline_metrics": metrics,
        "kline": [_kline_payload(row) for row in kline_rows[-120:]],
        "latest_financial": _financial_payload(financial_rows[0]) if financial_rows else None,
        "financial_history": [_financial_payload(row) for row in financial_rows],
        "stock_flow": flow_summary,
        "market_flow": market_flow,
        "market_heat": market_heat,
        "news": news_payload,
        "announcements": announcement_payload,
        "policies": policy_payload,
        "recent_signals": [_signal_payload(row) for row in recent_signals],
        "sentiment_counts": dict(sentiment_counts),
        "data_gaps": data_gaps,
        "data_notes": data_notes,
        "source_limits": source_limits,
        "data_quality": data_quality,
        "source_policy": SOURCE_POLICY,
    }


async def _prepare_stock_context(
    db: AsyncSession,
    code: str,
    lookback_days: int,
    session_factory,
    auto_collect: bool,
) -> dict[str, Any]:
    context = await _build_stock_context(db, code, lookback_days)
    if not auto_collect:
        return context

    collection = await _supplement_missing_stock_data(code, context, lookback_days, session_factory)
    if not collection.get("attempted"):
        context["collection_attempts"] = collection
        return context

    await db.rollback()
    refreshed = await _build_stock_context(db, code, lookback_days)
    refreshed["collection_attempts"] = collection
    refreshed_notes = refreshed.setdefault("data_notes", [])
    completed = [step for step in collection.get("steps", []) if step.get("status") in {"completed", "completed_empty"}]
    failed = [step for step in collection.get("steps", []) if step.get("status") == "failed"]
    if completed:
        _append_unique(refreshed_notes, f"已自动补采 {len(completed)} 类数据源，随后重新生成分析")
    if failed:
        _append_unique(refreshed_notes, f"{len(failed)} 类数据源补采失败，详见 metadata.collection_attempts")
    return refreshed


def _market_heat(
    metrics: dict[str, Any],
    flow: dict[str, Any],
    news: list[dict[str, Any]],
    policies: list[dict[str, Any]],
    signals: list[Signal],
) -> dict[str, Any]:
    sentiment = Counter(item.get("sentiment") or "unknown" for item in news)
    score = 50.0
    ret5 = metrics.get("return_5d") or 0
    ret20 = metrics.get("return_20d") or 0
    volume_ratio = metrics.get("volume_ratio")
    turnover = metrics.get("latest_turnover_rate")
    if volume_ratio is not None:
        score += _clamp((volume_ratio - 1) * 18, -12, 18)
    if turnover is not None:
        score += _clamp(turnover * 1.5, 0, 12)
    score += _clamp(ret5 * 0.9, -15, 15) + _clamp(ret20 * 0.35, -12, 12)
    score += min(sentiment.get("positive", 0) * 4, 12)
    score -= min(sentiment.get("negative", 0) * 5, 18)
    score += min(len(signals) * 2, 10)
    score += min(len(policies) * 1.5, 6)
    score += _clamp((flow.get("main_net_5d") or 0) / 10000000, -8, 8)
    score = _round(_clamp(score), 1)
    level = "low" if (score or 0) < 45 else "high" if (score or 0) >= 70 else "neutral"
    return {
        "score": score,
        "level": level,
        "news_count": len(news),
        "policy_count": len(policies),
        "signal_count": len(signals),
        "sentiment_counts": dict(sentiment),
        "volume_ratio": volume_ratio,
        "turnover_rate": turnover,
    }


def _score_technical(metrics: dict[str, Any]) -> float:
    close = metrics.get("latest_close")
    ma20 = metrics.get("ma20")
    ma60 = metrics.get("ma60")
    score = 50 + (metrics.get("return_20d") or 0) * 0.8 + (metrics.get("return_5d") or 0) * 0.6
    if close and ma20:
        score += 10 if close >= ma20 else -12
    if ma20 and ma60:
        score += 8 if ma20 >= ma60 else -8
    if metrics.get("drawdown_60d") is not None and metrics["drawdown_60d"] < -18:
        score -= 10
    if metrics.get("volume_ratio") and metrics["volume_ratio"] >= 1.3:
        score += 6
    return _clamp(score)


def _score_flow(flow: dict[str, Any], market_flow: dict[str, Any]) -> float:
    score = 50.0
    main_5d = flow.get("main_net_5d")
    main_20d = flow.get("main_net_20d")
    if main_5d is not None:
        score += _clamp(main_5d / 8000000, -18, 18)
    if main_20d is not None:
        score += _clamp(main_20d / 30000000, -12, 12)
    score += (flow.get("positive_days_20") or 0) * 0.7
    north_5d = market_flow.get("north_net_5d")
    if north_5d is not None:
        score += _clamp(north_5d / 500000000, -8, 8)
    return _clamp(score)


def _score_fundamental(financial: dict[str, Any] | None) -> float:
    if not financial:
        return 45.0
    score = 50.0
    revenue_yoy = financial.get("revenue_yoy")
    profit_yoy = financial.get("net_profit_yoy")
    gross_margin = financial.get("gross_margin")
    roe = financial.get("roe")
    if revenue_yoy is not None:
        score += _clamp(revenue_yoy * 0.25, -10, 12)
    if profit_yoy is not None:
        score += _clamp(profit_yoy * 0.22, -14, 16)
    if gross_margin is not None:
        score += _clamp((gross_margin - 20) * 0.25, -6, 8)
    if roe is not None:
        score += _clamp((roe - 5) * 0.4, -6, 8)
    return _clamp(score)


def _score_event(context: dict[str, Any]) -> float:
    sentiment = Counter(item.get("sentiment") or "unknown" for item in context.get("news") or [])
    score = 50.0
    score += min(sentiment.get("positive", 0) * 5, 18)
    score -= min(sentiment.get("negative", 0) * 7, 24)
    score += min(len(context.get("policies") or []) * 2, 8)
    score += min(len(context.get("announcements") or []) * 2, 8)
    score += min(len(context.get("recent_signals") or []) * 2.5, 12)
    return _clamp(score)


def _operation_advice(action: str, price: float | None, metrics: dict[str, Any], confidence: str) -> dict[str, Any]:
    if price is None:
        return {
            "primary": "缺少可核验价格，不给出买卖区间；先补采实时行情或K线。",
            "entry_zone": None,
            "target_price": None,
            "stop_loss": None,
            "max_position_pct": 0,
            "time_horizon": "数据补齐后复核",
            "add_condition": "补齐价格、K线和资金流后再判断",
            "reduce_condition": "已有持仓时以手工风控线为准",
            "invalidation": "核心行情数据缺失",
        }
    support = metrics.get("support_20")
    resistance = metrics.get("resistance_20")
    stop_loss = max(price * 0.92, support * 0.98) if support else price * 0.92
    target = max(price * 1.1, resistance * 1.02) if resistance else price * 1.1
    max_position = 10 if confidence == "low" else 20 if confidence == "medium" else 30
    if action in {"reduce", "avoid"}:
        max_position = 0 if action == "avoid" else min(max_position, 10)
    entry_zone = [_round(price * 0.98, 2), _round(price * 1.01, 2)] if action in {"buy", "add"} else None
    label = ACTION_LABELS.get(action, action)
    return {
        "primary": f"{label}；以{_round(price, 2)}为当前参考价，按触发条件执行，不追高扩大仓位。",
        "entry_zone": entry_zone,
        "target_price": _round(target, 2),
        "stop_loss": _round(stop_loss, 2),
        "max_position_pct": max_position,
        "time_horizon": "1-4周",
        "add_condition": f"收盘价站上MA20({metrics.get('ma20') or '-'})且5日主力资金继续净流入",
        "reduce_condition": f"跌破止损价{_round(stop_loss, 2)}或主力资金连续3日净流出",
        "invalidation": "收盘价跌破MA20且资讯/公告出现负面证伪，或最新财报增长转弱",
    }


def _confidence(context: dict[str, Any], score: float) -> str:
    gaps = context.get("data_gaps") or []
    has_core = bool((context.get("quote") or {}).get("price")) and bool((context.get("kline_metrics") or {}).get("latest_close"))
    if not has_core or len(gaps) >= 5:
        return "low"
    if score >= 70 and len(gaps) <= 2:
        return "high"
    return "medium"


def _normalize_confidence_value(value: Any, fallback: str = "low") -> str:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"high", "medium", "low"}:
            return text
        if text in {"高", "强"}:
            return "high"
        if text in {"中", "中等"}:
            return "medium"
        if text in {"低", "弱"}:
            return "low"
    number = _num(value)
    if number is not None:
        if number > 1:
            number = number / 100
        if number >= 0.75:
            return "high"
        if number >= 0.4:
            return "medium"
        return "low"
    return fallback if fallback in {"high", "medium", "low"} else "low"


def _action_from_scores(total: float, tech_score: float, flow_score: float, price: float | None, metrics: dict[str, Any]) -> str:
    if not price or not metrics.get("latest_close"):
        return "watch"
    if total >= 74 and tech_score >= 63 and flow_score >= 58:
        return "buy"
    if total >= 66 and flow_score >= 55:
        return "hold"
    if total <= 42 or (tech_score < 42 and flow_score < 45):
        return "reduce"
    if total < 35:
        return "avoid"
    return "watch"


def _analysis_sections(
    context: dict[str, Any],
    price: float | None,
    metrics: dict[str, Any],
    flow: dict[str, Any],
    market_flow: dict[str, Any],
    heat_score: float,
) -> dict[str, Any]:
    heat = context.get("market_heat") or {}
    return {
        "price_kline": {
            "view": f"最新价{price or '缺失'}，5日涨跌{metrics.get('return_5d')}%，20日涨跌{metrics.get('return_20d')}%。",
            "evidence": [
                f"MA20={metrics.get('ma20')}, MA60={metrics.get('ma60')}",
                f"20日支撑={metrics.get('support_20')}, 压力={metrics.get('resistance_20')}",
                f"量比={metrics.get('volume_ratio')}, 换手率={metrics.get('latest_turnover_rate')}",
            ],
        },
        "fund_flow": {
            "view": f"近5日主力净流入{_money_text(flow.get('main_net_5d'))}，近20日{_money_text(flow.get('main_net_20d'))}。",
            "evidence": [
                f"最新主力净流入={_money_text(flow.get('latest_main_net'))}",
                f"20日净流入天数={flow.get('positive_days_20')}",
                f"北向近5日净流入={_money_text(market_flow.get('north_net_5d'))}",
            ],
        },
        "market_heat": {
            "view": f"热度{heat.get('level')}，热度分{heat_score}。",
            "evidence": [
                f"资讯{len(context.get('news') or [])}条，公告线索{len(context.get('announcements') or [])}条，政策{len(context.get('policies') or [])}条",
                f"近期信号{len(context.get('recent_signals') or [])}个",
            ],
        },
        "news": {
            "view": "近期资讯按入库新闻事件聚合。",
            "evidence": [item.get("title") for item in (context.get("news") or [])[:5]],
        },
        "announcements": {
            "view": "公告以结构化公告源或新闻事件中的公告线索为依据。",
            "evidence": [item.get("title") for item in (context.get("announcements") or [])[:5]],
        },
        "policy": {
            "view": "政策以个股、公司名或行业关键词匹配。",
            "evidence": [item.get("title") for item in (context.get("policies") or [])[:5]],
        },
        "financial": {
            "view": "最新财报用于校验盈利质量和估值。",
            "evidence": [json.dumps(context.get("latest_financial") or {}, ensure_ascii=False)],
        },
    }


def _rule_analysis(context: dict[str, Any]) -> dict[str, Any]:
    metrics = context.get("kline_metrics") or {}
    flow = context.get("stock_flow") or {}
    market_flow = context.get("market_flow") or {}
    tech_score = _score_technical(metrics)
    flow_score = _score_flow(flow, market_flow)
    event_score = _score_event(context)
    fundamental_score = _score_fundamental(context.get("latest_financial"))
    heat_score = (context.get("market_heat") or {}).get("score") or 50
    gap_penalty = min(len(context.get("data_gaps") or []) * 3, 18)
    total = _round(_clamp(
        tech_score * 0.32
        + flow_score * 0.23
        + heat_score * 0.15
        + event_score * 0.15
        + fundamental_score * 0.15
        - gap_penalty
    ), 1) or 0
    price = (context.get("quote") or {}).get("price") or metrics.get("latest_close")
    action = _action_from_scores(total, tech_score, flow_score, price, metrics)
    confidence = _confidence(context, total)
    if confidence == "low" and action in {"buy", "add"}:
        action = "watch"

    stock = context.get("stock") or {}
    name = stock.get("name") or context.get("code")
    summary = (
        f"{name}({context.get('code')}) 综合评分{total}，建议{ACTION_LABELS.get(action, action)}。"
        f"技术分{_round(tech_score, 1)}，资金分{_round(flow_score, 1)}，市场热度{heat_score}。"
    )
    sections = _analysis_sections(context, price, metrics, flow, market_flow, heat_score)
    return {
        "summary": summary,
        "action": action,
        "action_label": ACTION_LABELS.get(action, action),
        "confidence": confidence,
        "score": total,
        "scores": {
            "technical": _round(tech_score, 1),
            "fund_flow": _round(flow_score, 1),
            "market_heat": heat_score,
            "event": _round(event_score, 1),
            "fundamental": _round(fundamental_score, 1),
        },
        "operation_advice": _operation_advice(action, price, metrics, confidence),
        "sections": sections,
        "risks": [
            "主力资金连续净流出会削弱短线胜率",
            "跌破MA20或20日支撑位后需要降低仓位",
            "公告、政策或财报出现负面变化会证伪当前逻辑",
        ],
        "data_gaps": context.get("data_gaps") or [],
        "data_notes": context.get("data_notes") or [],
        "source_limits": context.get("source_limits") or [],
        "data_quality": context.get("data_quality") or {},
        "source_policy": SOURCE_POLICY,
    }


def _llm_prompt() -> str:
    return (
        "你是个股分析Agent。只能基于用户JSON里的真实数据分析，禁止补造资讯、公告、政策、价格或资金流。"
        "请输出严格JSON，字段包括summary, action, confidence, score, scores, operation_advice, sections, risks, data_gaps。"
        "action只能是buy/add/hold/watch/reduce/avoid之一。operation_advice必须包含primary, entry_zone, "
        "target_price, stop_loss, max_position_pct, time_horizon, add_condition, reduce_condition, invalidation。"
        "sections至少包含price_kline, fund_flow, market_heat, news, announcements, policy, financial，每个section包含view和evidence。"
        "data_gaps 必须原样使用用户JSON中的 data_gaps，不允许自行新增、改写、翻译或重复；"
        "data_notes 和 source_limits 可在正文或对应 section 中说明。"
    )


def _merge_analysis(base: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key in ["summary", "confidence", "score", "scores", "operation_advice", "sections", "risks"]:
        if raw.get(key) not in (None, "", [], {}):
            result[key] = _normalize_confidence_value(raw[key], result.get("confidence", "low")) if key == "confidence" else raw[key]
    action = raw.get("action")
    if action in ACTION_LABELS:
        result["action"] = action
        result["action_label"] = ACTION_LABELS[action]
    result["data_gaps"] = _unique_texts(list(base.get("data_gaps") or []))
    result["data_notes"] = _unique_texts(list(base.get("data_notes") or []))
    result["source_limits"] = _unique_texts(list(base.get("source_limits") or []))
    result["data_quality"] = base.get("data_quality") or {}
    result["source_policy"] = SOURCE_POLICY
    return result


async def _generate_analysis(context: dict[str, Any], use_llm: bool) -> tuple[dict[str, Any], bool, str | None]:
    base = _rule_analysis(context)
    if not use_llm:
        return base, False, None
    llm = LLMClient()
    try:
        if not llm.is_available():
            return base, False, None
        raw = await llm.chat_json(
            [
                {"role": "system", "content": _llm_prompt()},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
            ],
            temperature=0.2,
            max_tokens=3000,
        )
        return _merge_analysis(base, raw), True, None
    except Exception as e:
        degraded = dict(base)
        gaps = list(degraded.get("data_gaps") or [])
        _append_unique(gaps, f"LLM分析失败，已使用规则化分析: {e}")
        degraded["data_gaps"] = gaps
        return degraded, False, str(e)
    finally:
        await llm.close()


async def _finalize_analysis(
    db: AsyncSession,
    normalized: str,
    context: dict[str, Any],
    analysis: dict[str, Any],
    llm_used: bool,
    task_id: str,
    started: float,
    save: bool,
) -> dict[str, Any]:
    quote = context.get("quote") or {}
    metrics = context.get("kline_metrics") or {}
    latest_trade_date = metrics.get("latest_trade_date")
    latest_date = datetime.fromisoformat(latest_trade_date).date() if latest_trade_date else None
    operation = analysis.get("operation_advice") or {}
    confidence = _normalize_confidence_value(analysis.get("confidence"), "low")
    analysis["confidence"] = confidence
    analysis["data_gaps"] = _unique_texts(list(analysis.get("data_gaps") or context.get("data_gaps") or []))
    analysis["data_notes"] = _unique_texts(list(analysis.get("data_notes") or context.get("data_notes") or []))
    analysis["source_limits"] = _unique_texts(list(analysis.get("source_limits") or context.get("source_limits") or []))
    analysis["data_quality"] = analysis.get("data_quality") or context.get("data_quality") or {}
    analysis["metadata"] = {
        "execution_time_ms": int((time.time() - started) * 1000),
        "llm_used": llm_used,
        "task_id": task_id,
    }
    if context.get("collection_attempts"):
        analysis["metadata"]["collection_attempts"] = context["collection_attempts"]

    if not save:
        return {
            "id": None,
            "code": normalized,
            "name": (context.get("stock") or {}).get("name"),
            "analysis_time": context.get("generated_at"),
            "latest_trade_date": latest_trade_date,
            "current_price": quote.get("price"),
            "action": analysis.get("action"),
            "action_label": ACTION_LABELS.get(analysis.get("action") or "", analysis.get("action")),
            "confidence": confidence,
            "score": analysis.get("score"),
            "time_horizon": operation.get("time_horizon"),
            "summary": analysis.get("summary"),
            "result": analysis,
            "input_snapshot": context,
            "data_gaps": analysis.get("data_gaps") or context.get("data_gaps") or [],
            "data_notes": analysis.get("data_notes") or context.get("data_notes") or [],
            "source_limits": analysis.get("source_limits") or context.get("source_limits") or [],
            "source_policy": SOURCE_POLICY,
            "llm_used": llm_used,
            "task_id": task_id,
        }

    row = StockAnalysisReport(
        code=normalized,
        name=(context.get("stock") or {}).get("name"),
        latest_trade_date=latest_date,
        current_price=_dec(quote.get("price")),
        action=analysis.get("action"),
        confidence=confidence,
        score=_dec(analysis.get("score")),
        time_horizon=operation.get("time_horizon"),
        summary=analysis.get("summary"),
        analysis_result=analysis,
        input_snapshot=context,
        data_gaps=analysis.get("data_gaps") or context.get("data_gaps") or [],
        source_policy=SOURCE_POLICY,
        llm_used=llm_used,
        task_id=task_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _report_payload(row)


def _report_payload(row: StockAnalysisReport) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "analysis_time": row.analysis_time.isoformat(timespec="seconds") if row.analysis_time else None,
        "latest_trade_date": str(row.latest_trade_date) if row.latest_trade_date else None,
        "current_price": _num(row.current_price),
        "action": row.action,
        "action_label": ACTION_LABELS.get(row.action or "", row.action),
        "confidence": row.confidence,
        "score": _num(row.score),
        "time_horizon": row.time_horizon,
        "summary": row.summary,
        "result": row.analysis_result or {},
        "input_snapshot": row.input_snapshot or {},
        "data_gaps": row.data_gaps or [],
        "data_notes": (row.analysis_result or {}).get("data_notes") or (row.input_snapshot or {}).get("data_notes") or [],
        "source_limits": (row.analysis_result or {}).get("source_limits") or (row.input_snapshot or {}).get("source_limits") or [],
        "source_policy": row.source_policy,
        "llm_used": bool(row.llm_used),
        "task_id": row.task_id,
    }


async def _run_analysis_task(task_id: str, params: dict[str, Any], session_factory) -> None:
    started = time.time()
    normalized = _normalize_code(params.get("code"))
    if not normalized:
        _set_task(task_id, status="failed", progress=100, step="股票代码无效", error_message="股票代码无效")
        return

    try:
        _set_task(task_id, status="running", progress=8, step="校验股票代码", code=normalized)
        async with session_factory() as db:
            stock = (await db.execute(select(Stock).where(Stock.code == normalized))).scalar_one_or_none()
            _set_task(
                task_id,
                progress=16,
                step="读取行情、K线、资金、资讯和政策数据",
                code=normalized,
                name=stock.name if stock else None,
            )
            context = await _prepare_stock_context(
                db,
                normalized,
                int(params.get("lookback_days") or 180),
                session_factory,
                bool(params.get("auto_collect", True)),
            )
            if not context.get("quote") and not context.get("kline") and not (context.get("stock") or {}).get("name"):
                raise ValueError("该股票缺少可分析的入库数据")

            _set_task(task_id, progress=48, step="完成数据聚合，计算规则化评分")
            _set_task(task_id, progress=62, step="调用LLM生成综合分析" if params.get("use_llm", True) else "生成规则化综合分析")
            analysis, llm_used, llm_error = await _generate_analysis(context, bool(params.get("use_llm", True)))
            if llm_error:
                analysis["llm_error"] = llm_error

            _set_task(task_id, progress=86, step="保存分析结果")
            result = await _finalize_analysis(
                db=db,
                normalized=normalized,
                context=context,
                analysis=analysis,
                llm_used=llm_used,
                task_id=task_id,
                started=started,
                save=bool(params.get("save", True)),
            )
            _set_task(
                task_id,
                status="completed",
                progress=100,
                step="分析完成",
                code=normalized,
                name=result.get("name") or (context.get("stock") or {}).get("name"),
                result=result,
                report_id=result.get("id"),
                action=result.get("action"),
                action_label=result.get("action_label"),
                confidence=result.get("confidence"),
                score=result.get("score"),
            )
    except Exception as e:
        _set_task(task_id, status="failed", progress=100, step="分析失败", error_message=str(e), code=normalized)


@router.post("/tasks")
async def create_stock_analysis_task(
    req: StockAnalysisRunRequest,
    background_tasks: BackgroundTasks,
    session_factory=Depends(get_session_factory),
):
    normalized = _normalize_code(req.code)
    if not normalized:
        raise HTTPException(status_code=400, detail="股票代码无效")
    task_id = f"stock_full_analysis_{uuid.uuid4().hex[:8]}"
    task = _set_task(
        task_id,
        code=normalized,
        status="queued",
        progress=0,
        step="任务已创建",
        use_llm=req.use_llm,
        save=req.save,
    )
    background_tasks.add_task(_run_analysis_task, task_id, {**req.model_dump(), "code": normalized}, session_factory)
    return _task_payload(task)


@router.get("/tasks")
async def stock_analysis_tasks(limit: int = Query(default=30, ge=1, le=100)):
    rows = sorted(TASKS.values(), key=lambda item: item.get("created_at") or "", reverse=True)
    return [_task_payload(row) for row in rows[:limit]]


@router.get("/tasks/{task_id}")
async def stock_analysis_task(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启")
    return _task_payload(task)


@router.get("/history")
async def stock_analysis_history(
    code: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(StockAnalysisReport).order_by(desc(StockAnalysisReport.analysis_time), desc(StockAnalysisReport.id)).limit(limit)
    normalized = _normalize_code(code) if code else None
    if normalized:
        stmt = stmt.where(StockAnalysisReport.code == normalized)
    rows = (await db.execute(stmt)).scalars().all()
    return [_report_payload(row) for row in rows]


@router.get("/latest/{code}")
async def latest_stock_analysis(code: str, db: AsyncSession = Depends(get_db)):
    normalized = _normalize_code(code)
    if not normalized:
        raise HTTPException(status_code=400, detail="股票代码无效")
    row = (
        await db.execute(
            select(StockAnalysisReport)
            .where(StockAnalysisReport.code == normalized)
            .order_by(desc(StockAnalysisReport.analysis_time), desc(StockAnalysisReport.id))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="暂无分析记录")
    return _report_payload(row)


@router.get("/reports/{report_id}")
async def stock_analysis_report(report_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(StockAnalysisReport).where(StockAnalysisReport.id == report_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    return _report_payload(row)


@router.post("/run")
async def run_stock_analysis(
    req: StockAnalysisRunRequest,
    db: AsyncSession = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    normalized = _normalize_code(req.code)
    if not normalized:
        raise HTTPException(status_code=400, detail="股票代码无效")
    started = time.time()
    task_id = f"stock_full_analysis_{uuid.uuid4().hex[:8]}"
    context = await _prepare_stock_context(db, normalized, req.lookback_days, session_factory, req.auto_collect)
    if not context.get("quote") and not context.get("kline") and not (context.get("stock") or {}).get("name"):
        raise HTTPException(status_code=404, detail="该股票缺少可分析的入库数据")
    analysis, llm_used, llm_error = await _generate_analysis(context, req.use_llm)
    if llm_error:
        analysis["llm_error"] = llm_error
    return await _finalize_analysis(
        db=db,
        normalized=normalized,
        context=context,
        analysis=analysis,
        llm_used=llm_used,
        task_id=task_id,
        started=started,
        save=req.save,
    )
