"""持仓管理 API：建仓/加仓、实时估值、阈值提醒和操作历史。"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from common.models import DailyKline, PortfolioPosition, PortfolioTransaction, Stock
from data_collector.cache.redis_cache import RedisCache
from data_collector.sources.market_realtime import RealtimeCollector
from eod_screener.config import EODScreenerConfig

router = APIRouter(prefix="/portfolio", tags=["持仓管理"])


class PositionCreateRequest(BaseModel):
    code: str
    name: str | None = None
    quantity: int = Field(default=100, ge=1)
    buy_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    stop_loss_price: float | None = Field(default=None, gt=0)
    note: str | None = None
    source: str | None = "manual"


class PositionUpdateRequest(BaseModel):
    quantity: int | None = Field(default=None, ge=1)
    avg_cost: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    stop_loss_price: float | None = Field(default=None, gt=0)
    note: str | None = None


class PositionCloseRequest(BaseModel):
    quantity: int | None = Field(default=None, ge=1)
    close_price: float | None = Field(default=None, gt=0)
    note: str | None = None


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


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _money(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def _position_snapshot(row: PortfolioPosition | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "quantity": row.quantity,
        "avg_cost": _num(row.avg_cost),
        "target_price": _num(row.target_price),
        "stop_loss_price": _num(row.stop_loss_price),
        "status": row.status,
        "note": row.note,
    }


def _resolved_name(
    explicit: str | None,
    existing: str | None,
    stock: dict[str, Any] | None,
    quote: dict[str, Any] | None,
) -> str | None:
    return explicit or existing or (stock.get("name") if stock else None) or (quote.get("name") if quote else None)


def _default_thresholds(cost: Decimal) -> tuple[Decimal, Decimal]:
    config = EODScreenerConfig.load()
    target = cost * (Decimal("1") + Decimal(str(config.take_profit_pct)) / Decimal("100"))
    stop_loss = cost * (Decimal("1") - Decimal(str(config.stop_loss_pct)) / Decimal("100"))
    return (
        target.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        stop_loss.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
    )


async def _stock_payload(db: AsyncSession, code: str) -> dict[str, Any] | None:
    stock = (await db.execute(select(Stock).where(Stock.code == code))).scalar_one_or_none()
    if not stock:
        return None
    return {
        "code": stock.code,
        "name": stock.name,
        "industry": stock.industry,
        "market": stock.market,
        "market_cap": _num(stock.market_cap),
        "is_st": stock.is_st,
    }


async def _realtime_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    collector = RealtimeCollector(RedisCache())
    try:
        rows = await collector.fetch_realtime(codes)
    except Exception:
        rows = []
    finally:
        await collector.close()
    return {
        str(row.get("code")): row
        for row in rows
        if row.get("code") and float(row.get("price") or 0) > 0
    }


async def _stored_quote(db: AsyncSession, code: str) -> dict[str, Any] | None:
    rows = list(
        (
            await db.execute(
                select(DailyKline)
                .where(DailyKline.code == code)
                .order_by(desc(DailyKline.trade_date))
                .limit(2)
            )
        ).scalars().all()
    )
    if not rows:
        return None
    latest = rows[0]
    price = _num(latest.close)
    if price is None or price <= 0:
        return None
    previous_close = _num(rows[1].close) if len(rows) > 1 else _num(latest.open)
    change_pct = None
    if previous_close:
        change_pct = round((price / previous_close - 1) * 100, 2)
    return {
        "code": code,
        "price": price,
        "name": None,
        "change_pct": change_pct,
        "yesterday_close": previous_close,
        "timestamp": str(latest.trade_date),
        "source": "daily_kline",
        "is_realtime": False,
    }


async def _quotes_for_codes(db: AsyncSession, codes: list[str]) -> dict[str, dict[str, Any]]:
    normalized = [code for code in dict.fromkeys(codes) if code]
    realtime = await _realtime_quotes(normalized)
    quotes: dict[str, dict[str, Any]] = {}
    for code in normalized:
        quote = realtime.get(code)
        if quote:
            previous = float(quote.get("yesterday_close") or 0)
            price = float(quote.get("price") or 0)
            change_pct = round((price / previous - 1) * 100, 2) if previous else None
            quotes[code] = {**quote, "change_pct": change_pct, "is_realtime": True}
            continue
        stored = await _stored_quote(db, code)
        if stored:
            quotes[code] = stored
    return quotes


def _advice(row: PortfolioPosition, current_price: float | None, threshold_status: str) -> str:
    if current_price is None:
        return "缺少实时/入库行情，先补采行情或手工核对价格后再操作。"
    if threshold_status == "take_profit":
        return "已触及止盈阈值，建议复核信号强度，按计划分批止盈或上移止损。"
    if threshold_status == "stop_loss":
        return "已触及止损阈值，建议立即复核持仓逻辑，若无新增强信号则执行止损。"
    cost = float(row.avg_cost)
    if current_price >= cost:
        return "未触发止盈，持仓仍为盈利状态；继续跟踪信号，避免跌破成本后被动处理。"
    return "未触发止损但已低于成本；观察是否有信号证伪，弱势延续时降低仓位。"


def _position_payload(row: PortfolioPosition, quote: dict[str, Any] | None) -> dict[str, Any]:
    qty = int(row.quantity or 0)
    avg_cost = float(row.avg_cost)
    current_price = float(quote["price"]) if quote and quote.get("price") is not None else None
    cost_amount = avg_cost * qty
    market_value = current_price * qty if current_price is not None else None
    unrealized_profit = market_value - cost_amount if market_value is not None else None
    unrealized_return_pct = (unrealized_profit / cost_amount * 100) if cost_amount else None
    target_price = _num(row.target_price)
    stop_loss_price = _num(row.stop_loss_price)
    if current_price is None:
        threshold_status = "data_missing"
    elif target_price is not None and current_price >= target_price:
        threshold_status = "take_profit"
    elif stop_loss_price is not None and current_price <= stop_loss_price:
        threshold_status = "stop_loss"
    else:
        threshold_status = "holding"

    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "quantity": qty,
        "avg_cost": avg_cost,
        "cost_amount": _money(cost_amount),
        "current_price": current_price,
        "change_pct": quote.get("change_pct") if quote else None,
        "market_value": _money(market_value),
        "unrealized_profit": _money(unrealized_profit),
        "unrealized_return_pct": round(unrealized_return_pct, 2) if unrealized_return_pct is not None else None,
        "target_price": target_price,
        "stop_loss_price": stop_loss_price,
        "threshold_status": threshold_status,
        "action_advice": _advice(row, current_price, threshold_status),
        "quote_time": quote.get("timestamp") if quote else None,
        "quote_source": quote.get("source") if quote else None,
        "is_realtime": bool(quote.get("is_realtime")) if quote else False,
        "status": row.status,
        "note": row.note,
        "opened_at": row.opened_at.isoformat(timespec="seconds") if row.opened_at else None,
        "updated_at": row.updated_at.isoformat(timespec="seconds") if row.updated_at else None,
        "closed_at": row.closed_at.isoformat(timespec="seconds") if row.closed_at else None,
        "data_gaps": [] if current_price is not None else ["实时行情和入库K线均缺失"],
    }


def _transaction_payload(row: PortfolioTransaction) -> dict[str, Any]:
    return {
        "id": row.id,
        "position_id": row.position_id,
        "code": row.code,
        "action": row.action,
        "quantity": row.quantity,
        "price": _num(row.price),
        "amount": _num(row.amount),
        "realized_profit": _num(row.realized_profit),
        "note": row.note,
        "before_snapshot": row.before_snapshot,
        "after_snapshot": row.after_snapshot,
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    }


def _history_row(
    row: PortfolioPosition,
    action: str,
    *,
    quantity: int | None = None,
    price: Decimal | None = None,
    realized_profit: Decimal | None = None,
    note: str | None = None,
    before: dict[str, Any] | None = None,
) -> PortfolioTransaction:
    amount = price * Decimal(quantity) if price is not None and quantity is not None else None
    return PortfolioTransaction(
        position_id=row.id,
        code=row.code,
        action=action,
        quantity=quantity,
        price=price,
        amount=amount,
        realized_profit=realized_profit,
        note=note,
        before_snapshot=before,
        after_snapshot=_position_snapshot(row),
    )


@router.get("/quote/{code}")
async def get_quote(code: str, db: AsyncSession = Depends(get_db)):
    normalized = _normalize_code(code)
    if not normalized:
        raise HTTPException(404, "股票代码无效")
    stock = await _stock_payload(db, normalized)
    quotes = await _quotes_for_codes(db, [normalized])
    quote = quotes.get(normalized)
    return {
        "code": normalized,
        "name": quote.get("name") if quote and quote.get("name") else stock.get("name") if stock else None,
        "stock": stock,
        "price": quote.get("price") if quote else None,
        "change_pct": quote.get("change_pct") if quote else None,
        "quote_time": quote.get("timestamp") if quote else None,
        "quote_source": quote.get("source") if quote else None,
        "is_realtime": bool(quote.get("is_realtime")) if quote else False,
        "data_gaps": [] if quote else ["实时行情和入库K线均缺失"],
    }


@router.get("/positions")
async def list_positions(
    include_closed: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PortfolioPosition).order_by(desc(PortfolioPosition.updated_at), desc(PortfolioPosition.id))
    if not include_closed:
        stmt = stmt.where(PortfolioPosition.status == "active")
    try:
        rows = (await db.execute(stmt)).scalars().all()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "持仓表不可用，请先运行数据库迁移") from exc

    quotes = await _quotes_for_codes(db, [row.code for row in rows if row.status == "active"])
    items = [_position_payload(row, quotes.get(row.code)) for row in rows]
    active_items = [item for item in items if item["status"] == "active"]
    total_cost = sum(item["cost_amount"] or 0 for item in active_items)
    market_value = sum(item["market_value"] or 0 for item in active_items)
    unrealized_profit = market_value - total_cost
    realized_profit = (
        await db.execute(
            select(func.coalesce(func.sum(PortfolioTransaction.realized_profit), 0))
            .where(PortfolioTransaction.realized_profit.isnot(None))
        )
    ).scalar() or 0
    return {
        "items": items,
        "summary": {
            "active_count": len(active_items),
            "total_cost": _money(total_cost),
            "market_value": _money(market_value),
            "unrealized_profit": _money(unrealized_profit),
            "unrealized_return_pct": round(unrealized_profit / total_cost * 100, 2) if total_cost else None,
            "realized_profit": _money(realized_profit),
            "threshold_hit_count": sum(
                1 for item in active_items if item["threshold_status"] in {"take_profit", "stop_loss"}
            ),
            "data_gap_count": sum(1 for item in active_items if item["data_gaps"]),
        },
    }


@router.post("/positions")
async def create_position(req: PositionCreateRequest, db: AsyncSession = Depends(get_db)):
    normalized = _normalize_code(req.code)
    if not normalized:
        raise HTTPException(400, "股票代码无效")
    stock = await _stock_payload(db, normalized)
    quotes = await _quotes_for_codes(db, [normalized])
    quote = quotes.get(normalized)
    buy_price = _dec(req.buy_price if req.buy_price is not None else quote.get("price") if quote else None)
    if buy_price is None:
        raise HTTPException(400, "缺少真实行情价格，请手工输入买入价")

    target_price = _dec(req.target_price)
    stop_loss_price = _dec(req.stop_loss_price)
    if target_price is None or stop_loss_price is None:
        default_target, default_stop = _default_thresholds(buy_price)
        target_price = target_price or default_target
        stop_loss_price = stop_loss_price or default_stop

    row = (
        await db.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.code == normalized, PortfolioPosition.status == "active")
            .order_by(desc(PortfolioPosition.id))
            .limit(1)
        )
    ).scalar_one_or_none()

    if row:
        before = _position_snapshot(row)
        old_qty = int(row.quantity or 0)
        new_qty = old_qty + req.quantity
        new_cost = ((row.avg_cost * Decimal(old_qty)) + (buy_price * Decimal(req.quantity))) / Decimal(new_qty)
        row.quantity = new_qty
        row.avg_cost = new_cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if req.target_price is None and req.stop_loss_price is None:
            row.target_price, row.stop_loss_price = _default_thresholds(row.avg_cost)
        else:
            row.target_price = target_price
            row.stop_loss_price = stop_loss_price
        row.note = req.note or row.note
        row.name = _resolved_name(req.name, row.name, stock, quote)
        row.source = req.source or row.source
        action = "add_buy"
    else:
        row = PortfolioPosition(
            code=normalized,
            name=_resolved_name(req.name, None, stock, quote),
            quantity=req.quantity,
            avg_cost=buy_price,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            status="active",
            note=req.note,
            source=req.source,
        )
        db.add(row)
        await db.flush()
        before = None
        action = "buy"

    db.add(
        _history_row(
            row,
            action,
            quantity=req.quantity,
            price=buy_price,
            note=req.note or ("一键加入持仓" if action == "buy" else "加仓"),
            before=before,
        )
    )
    await db.commit()
    await db.refresh(row)
    return _position_payload(row, quote)


@router.patch("/positions/{position_id}")
async def update_position(
    position_id: int,
    req: PositionUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(PortfolioPosition).where(PortfolioPosition.id == position_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "持仓不存在")
    if row.status != "active":
        raise HTTPException(400, "已平仓持仓不可修改")
    before = _position_snapshot(row)
    if req.quantity is not None:
        row.quantity = req.quantity
    if req.avg_cost is not None:
        row.avg_cost = _dec(req.avg_cost)
    if req.target_price is not None:
        row.target_price = _dec(req.target_price)
    if req.stop_loss_price is not None:
        row.stop_loss_price = _dec(req.stop_loss_price)
    if req.note is not None:
        row.note = req.note
    db.add(_history_row(row, "update", quantity=row.quantity, price=row.avg_cost, note="修改持仓参数", before=before))
    await db.commit()
    await db.refresh(row)
    quotes = await _quotes_for_codes(db, [row.code])
    return _position_payload(row, quotes.get(row.code))


@router.post("/positions/{position_id}/close")
async def close_position(
    position_id: int,
    req: PositionCloseRequest,
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(PortfolioPosition).where(PortfolioPosition.id == position_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "持仓不存在")
    if row.status != "active":
        raise HTTPException(400, "该持仓已平仓")
    quotes = await _quotes_for_codes(db, [row.code])
    quote = quotes.get(row.code)
    close_price = _dec(req.close_price if req.close_price is not None else quote.get("price") if quote else None)
    if close_price is None:
        raise HTTPException(400, "缺少真实行情价格，请手工输入卖出价")
    close_qty = min(req.quantity or row.quantity, row.quantity)
    before = _position_snapshot(row)
    realized_profit = (close_price - row.avg_cost) * Decimal(close_qty)
    row.quantity -= close_qty
    if row.quantity <= 0:
        row.status = "closed"
        row.closed_at = datetime.now()
        action = "close"
    else:
        action = "sell"
    db.add(
        _history_row(
            row,
            action,
            quantity=close_qty,
            price=close_price,
            realized_profit=realized_profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            note=req.note or ("平仓" if action == "close" else "减仓"),
            before=before,
        )
    )
    await db.commit()
    await db.refresh(row)
    return _position_payload(row, quote)


@router.get("/positions/{position_id}/history")
async def get_position_history(
    position_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(PortfolioTransaction)
            .where(PortfolioTransaction.position_id == position_id)
            .order_by(desc(PortfolioTransaction.created_at), desc(PortfolioTransaction.id))
            .limit(limit)
        )
    ).scalars().all()
    return [_transaction_payload(row) for row in rows]


@router.get("/transactions")
async def list_transactions(
    code: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PortfolioTransaction)
    normalized = _normalize_code(code) if code else None
    if normalized:
        stmt = stmt.where(PortfolioTransaction.code == normalized)
    rows = (
        await db.execute(stmt.order_by(desc(PortfolioTransaction.created_at), desc(PortfolioTransaction.id)).limit(limit))
    ).scalars().all()
    return [_transaction_payload(row) for row in rows]
