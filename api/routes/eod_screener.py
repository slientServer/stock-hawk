"""尾盘选股 API 路由"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_session_factory
from common.models import EodBacktestResult, EodScreenResult
from data_collector.cache.redis_cache import RedisCache
from data_collector.sources.market_kline import KlineCollector
from data_collector.storage import DataStorage
from eod_screener.backtest import EODBacktestEngine
from eod_screener.config import EODScreenerConfig
from eod_screener.screener import EODScreener

router = APIRouter(prefix="/eod-screener", tags=["尾盘选股"])


# --- Schemas ---


class ScreenRequest(BaseModel):
    trade_date: date | None = None
    include_backtest: bool = True
    mode: Literal["intraday", "stored", "daily"] = "intraday"
    lookback_days: int = Field(default=30, ge=1, le=30)


class FullMarketCollectRequest(BaseModel):
    trade_date: date | None = None
    lookback_days: int = Field(default=30, ge=1, le=30)
    mode: Literal["intraday", "daily", "auto"] = "intraday"
    run_after: bool = False


class ConfigUpdateRequest(BaseModel):
    min_change_pct: float | None = None
    max_change_pct: float | None = None
    volume_ratio_min: float | None = None
    volume_avg_days: int | None = None
    ma_short: int | None = None
    ma_long: int | None = None
    price_above_ma: bool | None = None
    late_strength_min: float | None = None
    min_turnover_rate: float | None = None
    max_turnover_rate: float | None = None
    exclude_st: bool | None = None
    min_market_cap: float | None = None
    min_listed_days: int | None = None
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    max_hold_days: int | None = None
    backtest_lookback_days: int | None = None
    weight_change_pct: float | None = None
    weight_volume_ratio: float | None = None
    weight_late_strength: float | None = None
    weight_turnover: float | None = None
    weight_main_flow: float | None = None


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    code: str | None = None


# --- Helpers ---


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def _screen_item(row: EodScreenResult) -> dict:
    backtest = {
        "start_date": str(row.backtest_start_date) if row.backtest_start_date else None,
        "end_date": str(row.backtest_end_date) if row.backtest_end_date else None,
        "total_trades": row.backtest_total_trades,
        "win_rate": _num(row.backtest_win_rate),
        "avg_return": _num(row.backtest_avg_return),
        "max_drawdown": _num(row.backtest_max_drawdown),
        "profit_loss_ratio": _num(row.backtest_profit_loss_ratio),
        "score": _num(row.backtest_score),
    }
    return {
        "code": row.code,
        "trade_date": str(row.trade_date),
        "name": row.name,
        "close_price": _num(row.close_price),
        "change_pct": _num(row.change_pct),
        "volume_ratio": _num(row.volume_ratio),
        "turnover_rate": _num(row.turnover_rate),
        "late_strength": _num(row.late_strength),
        "score": _num(row.score),
        "rank": row.rank,
        "signal_strength": row.signal_strength,
        "target_price": _num(row.target_price),
        "stop_loss_price": _num(row.stop_loss_price),
        "suggestion": row.suggestion,
        "data_mode": row.data_mode,
        "quote_source": row.quote_source,
        "quote_time": row.quote_time.isoformat(timespec="seconds") if row.quote_time else None,
        "backtest_start_date": backtest["start_date"],
        "backtest_end_date": backtest["end_date"],
        "backtest_total_trades": backtest["total_trades"],
        "backtest_win_rate": backtest["win_rate"],
        "backtest_avg_return": backtest["avg_return"],
        "backtest_max_drawdown": backtest["max_drawdown"],
        "backtest_profit_loss_ratio": backtest["profit_loss_ratio"],
        "backtest_score": backtest["score"],
        "backtest": backtest,
    }


def _backtest_item(row: EodBacktestResult) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "start_date": str(row.start_date) if row.start_date else None,
        "end_date": str(row.end_date) if row.end_date else None,
        "total_trades": row.total_trades,
        "win_rate": _num(row.win_rate),
        "avg_return": _num(row.avg_return),
        "max_drawdown": _num(row.max_drawdown),
        "profit_loss_ratio": _num(row.profit_loss_ratio),
        "result_detail": row.result_detail,
        "created_at": str(row.created_at) if row.created_at else None,
    }


def _parse_quote_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


# --- Endpoints ---


@router.post("/run")
async def run_screen(req: ScreenRequest, session_factory=Depends(get_session_factory)):
    """手动触发尾盘选股"""
    collect_result: dict | None = None
    run_trade_date = req.trade_date
    data_mode = req.mode
    quote_source = None
    quote_time = None

    if req.mode in {"intraday", "daily"}:
        storage = DataStorage(session_factory)
        collector = KlineCollector(storage, RedisCache())
        collect_result = await collector.collect_full_market_daily(
            req.trade_date,
            lookback_days=req.lookback_days,
            mode=req.mode,
        )
        if collect_result.get("trade_date"):
            run_trade_date = date.fromisoformat(collect_result["trade_date"])
        data_mode = str(collect_result.get("data_mode") or req.mode)
        quote_source = collect_result.get("source")
        quote_time = _parse_quote_time(collect_result.get("quote_time"))
        if collect_result.get("status") == "failed":
            return {
                "status": "blocked",
                "requested_trade_date": str(req.trade_date) if req.trade_date else None,
                "trade_date": collect_result.get("trade_date"),
                "count": 0,
                "results": [],
                "diagnostics": {
                    "candidate_count": 0,
                    "passed_count": 0,
                    "filter_reasons": {},
                    "market_coverage": collect_result.get("market_coverage"),
                    "data_gaps": [collect_result.get("message") or "盘中行情采集失败，未执行尾盘选股"],
                    "source_errors": collect_result.get("source_errors") or [],
                    "sample_failures": [],
                },
                "collect_result": collect_result,
            }

    screener = EODScreener(session_factory)
    result = await screener.run_with_diagnostics(
        run_trade_date,
        include_backtest=req.include_backtest,
        data_mode=data_mode,
        quote_source=quote_source,
        quote_time=quote_time,
    )
    if collect_result is not None:
        result["collect_result"] = collect_result
    return result


@router.get("/coverage")
async def get_market_coverage(
    trade_date: date | None = Query(None),
    session_factory=Depends(get_session_factory),
):
    """查询尾盘选股所需的当日全市场行情覆盖率。"""
    screener = EODScreener(session_factory)
    return await screener.market_coverage(trade_date)


@router.post("/collect-full-market")
async def collect_full_market(
    req: FullMarketCollectRequest,
    session_factory=Depends(get_session_factory),
):
    """采集全市场日行情，写入 daily_klines 后可直接用于尾盘选股。"""
    storage = DataStorage(session_factory)
    collector = KlineCollector(storage, RedisCache())
    result = await collector.collect_full_market_daily(req.trade_date, lookback_days=req.lookback_days, mode=req.mode)
    if req.run_after and result.get("market_coverage", {}).get("is_full_market") and result.get("trade_date"):
        screener = EODScreener(session_factory)
        result["screen_result"] = await screener.run_with_diagnostics(
            date.fromisoformat(result["trade_date"]),
            data_mode=str(result.get("data_mode") or req.mode),
            quote_source=result.get("source"),
            quote_time=_parse_quote_time(result.get("quote_time")),
        )
    return result


@router.get("/results")
async def get_results(
    trade_date: date | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """查询选股结果"""
    stmt = select(EodScreenResult)
    if trade_date:
        stmt = stmt.where(EodScreenResult.trade_date == trade_date)
    stmt = stmt.order_by(desc(EodScreenResult.trade_date), EodScreenResult.rank).limit(limit)

    try:
        rows = (await db.execute(stmt)).scalars().all()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "尾盘选股结果表不可用，请先运行数据库迁移") from exc
    return [_screen_item(row) for row in rows]


@router.get("/results/{code}/history")
async def get_stock_history(
    code: str,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询某只股票的入选历史"""
    stmt = (
        select(EodScreenResult)
        .where(EodScreenResult.code == code)
        .order_by(desc(EodScreenResult.trade_date))
        .limit(limit)
    )
    try:
        rows = (await db.execute(stmt)).scalars().all()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "尾盘选股结果表不可用，请先运行数据库迁移") from exc
    return [_screen_item(row) for row in rows]


@router.get("/config")
async def get_config():
    """获取当前配置"""
    config = EODScreenerConfig.load()
    return config.to_dict()


@router.put("/config")
async def update_config(req: ConfigUpdateRequest):
    """更新配置"""
    current = EODScreenerConfig.load()
    updates = req.model_dump(exclude_none=True)
    if not updates:
        return current.to_dict()
    new_config = current.merge_update(updates)
    try:
        new_config.validate()
        new_config.save()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return new_config.to_dict()


@router.post("/backtest")
async def run_backtest(req: BacktestRequest, session_factory=Depends(get_session_factory)):
    """运行回测"""
    if req.start_date > req.end_date:
        raise HTTPException(400, "start_date must be earlier than end_date")
    engine = EODBacktestEngine(session_factory)
    codes = [req.code] if req.code else None
    return await engine.run(req.start_date, req.end_date, codes=codes)


@router.get("/backtest/results")
async def get_backtest_results(
    task_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查询回测结果"""
    stmt = select(EodBacktestResult)
    if task_id:
        stmt = stmt.where(EodBacktestResult.task_id == task_id)
    stmt = stmt.order_by(desc(EodBacktestResult.created_at)).limit(limit)

    try:
        rows = (await db.execute(stmt)).scalars().all()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "尾盘选股回测表不可用，请先运行数据库迁移") from exc
    return [_backtest_item(row) for row in rows]
