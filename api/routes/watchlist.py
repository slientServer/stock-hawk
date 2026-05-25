"""关注列表 API：CRUD + 3种盯盘模式自动推送。"""

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.tools.notification_tools import NotificationTools
from api.deps import get_db
from common.logger import get_logger
from common.models import DailyKline, Stock, WatchlistItem

logger = get_logger(__name__)
router = APIRouter(prefix="/watchlist", tags=["关注列表"])


# ── 请求体 ────────────────────────────────────────────────────────────────────

class WatchItemCreateRequest(BaseModel):
    code: str
    name: str
    industry: str | None = None
    source: str = "manual"
    note: str | None = None
    # Mode 1
    mode1_enabled: bool = False
    mode1_target_price: float | None = Field(default=None, gt=0)
    mode1_floor_price: float | None = Field(default=None, gt=0)
    # Mode 2
    mode2_enabled: bool = False
    mode2_base_price: float | None = Field(default=None, gt=0)
    mode2_up_pct: float | None = Field(default=None, gt=0)
    mode2_down_pct: float | None = Field(default=None, gt=0)
    # Mode 3
    mode3_enabled: bool = False


class WatchItemUpdateRequest(BaseModel):
    name: str | None = None
    industry: str | None = None
    note: str | None = None
    status: str | None = None
    # Mode 1
    mode1_enabled: bool | None = None
    mode1_target_price: float | None = Field(default=None, gt=0)
    mode1_floor_price: float | None = Field(default=None, gt=0)
    # Mode 2
    mode2_enabled: bool | None = None
    mode2_base_price: float | None = Field(default=None, gt=0)
    mode2_up_pct: float | None = Field(default=None, gt=0)
    mode2_down_pct: float | None = Field(default=None, gt=0)
    # Mode 3
    mode3_enabled: bool | None = None


# ── 工具函数 ──────────────────────────────────────────────────────────────────

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


def _item_payload(row: WatchlistItem, quote: dict[str, Any] | None = None) -> dict[str, Any]:
    price = quote.get("price") if quote else None
    change_pct = quote.get("change_pct") if quote else None
    is_realtime = quote.get("is_realtime", False) if quote else False
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "industry": row.industry,
        "source": row.source,
        "note": row.note,
        "status": row.status,
        "current_price": float(price) if price is not None else None,
        "change_pct": float(change_pct) if change_pct is not None else None,
        "is_realtime": is_realtime,
        "mode1_enabled": row.mode1_enabled,
        "mode1_target_price": float(row.mode1_target_price) if row.mode1_target_price else None,
        "mode1_floor_price": float(row.mode1_floor_price) if row.mode1_floor_price else None,
        "mode2_enabled": row.mode2_enabled,
        "mode2_base_price": float(row.mode2_base_price) if row.mode2_base_price else None,
        "mode2_up_pct": row.mode2_up_pct,
        "mode2_down_pct": row.mode2_down_pct,
        "mode3_enabled": row.mode3_enabled,
        "last_notified_mode1": row.last_notified_mode1,
        "last_notified_mode2": row.last_notified_mode2,
        "last_notified_mode3_date": row.last_notified_mode3_date,
        "created_at": str(row.created_at) if row.created_at else None,
    }


async def _realtime_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    from data_collector.cache.redis_cache import RedisCache
    from data_collector.sources.market_realtime import RealtimeCollector
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
    price = float(latest.close) if latest.close else None
    if not price or price <= 0:
        return None
    previous_close = float(rows[1].close) if len(rows) > 1 and rows[1].close else None
    change_pct = round((price / previous_close - 1) * 100, 2) if previous_close else None
    return {"code": code, "price": price, "change_pct": change_pct, "is_realtime": False}


async def _quotes_for_codes(db: AsyncSession, codes: list[str]) -> dict[str, dict[str, Any]]:
    normalized = [c for c in dict.fromkeys(codes) if c]
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


def _calc_rsi14(closes: list[float]) -> float | None:
    """从最近 N 条收盘价计算 RSI14，需要至少 15 条数据。"""
    if len(closes) < 15:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0) for c in changes[-14:]]
    losses = [abs(min(c, 0)) for c in changes[-14:]]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


# ── 搜索端点 ──────────────────────────────────────────────────────────────────

@router.get("/search")
async def search_stocks(q: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    """按代码或中文名称搜索股票，用于添加关注项时的自动补全。"""
    stmt = select(Stock).where(
        or_(Stock.code.contains(q), Stock.name.contains(q))
    ).limit(20)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"code": r.code, "name": r.name, "industry": r.industry} for r in rows]


# ── CRUD 路由 ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_watchlist(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(WatchlistItem)
            .order_by(WatchlistItem.created_at.desc())
        )
    ).scalars().all()
    if not rows:
        return {"items": []}
    quotes = await _quotes_for_codes(db, [r.code for r in rows])
    return {"items": [_item_payload(r, quotes.get(r.code)) for r in rows]}


@router.post("")
async def add_watchlist_item(req: WatchItemCreateRequest, db: AsyncSession = Depends(get_db)):
    code = _normalize_code(req.code)
    if not code:
        raise HTTPException(status_code=400, detail="无效的股票代码")

    # 若 mode2 启用且没提供基准价，自动取实时价
    base_price = req.mode2_base_price
    if req.mode2_enabled and not base_price:
        quotes = await _quotes_for_codes(db, [code])
        q = quotes.get(code)
        if q and q.get("price"):
            base_price = q["price"]

    item = WatchlistItem(
        code=code,
        name=req.name,
        industry=req.industry,
        source=req.source,
        note=req.note,
        mode1_enabled=req.mode1_enabled,
        mode1_target_price=_dec(req.mode1_target_price),
        mode1_floor_price=_dec(req.mode1_floor_price),
        mode2_enabled=req.mode2_enabled,
        mode2_base_price=_dec(base_price),
        mode2_up_pct=req.mode2_up_pct,
        mode2_down_pct=req.mode2_down_pct,
        mode3_enabled=req.mode3_enabled,
        status="active",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _item_payload(item)


@router.put("/{item_id}")
async def update_watchlist_item(
    item_id: int,
    req: WatchItemUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(WatchlistItem).where(WatchlistItem.id == item_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="关注项不存在")

    update_data = req.model_dump(exclude_none=True)
    for field, value in update_data.items():
        if field in ("mode1_target_price", "mode1_floor_price", "mode2_base_price"):
            setattr(row, field, _dec(value))
        else:
            setattr(row, field, value)

    await db.commit()
    await db.refresh(row)
    return _item_payload(row)


@router.delete("/{item_id}")
async def delete_watchlist_item(item_id: int, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(select(WatchlistItem).where(WatchlistItem.id == item_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="关注项不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ── 盯盘监控主函数 ────────────────────────────────────────────────────────────

async def check_and_notify_watchlist(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """
    检查所有 active 关注项的3种盯盘模式，触发时推送飞书通知。
    供 AgentScheduler 盘中每5分钟调用。
    """
    notifier = NotificationTools()
    if not notifier.is_available():
        return {"status": "skipped", "reason": "飞书未配置"}

    async with session_factory() as db:
        rows = list(
            (
                await db.execute(
                    select(WatchlistItem).where(WatchlistItem.status == "active")
                )
            ).scalars().all()
        )

    if not rows:
        return {"status": "ok", "checked": 0, "notified": 0}

    async with session_factory() as db:
        quotes = await _quotes_for_codes(db, [r.code for r in rows])

    today_str = date.today().isoformat()
    notified = 0

    for row in rows:
        quote = quotes.get(row.code)
        if not quote or not quote.get("price"):
            continue
        current_price = float(quote["price"])
        name = row.name
        code = row.code

        # ── Mode 1：目标价/下限价触发 ────────────────────────────────────────
        if row.mode1_enabled:
            triggered_m1 = None
            if row.mode1_target_price and current_price >= float(row.mode1_target_price):
                triggered_m1 = "target"
            elif row.mode1_floor_price and current_price <= float(row.mode1_floor_price):
                triggered_m1 = "floor"

            # 恢复正常区间时清除去重标记
            if triggered_m1 is None and row.last_notified_mode1 is not None:
                async with session_factory() as db:
                    r = (await db.execute(select(WatchlistItem).where(WatchlistItem.id == row.id))).scalar_one_or_none()
                    if r:
                        r.last_notified_mode1 = None
                        await db.commit()

            elif triggered_m1 and row.last_notified_mode1 != triggered_m1:
                if triggered_m1 == "target":
                    msg = (
                        f"CtxHub 【关注列表 目标价触发】\n"
                        f"{name}({code})\n"
                        f"当前价: {current_price:.3f}  |  目标价: {float(row.mode1_target_price):.3f}"
                    )
                else:
                    msg = (
                        f"CtxHub 【关注列表 下限价触发】\n"
                        f"{name}({code})\n"
                        f"当前价: {current_price:.3f}  |  下限价: {float(row.mode1_floor_price):.3f}"
                    )
                result = await notifier.send_feishu(msg)
                if result.success:
                    notified += 1
                    async with session_factory() as db:
                        r = (await db.execute(select(WatchlistItem).where(WatchlistItem.id == row.id))).scalar_one_or_none()
                        if r:
                            r.last_notified_mode1 = triggered_m1
                            await db.commit()
                    logger.info("[WatchlistMonitor] Mode1 推送: %s %s triggered=%s", code, name, triggered_m1)

        # ── Mode 2：基准涨跌幅触发 ───────────────────────────────────────────
        if row.mode2_enabled and row.mode2_base_price:
            base = float(row.mode2_base_price)
            change_pct = (current_price - base) / base * 100
            triggered_m2 = None
            if row.mode2_up_pct and change_pct >= row.mode2_up_pct:
                triggered_m2 = "up"
            elif row.mode2_down_pct and change_pct <= -row.mode2_down_pct:
                triggered_m2 = "down"

            # 回到正常区间时重置去重
            if triggered_m2 is None and row.last_notified_mode2 is not None:
                async with session_factory() as db:
                    r = (await db.execute(select(WatchlistItem).where(WatchlistItem.id == row.id))).scalar_one_or_none()
                    if r:
                        r.last_notified_mode2 = None
                        await db.commit()

            elif triggered_m2 and row.last_notified_mode2 != triggered_m2:
                direction = "上涨" if triggered_m2 == "up" else "下跌"
                threshold = row.mode2_up_pct if triggered_m2 == "up" else row.mode2_down_pct
                sign = "+" if triggered_m2 == "up" else "-"
                msg = (
                    f"CtxHub 【关注列表 涨跌幅触发】\n"
                    f"{name}({code})\n"
                    f"当前价: {current_price:.3f}  |  基准价: {base:.3f}\n"
                    f"较基准{direction} {abs(change_pct):.1f}%（触发阈值 {sign}{threshold}%）"
                )
                result = await notifier.send_feishu(msg)
                if result.success:
                    notified += 1
                    async with session_factory() as db:
                        r = (await db.execute(select(WatchlistItem).where(WatchlistItem.id == row.id))).scalar_one_or_none()
                        if r:
                            r.last_notified_mode2 = triggered_m2
                            await db.commit()
                    logger.info("[WatchlistMonitor] Mode2 推送: %s %s change=%.2f%%", code, name, change_pct)

        # ── Mode 3：RSI14 超卖回升 ─────────────────────────────────────────
        if row.mode3_enabled:
            if row.last_notified_mode3_date == today_str:
                continue  # 今日已推过

            async with session_factory() as db:
                klines = list(
                    (
                        await db.execute(
                            select(DailyKline)
                            .where(DailyKline.code == code)
                            .order_by(desc(DailyKline.trade_date))
                            .limit(17)
                        )
                    ).scalars().all()
                )

            if len(klines) < 16:
                continue

            closes = [float(k.close) for k in reversed(klines) if k.close]
            if len(closes) < 16:
                continue

            rsi_prev = _calc_rsi14(closes[:-1])
            rsi_curr = _calc_rsi14(closes)
            if rsi_prev is None or rsi_curr is None:
                continue

            if rsi_prev < 30 and rsi_curr >= 30:
                msg = (
                    f"CtxHub 【关注列表 RSI超卖回升】\n"
                    f"{name}({code})\n"
                    f"RSI14={rsi_curr:.1f}，从超卖区回升，关注买入机会\n"
                    f"当前价: {current_price:.3f}"
                )
                result = await notifier.send_feishu(msg)
                if result.success:
                    notified += 1
                    async with session_factory() as db:
                        r = (await db.execute(select(WatchlistItem).where(WatchlistItem.id == row.id))).scalar_one_or_none()
                        if r:
                            r.last_notified_mode3_date = today_str
                            await db.commit()
                    logger.info("[WatchlistMonitor] Mode3 RSI推送: %s %s rsi=%.1f", code, name, rsi_curr)

    return {"status": "ok", "checked": len(rows), "notified": notified}
