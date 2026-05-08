"""股票路由：个股数据、行情查询和数据采集任务。"""

import json
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, distinct
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_session_factory
from common.config import get_settings
from common.models import Base, CommodityPrice, DailyKline, FundFlow, FinancialReport, InstitutionalHolding, NewsEvent, OverseasMapping, OverseasStock, Signal, Stock
from data_collector.cache.redis_cache import RedisCache
from data_collector.sources.commodity_price import CommodityPriceCollector
from data_collector.sources.financial_report import FinancialReportCollector
from data_collector.sources.fund_flow import FundFlowCollector
from data_collector.sources.institutional_holding import InstitutionalHoldingCollector
from data_collector.sources.market_basic import StockBasicCollector
from data_collector.sources.market_kline import KlineCollector
from data_collector.sources.news_crawler import NewsEventCollector
from data_collector.sources.overseas_mapping import OverseasMappingCollector
from data_collector.sources.shareholder import ShareholderCollector
from data_collector.storage import DataStorage
from knowledge_graph.neo4j_client import Neo4jClient
from knowledge_graph.seed_data import ALL_CHAINS, get_all_nodes, get_all_relationships

router = APIRouter(prefix="/stocks", tags=["股票"])


class FinancialRefreshRequest(BaseModel):
    codes: list[str] | None = None
    years: int = Field(default=3, ge=1, le=10)


DataTask = Literal[
    "schema",
    "seed_stocks",
    "stock_basic",
    "seed_klines",
    "fund_flow",
    "seed_shareholders",
    "seed_financials",
    "seed_graph",
    "focus_all",
    "seed_all",
    "collect_all",
    "news_events",
    "commodity_prices",
    "overseas_stocks",
    "institutional_holdings",
    "stock_detail",
]


class DataCollectRequest(BaseModel):
    task: DataTask
    codes: list[str] | None = None
    days: int = Field(default=365, ge=1, le=3650)
    years: int = Field(default=3, ge=1, le=10)


_collect_status: dict[str, Any] = {
    "running": False,
    "task": None,
    "status": "idle",
    "progress": "idle",
    "started_at": None,
    "finished_at": None,
    "result": None,
    "error": None,
}


def _default_seed_codes() -> list[str]:
    codes: list[str] = []
    for chain in ALL_CHAINS:
        for company in chain["companies"]:
            code = company["code"]
            if code not in codes:
                codes.append(code)
    return codes


def _normalize_code(code: Any) -> str | None:
    text = str(code or "").strip().upper()
    if not text:
        return None
    if "." in text:
        text = text.split(".", 1)[0]
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    if not text.isdigit():
        return None
    return text.zfill(6)


def _extend_unique_codes(target: list[str], values: list[Any]) -> None:
    for value in values:
        code = _normalize_code(value)
        if code and code not in target:
            target.append(code)


def _codes_from_signal_payload(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return [payload]
        return _codes_from_signal_payload(parsed)
    if isinstance(payload, list):
        return [item for item in payload if item is not None]
    if isinstance(payload, dict):
        values: list[Any] = []
        for value in payload.values():
            if isinstance(value, list):
                values.extend(value)
            else:
                values.append(value)
        return values
    return [payload]


async def _graph_company_codes() -> list[str]:
    try:
        client = await Neo4jClient.get_instance()
        rows = await client.run(
            """
            MATCH (company:Company)-[:BELONGS_TO]->(:Segment)
            RETURN DISTINCT company.code AS code
            ORDER BY code
            """
        )
    except Exception:
        return []
    return [row.get("code") for row in rows if row.get("code")]


async def _focus_codes(storage: DataStorage) -> list[str]:
    """重点股票：人工验证种子链、图谱公司、已有信号标的。"""
    codes = _default_seed_codes()
    _extend_unique_codes(codes, await _graph_company_codes())

    try:
        async with storage.session_factory() as session:
            rows = (await session.execute(select(Signal.target_codes, Signal.source_entity))).all()
    except Exception:
        rows = []

    for target_codes, source_entity in rows:
        _extend_unique_codes(codes, _codes_from_signal_payload(target_codes))
        _extend_unique_codes(codes, [source_entity])

    return codes


def _market(code: str) -> str:
    if code.startswith(("6", "9")):
        return "沪"
    if code.startswith(("4", "8")):
        return "北"
    return "深"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: float | None) -> float | None:
    return round(value * 100, 2) if value is not None else None


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
        "trigger_date": str(row.trigger_date) if row.trigger_date else None,
        "expire_date": str(row.expire_date) if row.expire_date else None,
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


def _kline_metrics(rows: list[DailyKline]) -> dict[str, Any]:
    closes = [_num(row.close) for row in rows if row.close is not None]
    amounts = [_num(row.amount) for row in rows[-20:] if row.amount is not None]
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
        if len(closes) <= period or not closes[-period - 1]:
            return None
        return (closes[-1] - closes[-period - 1]) / closes[-period - 1]

    high_60 = max(closes[-60:]) if closes else None
    drawdown = (closes[-1] / high_60 - 1) if high_60 else None
    return {
        "latest_close": round(closes[-1], 3),
        "return_5d": _pct(period_return(5)),
        "return_20d": _pct(period_return(20)),
        "drawdown_60d": _pct(drawdown),
        "avg_amount_20d": round(sum(amounts) / len(amounts), 2) if amounts else None,
        "latest_trade_date": str(rows[-1].trade_date) if rows else None,
    }


def _signal_matches_code(signal: Signal, code: str) -> bool:
    codes = {_normalize_code(item) for item in _codes_from_signal_payload(signal.target_codes)}
    codes.discard(None)
    source = _normalize_code(signal.source_entity)
    if source:
        codes.add(source)
    return code in codes


async def _graph_exposure(code: str) -> list[dict[str, Any]]:
    try:
        client = await Neo4jClient.get_instance()
        rows = await client.run(
            """
            MATCH (company:Company {code: $code})-[:BELONGS_TO]->(s:Segment)
            MATCH (c:IndustryChain {name: s.chain_name})
            WHERE (
              properties(c)['_source'] = 'chain_discovery'
              AND properties(c)['_discovery_source_mode'] = 'market_boards'
            )
            OR properties(c)['_source'] IN ['manual_verified', 'verified_import']
            RETURN
              c.name AS chain_name,
              s.name AS segment_name,
              s.position AS position
            ORDER BY c.name, s.position, s.name
            """,
            code=code,
        )
    except Exception:
        return []

    return [
        {
            "chain_name": row.get("chain_name"),
            "segment_name": row.get("segment_name"),
            "position": row.get("position"),
        }
        for row in rows
        if row.get("chain_name")
    ]


def _seed_stocks() -> list[dict]:
    stocks: dict[str, dict] = {}
    for chain in ALL_CHAINS:
        for company in chain["companies"]:
            code = company["code"]
            stocks.setdefault(
                code,
                {
                    "code": code,
                    "name": company.get("name"),
                    "industry": company.get("industry"),
                    "market": _market(code),
                    "market_cap": float(company["market_cap"]) * 100000000 if company.get("market_cap") else None,
                    "is_st": False,
                    "data_source": "knowledge_graph_seed",
                },
            )
    return list(stocks.values())


def _empty_stats() -> dict:
    return {
        "stock_count": 0,
        "kline_count": 0,
        "signal_count": 0,
        "fund_flow_count": 0,
    }


def _set_collect_status(**updates):
    _collect_status.update(updates)


async def _ensure_database_schema() -> dict:
    settings = get_settings()
    engine = create_async_engine(settings.db.async_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()
    return {"tables": len(Base.metadata.tables)}


async def _seed_stock_rows(storage: DataStorage) -> dict:
    rows = _seed_stocks()
    await storage.upsert_stock_basic(rows)
    return {"records_count": len(rows), "source": "knowledge_graph_seed"}


async def _seed_graph_rows() -> dict:
    client = await Neo4jClient.get_instance()
    await client.ensure_schema()
    nodes = get_all_nodes()
    node_counts: dict[str, int] = {}
    key_fields = {
        "IndustryChain": ["name"],
        "Segment": ["uid"],
        "Company": ["code"],
        "Technology": ["name"],
        "Product": ["name"],
    }
    for label, items in nodes.items():
        node_counts[label] = await client.merge_nodes_batch(label, items, key_fields[label])
    relationship_count = await client.merge_relationships_batch(get_all_relationships())
    return {"nodes": node_counts, "relationships": relationship_count}


async def _run_collect_task(req: DataCollectRequest) -> dict:
    storage = DataStorage(get_session_factory())
    result: dict[str, Any] = {}
    codes = req.codes or (_default_seed_codes() if req.task != "focus_all" else await _focus_codes(storage))

    async def run_step(name: str, fn):
        _set_collect_status(progress=name)
        result[name] = await fn()

    if req.task in {"schema", "seed_all"}:
        await run_step("schema", _ensure_database_schema)

    if req.task in {"seed_stocks", "seed_all"}:
        await run_step("seed_stocks", lambda: _seed_stock_rows(storage))

    if req.task == "stock_basic":
        await run_step("stock_basic", lambda: StockBasicCollector(storage).collect_stock_list())

    if req.task in {"seed_graph", "seed_all"}:
        await run_step("seed_graph", _seed_graph_rows)

    if req.task == "focus_all":
        result["focus_codes"] = {
            "count": len(codes),
            "preview": codes[:50],
            "source": "seed_chains+neo4j_companies+signals",
        }

    if req.task in {"seed_klines", "focus_all", "seed_all"}:
        cache = RedisCache()
        await cache.connect()
        try:
            collector = KlineCollector(storage, cache)
            start = date.today() - timedelta(days=req.days)
            await run_step("seed_klines", lambda: collector.collect_batch(codes, start_date=start))
        finally:
            await cache.close()

    if req.task in {"fund_flow", "seed_all"}:
        cache = RedisCache()
        await cache.connect()
        try:
            collector = FundFlowCollector(storage, cache)
            start = date.today() - timedelta(days=min(req.days, 365))
            await run_step("fund_flow", lambda: collector.collect_north_flow(start_date=start))
        finally:
            await cache.close()

    if req.task in {"seed_shareholders", "focus_all", "seed_all"}:
        await run_step("seed_shareholders", lambda: ShareholderCollector(storage).collect_batch(codes))

    if req.task in {"seed_financials", "focus_all", "seed_all"}:
        collector = FinancialReportCollector(storage)
        await run_step("seed_financials", lambda: collector.collect_batch(codes, years=req.years))
        if hasattr(result["seed_financials"], "as_dict"):
            result["seed_financials"] = result["seed_financials"].as_dict()

    if req.task == "news_events":
        cache = RedisCache()
        await cache.connect()
        try:
            collector = NewsEventCollector(storage, cache)
            await run_step("news_events", lambda: collector.collect_incremental(codes[:30] if codes else None))
        finally:
            await cache.close()

    if req.task == "commodity_prices":
        cache = RedisCache()
        await cache.connect()
        try:
            collector = CommodityPriceCollector(storage, cache)
            await run_step("commodity_prices", lambda: collector.collect_incremental())
        finally:
            await cache.close()

    if req.task == "overseas_stocks":
        cache = RedisCache()
        await cache.connect()
        try:
            collector = OverseasMappingCollector(storage, cache)
            await run_step("overseas_stocks", lambda: collector.collect_incremental())
        finally:
            await cache.close()

    if req.task == "institutional_holdings":
        cache = RedisCache()
        await cache.connect()
        try:
            collector = InstitutionalHoldingCollector(storage, cache)
            await run_step("institutional_holdings", lambda: collector.collect_incremental())
        finally:
            await cache.close()

    if req.task == "stock_detail":
        await run_step("stock_detail", lambda: StockBasicCollector(storage).collect_stock_detail(codes))

    if req.task == "collect_all":
        # 一键采集所有数据源
        cache = RedisCache()
        await cache.connect()
        try:
            # K线
            kline_collector = KlineCollector(storage, cache)
            start = date.today() - timedelta(days=req.days)
            await run_step("seed_klines", lambda: kline_collector.collect_batch(codes, start_date=start))
            # 北向资金
            ff_collector = FundFlowCollector(storage, cache)
            ff_start = date.today() - timedelta(days=min(req.days, 365))
            await run_step("fund_flow", lambda: ff_collector.collect_north_flow(start_date=ff_start))
            # 新闻事件
            news_collector = NewsEventCollector(storage, cache)
            await run_step("news_events", lambda: news_collector.collect_incremental(codes[:30] if codes else None))
            # 商品价格
            commodity_collector = CommodityPriceCollector(storage, cache)
            await run_step("commodity_prices", lambda: commodity_collector.collect_incremental())
            # 海外行情
            overseas_collector = OverseasMappingCollector(storage, cache)
            await run_step("overseas_stocks", lambda: overseas_collector.collect_incremental())
            # 机构持仓
            holding_collector = InstitutionalHoldingCollector(storage, cache)
            await run_step("institutional_holdings", lambda: holding_collector.collect_incremental())
        finally:
            await cache.close()
        # 股东户数
        await run_step("seed_shareholders", lambda: ShareholderCollector(storage).collect_batch(codes))
        # 财报
        fin_collector = FinancialReportCollector(storage)
        await run_step("seed_financials", lambda: fin_collector.collect_batch(codes, years=req.years))
        # 市值/上市日期（不传codes，自动检测缺失市值或名称的股票）
        await run_step("stock_detail", lambda: StockBasicCollector(storage).collect_stock_detail())
        # 采集完成后自动触发信号扫描
        async def _run_signal_scan():
            from agents.orchestrator import Orchestrator
            orch = Orchestrator(get_session_factory())
            return await orch.run_daily_scan()
        await run_step("signal_scan", _run_signal_scan)

    return result


async def _run_collect_background(req: DataCollectRequest):
    _set_collect_status(
        running=True,
        task=req.task,
        status="running",
        progress="starting",
        started_at=datetime.now().isoformat(timespec="seconds"),
        finished_at=None,
        result=None,
        error=None,
    )
    try:
        result = await _run_collect_task(req)
        _set_collect_status(
            running=False,
            status="completed",
            progress="completed",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result=result,
            error=None,
        )
    except Exception as e:
        _set_collect_status(
            running=False,
            status="failed",
            progress="failed",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result=None,
            error=str(e),
        )


@router.get("/stats")
async def get_data_stats(db: AsyncSession = Depends(get_db)):
    """数据概览统计"""
    try:
        stock_count = (await db.execute(select(func.count()).select_from(Stock))).scalar() or 0
        kline_count = (await db.execute(select(func.count()).select_from(DailyKline))).scalar() or 0
        signal_count = (await db.execute(select(func.count()).select_from(Signal))).scalar() or 0
        fund_flow_count = (await db.execute(select(func.count()).select_from(FundFlow))).scalar() or 0
    except Exception:
        return _empty_stats()
    return {
        "stock_count": stock_count,
        "kline_count": kline_count,
        "signal_count": signal_count,
        "fund_flow_count": fund_flow_count,
    }


@router.get("/stats/detail")
async def get_data_stats_detail(db: AsyncSession = Depends(get_db)):
    """详细数据统计：各维度数据覆盖情况"""
    try:
        # 股票总数
        stock_count = (await db.execute(select(func.count()).select_from(Stock))).scalar() or 0
    except Exception:
        seed_count = len(_seed_stocks())
        return {
            "stocks": {"total": seed_count, "industries": []},
            "klines": {"total": 0, "stock_coverage": 0, "date_from": None, "date_to": None, "recent_daily": []},
            "fund_flow": {"total": 0, "date_from": None, "date_to": None},
            "financials": {
                "total": 0,
                "stock_coverage": 0,
                "date_from": None,
                "date_to": None,
                "missing_publish_date": 0,
            },
            "signals": {"total": 0},
            "status": "degraded",
        }

    # 行业分布
    industry_stmt = (
        select(Stock.industry, func.count().label("count"))
        .where(Stock.industry.isnot(None))
        .group_by(Stock.industry)
        .order_by(desc("count"))
        .limit(20)
    )
    industry_rows = (await db.execute(industry_stmt)).all()
    industries = [{"industry": r[0], "count": r[1]} for r in industry_rows]

    # K线统计
    kline_count = (await db.execute(select(func.count()).select_from(DailyKline))).scalar() or 0
    kline_stocks = (await db.execute(select(func.count(distinct(DailyKline.code))))).scalar() or 0
    kline_date_range = (await db.execute(
        select(func.min(DailyKline.trade_date), func.max(DailyKline.trade_date))
    )).one_or_none()
    kline_min_date = str(kline_date_range[0]) if kline_date_range and kline_date_range[0] else None
    kline_max_date = str(kline_date_range[1]) if kline_date_range and kline_date_range[1] else None

    # 资金流统计
    fund_flow_count = (await db.execute(select(func.count()).select_from(FundFlow))).scalar() or 0
    fund_flow_date_range = (await db.execute(
        select(func.min(FundFlow.trade_date), func.max(FundFlow.trade_date))
    )).one_or_none()
    fund_min_date = str(fund_flow_date_range[0]) if fund_flow_date_range and fund_flow_date_range[0] else None
    fund_max_date = str(fund_flow_date_range[1]) if fund_flow_date_range and fund_flow_date_range[1] else None

    # 财报统计
    financial_count = (await db.execute(select(func.count()).select_from(FinancialReport))).scalar() or 0
    financial_stocks = (await db.execute(select(func.count(distinct(FinancialReport.code))))).scalar() or 0
    financial_date_range = (await db.execute(
        select(func.min(FinancialReport.report_date), func.max(FinancialReport.report_date))
    )).one_or_none()
    financial_min_date = str(financial_date_range[0]) if financial_date_range and financial_date_range[0] else None
    financial_max_date = str(financial_date_range[1]) if financial_date_range and financial_date_range[1] else None
    financial_missing_publish = (
        await db.execute(
            select(func.count()).select_from(FinancialReport).where(FinancialReport.publish_date.is_(None))
        )
    ).scalar() or 0

    # 信号统计
    signal_count = (await db.execute(select(func.count()).select_from(Signal))).scalar() or 0

    # 最近K线采集（按日期分组统计最近10天）
    recent_kline_stmt = (
        select(DailyKline.trade_date, func.count().label("count"))
        .group_by(DailyKline.trade_date)
        .order_by(desc(DailyKline.trade_date))
        .limit(10)
    )
    recent_kline_rows = (await db.execute(recent_kline_stmt)).all()
    recent_klines = [{"date": str(r[0]), "count": r[1]} for r in recent_kline_rows]

    return {
        "stocks": {
            "total": stock_count,
            "industries": industries,
        },
        "klines": {
            "total": kline_count,
            "stock_coverage": kline_stocks,
            "date_from": kline_min_date,
            "date_to": kline_max_date,
            "recent_daily": recent_klines,
        },
        "fund_flow": {
            "total": fund_flow_count,
            "date_from": fund_min_date,
            "date_to": fund_max_date,
        },
        "financials": {
            "total": financial_count,
            "stock_coverage": financial_stocks,
            "date_from": financial_min_date,
            "date_to": financial_max_date,
            "missing_publish_date": financial_missing_publish,
        },
        "signals": {
            "total": signal_count,
        },
    }


@router.get("/data-completeness")
async def get_data_completeness(db: AsyncSession = Depends(get_db)):
    """数据完备性分析：信号就绪状态 + 数据覆盖率 + 修复建议"""
    try:
        stock_total = (await db.execute(select(func.count()).select_from(Stock))).scalar() or 0
        with_market_cap = (await db.execute(
            select(func.count()).select_from(Stock).where(Stock.market_cap.isnot(None))
        )).scalar() or 0
        with_listed_date = (await db.execute(
            select(func.count()).select_from(Stock).where(Stock.listed_date.isnot(None))
        )).scalar() or 0

        commodity_count = (await db.execute(select(func.count()).select_from(CommodityPrice))).scalar() or 0
        commodity_products = (await db.execute(
            select(func.count(distinct(CommodityPrice.product_name)))
        )).scalar() or 0
        commodity_latest = (await db.execute(
            select(func.max(CommodityPrice.price_date))
        )).scalar()

        news_count = (await db.execute(select(func.count()).select_from(NewsEvent))).scalar() or 0
        news_today = (await db.execute(
            select(func.count()).select_from(NewsEvent).where(
                NewsEvent.publish_time >= datetime.now().replace(hour=0, minute=0, second=0)
            )
        )).scalar() or 0
        news_latest = (await db.execute(select(func.max(NewsEvent.publish_time)))).scalar()

        overseas_count = (await db.execute(select(func.count()).select_from(OverseasStock))).scalar() or 0
        overseas_symbols = (await db.execute(
            select(func.count(distinct(OverseasStock.symbol)))
        )).scalar() or 0
        mapping_count = (await db.execute(select(func.count()).select_from(OverseasMapping))).scalar() or 0

        holding_count = (await db.execute(select(func.count()).select_from(InstitutionalHolding))).scalar() or 0
        holding_stocks = (await db.execute(
            select(func.count(distinct(InstitutionalHolding.code)))
        )).scalar() or 0

    except Exception as e:
        return {
            "signals": [],
            "data_sources": {},
            "overall_score": 0,
            "recommendations": [],
            "error": str(e),
        }

    # 信号就绪状态
    signals_status = [
        {
            "signal_type": "supply_shortage",
            "name": "供需紧张",
            "weight": "15%",
            "ready": commodity_count > 0 and commodity_products >= 3,
            "reason": None if (commodity_count > 0 and commodity_products >= 3) else "缺少商品价格数据",
            "fix_action": "commodity_prices",
        },
        {
            "signal_type": "catalyst",
            "name": "催化剂",
            "weight": "10%",
            "ready": news_count >= 10,
            "reason": None if news_count >= 10 else "缺少新闻事件数据",
            "fix_action": "news_events",
        },
        {
            "signal_type": "overseas_mapping",
            "name": "海外映射",
            "weight": "10%",
            "ready": overseas_count > 0 and mapping_count > 0,
            "reason": None if (overseas_count > 0 and mapping_count > 0) else "缺少海外行情或映射关系",
            "fix_action": "overseas_stocks",
        },
        {
            "signal_type": "demand_inflection",
            "name": "需求拐点",
            "weight": "20%",
            "ready": True,  # Uses financial reports which are already collected
            "reason": None,
            "fix_action": None,
        },
        {
            "signal_type": "earnings_inflection",
            "name": "业绩拐点",
            "weight": "15%",
            "ready": True,
            "reason": None,
            "fix_action": None,
        },
        {
            "signal_type": "chip_concentration",
            "name": "筹码集中",
            "weight": "10%",
            "ready": True,
            "reason": None,
            "fix_action": None,
        },
        {
            "signal_type": "sector_linkage",
            "name": "板块联动",
            "weight": "10%",
            "ready": True,
            "reason": None,
            "fix_action": None,
        },
        {
            "signal_type": "north_flow_stock",
            "name": "北向资金",
            "weight": "5%",
            "ready": True,
            "reason": None,
            "fix_action": None,
        },
        {
            "signal_type": "valuation_percentile",
            "name": "估值分位",
            "weight": "5%",
            "ready": True,
            "reason": None,
            "fix_action": None,
        },
    ]

    # 数据源覆盖
    data_sources = {
        "commodity_prices": {
            "records": commodity_count,
            "products": commodity_products,
            "latest_date": str(commodity_latest) if commodity_latest else None,
        },
        "news_events": {
            "records": news_count,
            "today_count": news_today,
            "latest_date": news_latest.isoformat(timespec="seconds") if news_latest else None,
        },
        "overseas_stocks": {
            "records": overseas_count,
            "symbols": overseas_symbols,
            "mappings": mapping_count,
        },
        "institutional_holdings": {
            "records": holding_count,
            "stock_coverage": holding_stocks,
        },
        "stock_basic": {
            "total": stock_total,
            "with_market_cap": with_market_cap,
            "with_listed_date": with_listed_date,
        },
    }

    # 计算综合完备性分数
    scores = []
    if stock_total > 0:
        scores.append(min(100, with_market_cap / max(stock_total, 1) * 100))
    scores.append(min(100, commodity_products * 10))  # 10个产品=100分
    scores.append(min(100, news_count / 10 * 100))   # 10条=100分
    scores.append(min(100, overseas_symbols * 10))    # 10个=100分
    scores.append(min(100, holding_stocks * 2))       # 50只=100分
    overall_score = int(sum(scores) / len(scores)) if scores else 0

    # 修复建议
    recommendations = []
    if commodity_count == 0:
        recommendations.append({
            "priority": "P0",
            "action": "采集商品价格",
            "task": "commodity_prices",
            "impact": "激活supply_shortage信号(权重15%)",
        })
    if news_count < 10:
        recommendations.append({
            "priority": "P0",
            "action": "采集新闻事件",
            "task": "news_events",
            "impact": "激活catalyst信号(权重10%)",
        })
    if overseas_count == 0 or mapping_count == 0:
        recommendations.append({
            "priority": "P0",
            "action": "采集海外行情+同步映射",
            "task": "overseas_stocks",
            "impact": "激活overseas_mapping信号(权重10%)",
        })
    if with_market_cap == 0 and stock_total > 0:
        recommendations.append({
            "priority": "P1",
            "action": "补充个股市值和上市日期",
            "task": "stock_detail",
            "impact": "选股过滤需要市值数据",
        })
    if holding_count == 0:
        recommendations.append({
            "priority": "P1",
            "action": "采集机构持仓",
            "task": "institutional_holdings",
            "impact": "选股加分条件：机构加仓",
        })

    return {
        "signals": signals_status,
        "data_sources": data_sources,
        "overall_score": overall_score,
        "recommendations": recommendations,
    }


@router.get("/collect/status")
async def get_collect_status():
    return _collect_status


@router.get("/data-preview")
async def get_data_preview(
    source: str = Query(..., description="数据源: commodity_prices, news_events, overseas_stocks, institutional_holdings, stock_detail"),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """预览最近采集的数据"""
    from common.models import CommodityPrice, NewsEvent, OverseasStock, InstitutionalHolding, OverseasMapping

    if source == "commodity_prices":
        rows = (await db.execute(
            select(CommodityPrice).order_by(desc(CommodityPrice.price_date)).limit(limit)
        )).scalars().all()
        return {
            "source": source,
            "total": len(rows),
            "items": [
                {
                    "product_name": r.product_name,
                    "price_date": str(r.price_date),
                    "price": float(r.price) if r.price else None,
                    "price_change_pct": float(r.price_change_pct) if r.price_change_pct else None,
                    "chain_id": r.chain_id,
                    "source": r.source,
                }
                for r in rows
            ],
        }

    if source == "news_events":
        rows = (await db.execute(
            select(NewsEvent).order_by(desc(NewsEvent.publish_time)).limit(limit)
        )).scalars().all()
        return {
            "source": source,
            "total": len(rows),
            "items": [
                {
                    "title": r.title,
                    "publish_time": r.publish_time.isoformat(timespec="seconds") if r.publish_time else None,
                    "event_type": r.event_type,
                    "sentiment": r.sentiment,
                    "source": r.source,
                    "related_codes": r.related_codes,
                }
                for r in rows
            ],
        }

    if source == "overseas_stocks":
        rows = (await db.execute(
            select(OverseasStock).order_by(desc(OverseasStock.trade_date)).limit(limit)
        )).scalars().all()
        mappings = (await db.execute(select(OverseasMapping).limit(50))).scalars().all()
        return {
            "source": source,
            "total": len(rows),
            "items": [
                {
                    "symbol": r.symbol,
                    "name": r.name,
                    "trade_date": str(r.trade_date),
                    "close": float(r.close) if r.close else None,
                    "change_pct": float(r.change_pct) if r.change_pct else None,
                    "volume": r.volume,
                    "source": r.source,
                }
                for r in rows
            ],
            "mappings": [
                {
                    "a_code": m.a_code,
                    "a_name": m.a_name,
                    "overseas_symbol": m.overseas_symbol,
                    "overseas_name": m.overseas_name,
                    "relation_type": m.relation_type,
                    "chain_id": m.chain_id,
                }
                for m in mappings
            ],
        }

    if source == "institutional_holdings":
        rows = (await db.execute(
            select(InstitutionalHolding).order_by(desc(InstitutionalHolding.report_date)).limit(limit)
        )).scalars().all()
        return {
            "source": source,
            "total": len(rows),
            "items": [
                {
                    "code": r.code,
                    "report_date": str(r.report_date) if r.report_date else None,
                    "institution_name": r.institution_name,
                    "hold_amount": float(r.hold_amount) if r.hold_amount else None,
                    "hold_change": float(r.hold_change) if r.hold_change else None,
                    "hold_ratio": float(r.hold_ratio) if r.hold_ratio else None,
                    "source": r.source,
                }
                for r in rows
            ],
        }

    if source == "stock_detail":
        rows = (await db.execute(
            select(Stock).where(Stock.market_cap.isnot(None)).order_by(desc(Stock.updated_at)).limit(limit)
        )).scalars().all()
        return {
            "source": source,
            "total": len(rows),
            "items": [
                {
                    "code": r.code,
                    "name": r.name,
                    "market_cap": float(r.market_cap) if r.market_cap else None,
                    "listed_date": str(r.listed_date) if r.listed_date else None,
                    "industry": r.industry,
                }
                for r in rows
            ],
        }

    raise HTTPException(status_code=400, detail=f"不支持的数据源: {source}")


@router.post("/collect")
async def trigger_collect(req: DataCollectRequest, background_tasks: BackgroundTasks):
    if _collect_status.get("running"):
        return {
            "status": "already_running",
            "message": "已有数据采集任务正在执行",
            "current": _collect_status,
        }
    background_tasks.add_task(_run_collect_background, req)
    return {
        "status": "started",
        "task": req.task,
        "message": "数据采集任务已启动",
    }


@router.get("")
async def list_stocks(
    industry: str | None = Query(None),
    keyword: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """股票列表"""
    stmt = select(Stock)
    if industry:
        stmt = stmt.where(Stock.industry == industry)
    if keyword:
        stmt = stmt.where(Stock.name.contains(keyword) | Stock.code.contains(keyword))
    stmt = stmt.offset(offset).limit(limit)

    try:
        rows = (await db.execute(stmt)).scalars().all()
    except Exception:
        rows = []
        seed_rows = _seed_stocks()
        if industry:
            seed_rows = [s for s in seed_rows if s.get("industry") == industry]
        if keyword:
            seed_rows = [
                s for s in seed_rows if keyword in str(s.get("name", "")) or keyword in str(s.get("code", ""))
            ]
        return seed_rows[offset : offset + limit]

    if not rows:
        seed_rows = _seed_stocks()
        if industry:
            seed_rows = [s for s in seed_rows if s.get("industry") == industry]
        if keyword:
            seed_rows = [
                s for s in seed_rows if keyword in str(s.get("name", "")) or keyword in str(s.get("code", ""))
            ]
        return seed_rows[offset : offset + limit]

    return [
        {
            "code": s.code,
            "name": s.name,
            "industry": s.industry,
            "market": s.market,
            "market_cap": float(s.market_cap) if s.market_cap else None,
            "is_st": s.is_st,
        }
        for s in rows
    ]


@router.post("/financials/refresh")
async def refresh_financial_reports(req: FinancialRefreshRequest):
    """刷新财报指标；优先 Tushare，失败时降级 AKShare，仍禁止 mock 数据。"""
    codes = req.codes or _default_seed_codes()
    storage = DataStorage(get_session_factory())
    collector = FinancialReportCollector(storage)
    result = await collector.collect_batch(codes, years=req.years)
    return result.as_dict()


@router.get("/{code}/snapshot")
async def get_stock_snapshot(code: str, db: AsyncSession = Depends(get_db)):
    """个股快照：基础信息、图谱暴露、行情指标、财报和近期信号。"""
    normalized = _normalize_code(code)
    if not normalized:
        raise HTTPException(status_code=404, detail="Stock not found")

    try:
        stock = (await db.execute(select(Stock).where(Stock.code == normalized))).scalar_one_or_none()
        kline_rows = list(
            reversed(
                (
                    await db.execute(
                        select(DailyKline)
                        .where(DailyKline.code == normalized)
                        .order_by(desc(DailyKline.trade_date))
                        .limit(120)
                    )
                ).scalars().all()
            )
        )
        financial_rows = (
            await db.execute(
                select(FinancialReport)
                .where(FinancialReport.code == normalized)
                .order_by(desc(FinancialReport.report_date))
                .limit(8)
            )
        ).scalars().all()
        signal_rows = (
            await db.execute(
                select(Signal)
                .order_by(desc(Signal.trigger_date), desc(Signal.created_at))
                .limit(500)
            )
        ).scalars().all()
    except Exception:
        stock = None
        kline_rows = []
        financial_rows = []
        signal_rows = []

    if not stock:
        seed_stock = next((item for item in _seed_stocks() if item["code"] == normalized), None)
        if not seed_stock:
            raise HTTPException(status_code=404, detail="Stock not found")
        stock_payload = seed_stock
    else:
        stock_payload = {
            "code": stock.code,
            "name": stock.name,
            "industry": stock.industry,
            "market": stock.market,
            "market_cap": _num(stock.market_cap),
            "is_st": stock.is_st,
        }

    signals = [row for row in signal_rows if _signal_matches_code(row, normalized)][:20]
    exposure = await _graph_exposure(normalized)
    metrics = _kline_metrics(kline_rows)
    data_gaps = []
    if not exposure:
        data_gaps.append("图谱归属缺失")
    if not kline_rows:
        data_gaps.append("K线数据缺失")
    if not financial_rows:
        data_gaps.append("财报数据缺失")
    if not signals:
        data_gaps.append("近期信号缺失")

    return {
        "code": normalized,
        "stock": stock_payload,
        "chain_exposure": exposure,
        "metrics": metrics,
        "latest_financial": _financial_payload(financial_rows[0]) if financial_rows else None,
        "financial_history": [_financial_payload(row) for row in financial_rows],
        "recent_signals": [_signal_payload(row) for row in signals],
        "data_quality": {
            "has_stock": stock is not None,
            "has_graph": bool(exposure),
            "has_kline": bool(kline_rows),
            "has_financial": bool(financial_rows),
            "has_signal": bool(signals),
        },
        "data_gaps": data_gaps,
        "confidence": "medium" if stock and (kline_rows or financial_rows or signals) else "low",
    }


@router.get("/{code}")
async def get_stock(code: str, db: AsyncSession = Depends(get_db)):
    """股票详情"""
    try:
        stock = (await db.execute(select(Stock).where(Stock.code == code))).scalar_one_or_none()
    except Exception:
        stock = None
    if not stock:
        seed_stock = next((item for item in _seed_stocks() if item["code"] == code), None)
        if seed_stock:
            return seed_stock
        raise HTTPException(status_code=404, detail="Stock not found")
    return {
        "code": stock.code,
        "name": stock.name,
        "industry": stock.industry,
        "market": stock.market,
        "market_cap": float(stock.market_cap) if stock.market_cap else None,
        "is_st": stock.is_st,
    }


@router.get("/{code}/kline")
async def get_kline(
    code: str,
    days: int = Query(60, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """获取日K线"""
    stmt = (
        select(DailyKline)
        .where(DailyKline.code == code)
        .order_by(desc(DailyKline.trade_date))
        .limit(days)
    )
    try:
        rows = list(reversed((await db.execute(stmt)).scalars().all()))
    except Exception:
        return []
    return [
        {
            "trade_date": str(k.trade_date),
            "open": float(k.open or 0),
            "close": float(k.close or 0),
            "high": float(k.high or 0),
            "low": float(k.low or 0),
            "volume": k.volume,
            "amount": float(k.amount or 0),
            "turnover_rate": float(k.turnover_rate or 0),
        }
        for k in rows
    ]


@router.get("/{code}/financials")
async def get_financials(
    code: str,
    periods: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    """获取财务报告"""
    def optional_float(value):
        return float(value) if value is not None else None

    stmt = (
        select(FinancialReport)
        .where(FinancialReport.code == code)
        .order_by(desc(FinancialReport.report_date))
        .limit(periods)
    )
    try:
        rows = (await db.execute(stmt)).scalars().all()
    except Exception:
        return []
    return [
        {
            "report_date": str(r.report_date),
            "publish_date": str(r.publish_date) if r.publish_date else None,
            "revenue": optional_float(r.revenue),
            "revenue_yoy": optional_float(r.revenue_yoy),
            "net_profit": optional_float(r.net_profit),
            "net_profit_yoy": optional_float(r.net_profit_yoy),
            "gross_margin": optional_float(r.gross_margin),
            "roe": optional_float(r.roe),
            "pe": optional_float(r.pe_ratio),
            "pe_ratio": optional_float(r.pe_ratio),
            "pb_ratio": optional_float(r.pb_ratio),
            "source": r.source,
        }
        for r in rows
    ]
