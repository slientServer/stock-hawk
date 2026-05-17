"""ETF 分析 API：关注列表管理、持仓跟踪、板块轮动综合分析。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from json import JSONDecodeError
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agents.llm_client import LLMClient
from api.deps import get_db, get_session_factory
from common.config import get_settings
from common.logger import get_logger
from common.models import (
    EtfAnalysisRecord,
    EtfDailyKline,
    EtfWatchItem,
    NewsEvent,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/etf", tags=["ETF分析"])

EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
)

TASKS: dict[str, dict[str, Any]] = {}
ETF_ANALYSIS_LOCK = asyncio.Lock()
SPOT_CACHE: dict[str, Any] = {
    "data": {},
    "fetched_at": None,
    "error": None,
}
SPOT_REFRESH_TASK: asyncio.Task | None = None
SPOT_CACHE_TTL_SECONDS = 60
SPOT_STALE_TTL_SECONDS = 10 * 60
FUND_DAILY_CACHE: dict[str, Any] = {"data": {}, "fetched_at": None, "error": None}
ETF_SCALE_CACHE: dict[str, Any] = {"data": {}, "fetched_at": None, "data_gaps": []}
ETF_META_CACHE_TTL_SECONDS = 60 * 60

ACTION_LABELS = {
    "buy": "买入",
    "add": "加仓",
    "hold": "持有",
    "watch": "观察",
    "reduce": "减仓",
    "avoid": "回避",
}

SOURCE_POLICY = (
    "ETF 分析数据来源于 AKShare ETF 行情/K线/净值/折溢价/基金份额接口、行业/概念板块行情与系统已入库的资讯数据；"
    "数据缺失时明确标注，不得补造；分析结果仅供研究参考，不构成投资建议。"
)


# ========== Pydantic 请求模型 ==========


class EtfWatchAddRequest(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str | None = None
    sector: str | None = None
    is_holding: bool = False
    cost_price: float | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, ge=1)
    target_price: float | None = Field(default=None, gt=0)
    stop_loss_price: float | None = Field(default=None, gt=0)
    note: str | None = None


class EtfWatchUpdateRequest(BaseModel):
    name: str | None = None
    sector: str | None = None
    is_holding: bool | None = None
    cost_price: float | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, ge=1)
    target_price: float | None = Field(default=None, gt=0)
    stop_loss_price: float | None = Field(default=None, gt=0)
    note: str | None = None


class EtfAnalysisRunRequest(BaseModel):
    use_llm: bool = True
    lookback_days: int = Field(default=120, ge=30, le=365)
    trigger_type: str = Field(default="manual", max_length=20)


# ========== 工具函数 ==========


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _expected_latest_kline_date(now: datetime | None = None) -> date:
    """估算当前应拿到的最新日 K 日期；节假日仍需依赖远端空返回降级。"""
    current = now or datetime.now()
    expected = current.date()
    if expected.weekday() < 5 and current.hour < 16:
        expected -= timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    return expected


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
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value.endswith("%"):
            value = value[:-1]
        if value in {"", "-", "--", "None", "nan"}:
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 3) -> float | None:
    return round(value, digits) if value is not None else None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _money(value: float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _money_text(value: float | None) -> str:
    if value is None:
        return "缺失"
    abs_value = abs(value)
    sign = "-" if value < 0 else ""
    if abs_value >= 100_000_000:
        return f"{sign}{_round(abs_value / 100_000_000, 2)}亿"
    if abs_value >= 10_000:
        return f"{sign}{_round(abs_value / 10_000, 2)}万"
    return f"{sign}{_round(abs_value, 2)}"


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


def _running_etf_task() -> dict[str, Any] | None:
    rows = [
        dict(task)
        for task in TASKS.values()
        if task.get("status") in {"queued", "running"} and str(task.get("task_id") or "").startswith("etf_analysis_")
    ]
    if not rows:
        return None
    rows.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return rows[0]


# ========== ETF 数据采集（缓存 + Tushare / 东方财富 / AKShare）==========


def _parse_trade_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    return None


def _etf_ts_code(code: str) -> str:
    clean = _normalize_code(code) or str(code).strip()
    if clean.startswith(("5", "6", "9")):
        return f"{clean}.SH"
    return f"{clean}.SZ"


def _eastmoney_secid(code: str) -> str:
    clean = _normalize_code(code)
    if not clean:
        return ""
    if clean.startswith(("5", "6", "9")):
        return f"1.{clean}"
    return f"0.{clean}"


def _sina_symbol(code: str) -> str:
    clean = _normalize_code(code)
    if not clean:
        return ""
    if clean.startswith(("5", "6", "9")):
        return f"sh{clean}"
    return f"sz{clean}"


def _market_headers(referer: str) -> dict[str, str]:
    settings = get_settings().data_source
    headers = {
        "User-Agent": settings.eastmoney_user_agent or DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
    }
    if settings.eastmoney_cookie:
        headers["Cookie"] = settings.eastmoney_cookie
    return headers


def _market_client(headers: dict[str, str]) -> httpx.AsyncClient:
    settings = get_settings().data_source
    timeout = max(settings.market_request_timeout or 15, 3)
    kwargs: dict[str, Any] = {
        "headers": headers,
        "timeout": httpx.Timeout(timeout),
        "follow_redirects": True,
    }
    if settings.market_proxy_url:
        kwargs["proxy"] = settings.market_proxy_url
    return httpx.AsyncClient(**kwargs)


def _normalize_kline_rows(rows: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        trade_date = _parse_trade_date(row.get("trade_date"))
        open_price = _num(row.get("open"))
        close_price = _num(row.get("close"))
        high_price = _num(row.get("high"))
        low_price = _num(row.get("low"))
        volume = _num(row.get("volume"))
        if trade_date is None or None in (open_price, close_price, high_price, low_price):
            continue
        normalized.append({
            "trade_date": trade_date,
            "open": open_price,
            "close": close_price,
            "high": high_price,
            "low": low_price,
            "volume": int(volume) if volume is not None else None,
            "amount": _num(row.get("amount")),
            "change_pct": _num(row.get("change_pct")),
            "turnover_rate": _num(row.get("turnover_rate")),
            "source": source,
        })
    normalized.sort(key=lambda item: item["trade_date"])
    return normalized


async def _fetch_etf_kline(code: str, lookback_days: int) -> list[dict[str, Any]]:
    """获取 ETF 历史 K 线（AKShare fund_etf_hist_em，前复权）"""
    try:
        import akshare as ak

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=lookback_days + 30)).strftime("%Y%m%d")
        df = await asyncio.to_thread(
            ak.fund_etf_hist_em,
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        if df is None or df.empty:
            return []
        rows: list[dict[str, Any]] = []
        for _, item in df.iterrows():
            rows.append({
                "trade_date": str(item.get("日期")),
                "open": _num(item.get("开盘")),
                "close": _num(item.get("收盘")),
                "high": _num(item.get("最高")),
                "low": _num(item.get("最低")),
                "volume": _num(item.get("成交量")),
                "amount": _num(item.get("成交额")),
                "change_pct": _num(item.get("涨跌幅")),
                "turnover_rate": _num(item.get("换手率")),
            })
        return rows
    except Exception as e:
        logger.warning(f"ETF kline fetch failed for {code}: {e}")
        return []


async def _fetch_etf_kline_tushare(code: str, start: date, end: date) -> list[dict[str, Any]]:
    token = get_settings().data_source.tushare_token
    if not token:
        return []
    try:
        import tushare as ts

        pro = ts.pro_api(token)
        df = await asyncio.to_thread(
            pro.fund_daily,
            ts_code=_etf_ts_code(code),
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return []
        rows: list[dict[str, Any]] = []
        for _, item in df.iterrows():
            amount = _num(item.get("amount"))
            rows.append({
                "trade_date": item.get("trade_date"),
                "open": item.get("open"),
                "close": item.get("close"),
                "high": item.get("high"),
                "low": item.get("low"),
                "volume": item.get("vol"),
                "amount": amount * 1000 if amount is not None else None,
                "change_pct": item.get("pct_chg"),
                "turnover_rate": None,
            })
        return _normalize_kline_rows(rows, "tushare_fund_daily")
    except Exception as e:
        logger.warning(f"Tushare ETF K线失败: code={code}, error={e}")
        return []


async def _fetch_etf_kline_eastmoney(code: str, start: date, end: date) -> list[dict[str, Any]]:
    secid = _eastmoney_secid(code)
    if not secid:
        return []
    days = max((end - start).days + 1, 1)
    params = {
        "secid": secid,
        "klt": "101",
        "fqt": "1",
        "beg": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "lmt": str(min(max(days * 2, 120), 10000)),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "wbp2u": "|0|0|0|web",
        "_": str(int(time.time() * 1000)),
    }
    try:
        async with _market_client(_market_headers("https://quote.eastmoney.com")) as client:
            resp = await client.get(EASTMONEY_KLINE_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, JSONDecodeError, ValueError) as e:
        logger.warning(f"东方财富 ETF K线失败: code={code}, error={e}")
        return []

    rows: list[dict[str, Any]] = []
    for raw in ((payload.get("data") or {}).get("klines") or []):
        parts = str(raw).split(",")
        if len(parts) < 11:
            continue
        rows.append({
            "trade_date": parts[0],
            "open": parts[1],
            "close": parts[2],
            "high": parts[3],
            "low": parts[4],
            "volume": parts[5],
            "amount": parts[6],
            "change_pct": parts[8],
            "turnover_rate": parts[10],
        })
    return _normalize_kline_rows(rows, "eastmoney_direct")


async def _fetch_etf_kline_tencent(code: str, start: date, end: date) -> list[dict[str, Any]]:
    symbol = _sina_symbol(code)
    if not symbol:
        return []
    days = max((end - start).days + 1, 1)
    params = {
        "_var": "kline_dayqfq",
        "param": f"{symbol},day,,,{min(max(days * 2, 120), 800)},qfq",
    }
    try:
        async with _market_client(_market_headers("https://gu.qq.com")) as client:
            resp = await client.get(TENCENT_KLINE_URL, params=params)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning(f"腾讯 ETF K线失败: code={code}, error={e}")
        return []

    text = resp.text.strip()
    if text.startswith("kline_dayqfq="):
        text = text.removeprefix("kline_dayqfq=").rstrip(";")
    try:
        payload = json.loads(text)
    except JSONDecodeError as e:
        logger.warning(f"腾讯 ETF K线 JSON 解析失败: code={code}, error={e}")
        return []
    if payload.get("code") != 0:
        logger.warning(f"腾讯 ETF K线返回异常: code={code}, response_code={payload.get('code')}")
        return []

    rows: list[dict[str, Any]] = []
    for stock_data in (payload.get("data") or {}).values():
        for item in stock_data.get("qfqday") or stock_data.get("day") or []:
            if len(item) < 6:
                continue
            trade_date = _parse_trade_date(item[0])
            if trade_date is None or trade_date < start or trade_date > end:
                continue
            rows.append({
                "trade_date": item[0],
                "open": item[1],
                "close": item[2],
                "high": item[3],
                "low": item[4],
                "volume": item[5],
                "amount": item[6] if len(item) > 6 else None,
                "change_pct": None,
                "turnover_rate": None,
            })
        break
    return _normalize_kline_rows(rows, "tencent_direct")


async def _fetch_etf_kline_akshare(code: str, start: date, end: date) -> list[dict[str, Any]]:
    lookback_days = max((end - start).days, 30)
    rows = await _fetch_etf_kline(code, lookback_days)
    return [
        row for row in _normalize_kline_rows(rows, "akshare_fund_etf_hist_em")
        if start <= row["trade_date"] <= end
    ]


def _kline_payload_from_cache(row: EtfDailyKline) -> dict[str, Any]:
    return {
        "trade_date": row.trade_date.isoformat() if row.trade_date else None,
        "open": _num(row.open),
        "close": _num(row.close),
        "high": _num(row.high),
        "low": _num(row.low),
        "volume": _num(row.volume),
        "amount": _num(row.amount),
        "change_pct": _num(row.change_pct),
        "turnover_rate": _num(row.turnover_rate),
        "source": row.source,
    }


async def _read_cached_etf_kline(db: AsyncSession, code: str, start: date) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(EtfDailyKline)
            .where(EtfDailyKline.code == code, EtfDailyKline.trade_date >= start)
            .order_by(EtfDailyKline.trade_date)
        )
    ).scalars().all()
    return [_kline_payload_from_cache(row) for row in rows]


async def _upsert_etf_kline_cache(db: AsyncSession, code: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    values = []
    for row in rows:
        values.append({
            "code": code,
            "trade_date": row["trade_date"],
            "open": _dec(row.get("open")),
            "close": _dec(row.get("close")),
            "high": _dec(row.get("high")),
            "low": _dec(row.get("low")),
            "volume": row.get("volume"),
            "amount": _dec(row.get("amount")),
            "change_pct": _dec(row.get("change_pct")),
            "turnover_rate": _dec(row.get("turnover_rate")),
            "source": row.get("source"),
            "updated_at": datetime.now(),
        })
    stmt = pg_insert(EtfDailyKline).values(values)
    update_cols = {
        "open": stmt.excluded.open,
        "close": stmt.excluded.close,
        "high": stmt.excluded.high,
        "low": stmt.excluded.low,
        "volume": stmt.excluded.volume,
        "amount": stmt.excluded.amount,
        "change_pct": stmt.excluded.change_pct,
        "turnover_rate": stmt.excluded.turnover_rate,
        "source": stmt.excluded.source,
        "updated_at": stmt.excluded.updated_at,
    }
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["code", "trade_date"],
            set_=update_cols,
        )
    )
    await db.commit()


def _latest_kline_date(rows: list[dict[str, Any]]) -> date | None:
    dates = [_parse_trade_date(row.get("trade_date")) for row in rows]
    dates = [d for d in dates if d is not None]
    return max(dates) if dates else None


def _remote_rows_to_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for row in rows:
        trade_date = _parse_trade_date(row.get("trade_date"))
        if trade_date is None:
            continue
        payload.append({
            "trade_date": trade_date.isoformat(),
            "open": _num(row.get("open")),
            "close": _num(row.get("close")),
            "high": _num(row.get("high")),
            "low": _num(row.get("low")),
            "volume": _num(row.get("volume")),
            "amount": _num(row.get("amount")),
            "change_pct": _num(row.get("change_pct")),
            "turnover_rate": _num(row.get("turnover_rate")),
            "source": row.get("source"),
        })
    payload.sort(key=lambda item: item["trade_date"])
    return payload


async def _force_fetch_etf_kline(db: AsyncSession, code: str, lookback_days: int) -> dict[str, Any]:
    """跳过缓存，强制从远端拉取并写缓存；返回成功源/错误"""
    end = datetime.now().date()
    start = end - timedelta(days=lookback_days + 30)
    errors: list[str] = []
    for source, fetcher in (
        ("tushare_fund_daily", _fetch_etf_kline_tushare),
        ("eastmoney_direct", _fetch_etf_kline_eastmoney),
        ("tencent_direct", _fetch_etf_kline_tencent),
        ("akshare_fund_etf_hist_em", _fetch_etf_kline_akshare),
    ):
        try:
            rows = await fetcher(code, start, end)
        except Exception as e:
            errors.append(f"{source}: {e}")
            continue
        if not rows:
            errors.append(f"{source}: 返回空数据")
            continue
        await _upsert_etf_kline_cache(db, code, rows)
        latest = max((r["trade_date"] for r in rows), default=None)
        return {
            "code": code,
            "ok": True,
            "source": source,
            "rows": len(rows),
            "latest_trade_date": latest.isoformat() if latest else None,
        }
    return {
        "code": code,
        "ok": False,
        "errors": errors,
    }


async def _load_etf_kline(db: AsyncSession, code: str, lookback_days: int) -> tuple[list[dict[str, Any]], str]:
    end = datetime.now().date()
    start = end - timedelta(days=lookback_days + 30)
    cached = await _read_cached_etf_kline(db, code, start)
    latest_cached = _latest_kline_date(cached)
    if cached and latest_cached and latest_cached >= _expected_latest_kline_date():
        return cached, "cache"

    for source, fetcher in (
        ("tushare_fund_daily", _fetch_etf_kline_tushare),
        ("eastmoney_direct", _fetch_etf_kline_eastmoney),
        ("tencent_direct", _fetch_etf_kline_tencent),
        ("akshare_fund_etf_hist_em", _fetch_etf_kline_akshare),
    ):
        rows = await fetcher(code, start, end)
        if not rows:
            continue
        await _upsert_etf_kline_cache(db, code, rows)
        return _remote_rows_to_payload(rows), source

    if cached:
        return cached, "cache_stale"
    return [], "missing"


async def _fetch_etf_spot_uncached() -> dict[str, dict[str, Any]]:
    """全市场 ETF 实时行情快照（AKShare fund_etf_spot_em）"""
    try:
        import akshare as ak

        df = await asyncio.to_thread(ak.fund_etf_spot_em)
        if df is None or df.empty:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for _, item in df.iterrows():
            code = _normalize_code(item.get("代码"))
            if not code:
                continue
            result[code] = {
                "code": code,
                "name": str(item.get("名称") or ""),
                "price": _num(item.get("最新价")),
                "change_pct": _num(item.get("涨跌幅")),
                "open": _num(item.get("今开")),
                "high": _num(item.get("最高")),
                "low": _num(item.get("最低")),
                "yesterday_close": _num(item.get("昨收")),
                "volume": _num(item.get("成交量")),
                "amount": _num(item.get("成交额")),
                "turnover_rate": _num(item.get("换手率")),
            }
        return result
    except Exception as e:
        logger.warning(f"ETF spot fetch failed: {e}")
        return {}


async def _refresh_etf_spot_cache() -> dict[str, dict[str, Any]]:
    global SPOT_REFRESH_TASK
    try:
        data = await _fetch_etf_spot_uncached()
        if data:
            SPOT_CACHE["data"] = data
            SPOT_CACHE["fetched_at"] = datetime.now()
            SPOT_CACHE["error"] = None
        else:
            SPOT_CACHE["error"] = "empty_spot_snapshot"
        return data
    finally:
        SPOT_REFRESH_TASK = None


async def _fetch_etf_spot_cached(wait_timeout: float = 3.0) -> dict[str, dict[str, Any]]:
    """返回真实 ETF 行情快照；冷启动慢时先返回旧缓存/空值，避免阻塞页面。"""
    global SPOT_REFRESH_TASK

    now = datetime.now()
    fetched_at = SPOT_CACHE.get("fetched_at")
    cached = SPOT_CACHE.get("data") or {}
    age = (now - fetched_at).total_seconds() if fetched_at else None
    if cached and age is not None and age <= SPOT_CACHE_TTL_SECONDS:
        return cached

    if SPOT_REFRESH_TASK is None or SPOT_REFRESH_TASK.done():
        SPOT_REFRESH_TASK = asyncio.create_task(_refresh_etf_spot_cache())

    if cached and age is not None and age <= SPOT_STALE_TTL_SECONDS:
        return cached

    try:
        return await asyncio.wait_for(asyncio.shield(SPOT_REFRESH_TASK), timeout=wait_timeout)
    except asyncio.TimeoutError:
        logger.info("ETF spot fetch is still running; returning without fresh quote snapshot")
        return cached


def _find_column(columns: list[Any], *keywords: str) -> str | None:
    for col in columns:
        name = str(col)
        if all(k in name for k in keywords):
            return name
    return None


async def _fetch_etf_fund_daily_cached() -> dict[str, dict[str, Any]]:
    """全市场 ETF 净值/折溢价快照，用于资金面和交易安全性评估。"""
    now = datetime.now()
    cached_at = FUND_DAILY_CACHE.get("fetched_at")
    if cached_at and (now - cached_at).total_seconds() <= ETF_META_CACHE_TTL_SECONDS:
        return FUND_DAILY_CACHE.get("data") or {}
    try:
        import akshare as ak

        df = await asyncio.to_thread(ak.fund_etf_fund_daily_em)
        if df is None or df.empty:
            FUND_DAILY_CACHE.update({"data": {}, "fetched_at": now, "error": "empty_fund_daily"})
            return {}

        columns = list(df.columns)
        unit_nav_col = _find_column(columns, "单位净值")
        accum_nav_col = _find_column(columns, "累计净值")
        result: dict[str, dict[str, Any]] = {}
        for _, item in df.iterrows():
            code = _normalize_code(item.get("基金代码"))
            if not code:
                continue
            result[code] = {
                "code": code,
                "fund_name": str(item.get("基金简称") or ""),
                "fund_type": str(item.get("类型") or ""),
                "unit_nav": _num(item.get(unit_nav_col)) if unit_nav_col else None,
                "accum_nav": _num(item.get(accum_nav_col)) if accum_nav_col else None,
                "nav_growth_pct": _num(item.get("增长率")),
                "market_price": _num(item.get("市价")),
                "discount_rate": _num(item.get("折价率")),
                "source": "akshare_fund_etf_fund_daily_em",
                "fetched_at": _now_iso(),
            }
        FUND_DAILY_CACHE.update({"data": result, "fetched_at": now, "error": None})
        return result
    except Exception as e:
        logger.warning(f"ETF fund daily fetch failed: {e}")
        FUND_DAILY_CACHE.update({"data": {}, "fetched_at": now, "error": str(e)})
        return {}


def _previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


async def _fetch_sse_scale_for_date(day: date) -> list[dict[str, Any]]:
    import akshare as ak

    df = await asyncio.to_thread(ak.fund_etf_scale_sse, date=day.strftime("%Y%m%d"))
    if df is None or df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, item in df.iterrows():
        code = _normalize_code(item.get("基金代码"))
        if not code:
            continue
        rows.append({
            "code": code,
            "shares": _num(item.get("基金份额")),
            "scale_date": _parse_trade_date(item.get("统计日期")) or day,
            "source": "akshare_fund_etf_scale_sse",
        })
    return rows


async def _fetch_latest_sse_scale() -> tuple[dict[str, dict[str, Any]], list[str]]:
    gaps: list[str] = []
    latest_rows: list[dict[str, Any]] = []
    latest_day: date | None = None
    day = _expected_latest_kline_date()
    for _ in range(7):
        try:
            latest_rows = await _fetch_sse_scale_for_date(day)
        except Exception as e:
            gaps.append(f"上交所 ETF 份额 {day.isoformat()} 获取失败：{e}")
            latest_rows = []
        if latest_rows:
            latest_day = day
            break
        day = _previous_weekday(day)

    if not latest_rows or latest_day is None:
        return {}, gaps or ["上交所 ETF 份额数据不可用"]

    prev_rows: list[dict[str, Any]] = []
    prev_day = _previous_weekday(latest_day)
    for _ in range(7):
        try:
            prev_rows = await _fetch_sse_scale_for_date(prev_day)
        except Exception:
            prev_rows = []
        if prev_rows:
            break
        prev_day = _previous_weekday(prev_day)

    prev_map = {row["code"]: row for row in prev_rows}
    result: dict[str, dict[str, Any]] = {}
    for row in latest_rows:
        code = row["code"]
        shares = row.get("shares")
        prev_shares = prev_map.get(code, {}).get("shares")
        share_delta = shares - prev_shares if shares is not None and prev_shares else None
        share_delta_pct = (share_delta / prev_shares * 100) if share_delta is not None and prev_shares else None
        result[code] = {
            **row,
            "prev_shares": prev_shares,
            "share_delta": _round(share_delta, 2),
            "share_delta_pct": _round(share_delta_pct, 2),
            "prev_scale_date": prev_map.get(code, {}).get("scale_date"),
        }
    return result, gaps


async def _fetch_szse_scale() -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        import akshare as ak

        df = await asyncio.to_thread(ak.fund_etf_scale_szse)
        if df is None or df.empty:
            return {}, ["深交所 ETF 份额数据为空"]
        result: dict[str, dict[str, Any]] = {}
        for _, item in df.iterrows():
            code = _normalize_code(item.get("基金代码"))
            if not code:
                continue
            result[code] = {
                "code": code,
                "shares": _num(item.get("基金份额")),
                "scale_date": None,
                "prev_shares": None,
                "share_delta": None,
                "share_delta_pct": None,
                "source": "akshare_fund_etf_scale_szse",
            }
        return result, []
    except Exception as e:
        logger.warning(f"SZSE ETF scale fetch failed: {e}")
        return {}, [f"深交所 ETF 份额获取失败：{e}"]


async def _fetch_etf_scale_cached() -> tuple[dict[str, dict[str, Any]], list[str]]:
    now = datetime.now()
    cached_at = ETF_SCALE_CACHE.get("fetched_at")
    if cached_at and (now - cached_at).total_seconds() <= ETF_META_CACHE_TTL_SECONDS:
        return ETF_SCALE_CACHE.get("data") or {}, ETF_SCALE_CACHE.get("data_gaps") or []

    sse, sse_gaps = await _fetch_latest_sse_scale()
    szse, szse_gaps = await _fetch_szse_scale()
    merged = {**sse, **szse}
    gaps = sse_gaps + szse_gaps
    ETF_SCALE_CACHE.update({"data": merged, "fetched_at": now, "data_gaps": gaps})
    return merged, gaps


# ========== 技术指标计算 ==========


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    ema_values = [values[0]]
    for v in values[1:]:
        ema_values.append(v * k + ema_values[-1] * (1 - k))
    return ema_values


def _macd(closes: list[float]) -> dict[str, float | None]:
    if len(closes) < 35:
        return {"dif": None, "dea": None, "hist": None}
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = _ema(dif, 9)
    return {
        "dif": _round(dif[-1], 4),
        "dea": _round(dea[-1], 4),
        "hist": _round((dif[-1] - dea[-1]) * 2, 4),
    }


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        diff = closes[-i] - closes[-i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(-diff)
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return _round(100 - 100 / (1 + rs), 2)


def _period_return(closes: list[float], period: int) -> float | None:
    if len(closes) <= period or not closes[-period - 1]:
        return None
    return _round((closes[-1] / closes[-period - 1] - 1) * 100, 2)


def _compute_technicals(kline: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [r["close"] for r in kline if r.get("close") is not None]
    if not closes:
        return {
            "latest_close": None, "latest_trade_date": None,
            "ma5": None, "ma10": None, "ma20": None, "ma60": None,
            "macd": {"dif": None, "dea": None, "hist": None},
            "rsi14": None,
            "return_5d": None, "return_20d": None, "return_60d": None,
            "volume_ratio": None,
            "trend": "unknown",
        }
    ma5 = _avg(closes[-5:])
    ma10 = _avg(closes[-10:])
    ma20 = _avg(closes[-20:])
    ma60 = _avg(closes[-60:]) if len(closes) >= 60 else None
    latest = closes[-1]
    # 量比：最新成交量 / 过去20日均量
    latest_volume = _num(kline[-1].get("volume"))
    prev_volumes = [_num(r.get("volume")) for r in kline[-21:-1]]
    prev_volumes = [v for v in prev_volumes if v is not None]
    avg_volume = _avg(prev_volumes) if len(prev_volumes) >= 20 else None
    volume_ratio = _round(latest_volume / avg_volume, 2) if avg_volume else None
    # 趋势判断
    if ma5 and ma20 and ma5 > ma20 and latest > ma5:
        trend = "up"
    elif ma5 and ma20 and ma5 < ma20 and latest < ma5:
        trend = "down"
    else:
        trend = "consolidation"
    return {
        "latest_close": _round(latest, 3),
        "latest_trade_date": kline[-1].get("trade_date"),
        "ma5": _round(ma5, 3),
        "ma10": _round(ma10, 3),
        "ma20": _round(ma20, 3),
        "ma60": _round(ma60, 3),
        "macd": _macd(closes),
        "rsi14": _rsi(closes, 14),
        "return_5d": _period_return(closes, 5),
        "return_20d": _period_return(closes, 20),
        "return_60d": _period_return(closes, 60),
        "volume_ratio": volume_ratio,
        "trend": trend,
        "high_60d": _round(max(closes[-60:]), 3) if len(closes) >= 60 else _round(max(closes), 3),
        "low_60d": _round(min(closes[-60:]), 3) if len(closes) >= 60 else _round(min(closes), 3),
    }


# ========== 市场热门 / 轮动板块（独立于关注分组）==========


MARKET_BOARD_CACHE: dict[str, Any] = {
    "data": None,
    "fetched_at": None,
}
MARKET_BOARD_CACHE_TTL_SECONDS = 5 * 60
ETF_NON_EQUITY_KEYWORDS = (
    "货币",
    "现金",
    "保证金",
    "国债",
    "政金债",
    "信用债",
    "公司债",
    "短债",
    "中短债",
    "同业存单",
    "可转债",
    "债券",
)
ETF_BOARD_ALIASES: dict[str, list[str]] = {
    "AI": ["AI", "人工智能", "智能", "云计算", "软件", "计算机", "通信"],
    "CPO": ["CPO", "光模块", "通信", "5G"],
    "光模块": ["光模块", "CPO", "通信", "5G", "云计算", "人工智能"],
    "算力": ["算力", "云计算", "人工智能", "通信", "计算机"],
    "人工智能": ["人工智能", "AI", "智能", "云计算", "软件", "计算机", "机器人"],
    "机器人": ["机器人", "智能机器", "高端装备", "机械"],
    "低空经济": ["低空", "航空", "军工", "无人机"],
    "半导体": ["半导体", "芯片", "集成电路", "科创芯片", "电子"],
    "芯片": ["芯片", "半导体", "集成电路", "科创芯片"],
    "消费电子": ["消费电子", "电子", "智能", "苹果"],
    "汽车": ["汽车", "新能源车", "智能车", "智能汽车"],
    "电池": ["电池", "锂电", "新能源车", "新能源"],
    "光伏": ["光伏", "新能源", "电力设备"],
    "储能": ["储能", "新能源", "电力设备"],
    "风电": ["风电", "新能源", "电力设备"],
    "军工": ["军工", "国防", "航空", "航天"],
    "创新药": ["创新药", "医药", "生物医药", "医疗"],
    "医疗": ["医疗", "医药", "生物医药"],
    "券商": ["券商", "证券", "金融"],
    "证券": ["证券", "券商", "金融"],
    "金融": ["金融", "证券", "券商", "银行", "保险"],
    "银行": ["银行", "金融"],
    "医药": ["医药", "医疗", "创新药", "生物医药"],
    "电子": ["电子", "消费电子", "半导体", "芯片"],
    "新能源": ["新能源", "光伏", "储能", "风电", "电池", "新能源车"],
    "有色": ["有色", "有色金属", "稀土", "黄金"],
    "黄金": ["黄金", "有色", "贵金属"],
    "煤炭": ["煤炭", "能源"],
    "化工": ["化工", "基础化工", "新材料"],
    "白酒": ["白酒", "酒", "食品饮料", "消费"],
    "游戏": ["游戏", "传媒"],
}


def _board_index_kline_industry(name: str) -> Any:
    import akshare as ak
    return ak.stock_board_industry_index_em(symbol=name, period="daily")


def _board_index_kline_concept(name: str) -> Any:
    import akshare as ak
    return ak.stock_board_concept_hist_em(symbol=name, period="daily")


def _normalize_board_name_field(item: dict[str, Any]) -> str:
    return str(item.get("板块名称") or item.get("板块") or item.get("name") or "").strip()


def _normalize_board_change_pct(item: dict[str, Any]) -> float | None:
    return _num(item.get("涨跌幅") or item.get("change_pct"))


async def _fetch_board_index_metrics(name: str, board_type: str) -> dict[str, Any]:
    """拉取板块指数日 K，计算 5/20 日涨幅、量比"""
    fetcher = _board_index_kline_industry if board_type == "industry" else _board_index_kline_concept
    try:
        df = await asyncio.to_thread(fetcher, name)
    except Exception as e:
        logger.info(f"板块指数 K 线失败 [{board_type}] {name}: {e}")
        return {"return_5d": None, "return_20d": None, "volume_ratio": None}
    if df is None or getattr(df, "empty", True):
        return {"return_5d": None, "return_20d": None, "volume_ratio": None}
    rows: list[tuple[date, float | None, float | None]] = []
    for _, row in df.iterrows():
        trade_date = _parse_trade_date(row.get("日期") or row.get("trade_date") or row.get("date"))
        if trade_date is None:
            continue
        c = _num(row.get("收盘") or row.get("close"))
        v = _num(row.get("成交量") or row.get("volume"))
        rows.append((trade_date, c, v))
    rows.sort(key=lambda item: item[0])
    closes = [c for _, c, _ in rows if c is not None]
    volumes = [v for _, _, v in rows if v is not None]
    r5 = _period_return(closes, 5)
    r20 = _period_return(closes, 20)
    vr = None
    if len(volumes) >= 21 and volumes[-1] is not None:
        avg = _avg(volumes[-21:-1])
        if avg:
            vr = _round(volumes[-1] / avg, 2)
    return {"return_5d": r5, "return_20d": r20, "volume_ratio": vr}


async def _fetch_market_boards_raw() -> tuple[list[dict[str, Any]], list[str]]:
    """直接调 push2delay.eastmoney.com 拉行业/概念板块快照，不依赖 AKShare board 封装。"""
    gaps: list[str] = []
    boards: list[dict[str, Any]] = []

    _BOARD_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
    _BOARD_PARAMS_BASE = {
        "pn": "1", "pz": "200", "po": "1", "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f62,f104,f105,f128",
    }
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/center/boardlist.html",
    }

    def _fetch_boards_sync(fs: str) -> list[dict[str, Any]]:
        import requests as _req
        params = dict(_BOARD_PARAMS_BASE, fs=fs)
        resp = _req.get(_BOARD_URL, params=params, headers=_HEADERS, timeout=12)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        items = data.get("diff") or []
        return items

    def _parse_items(items: list[dict[str, Any]], board_type: str) -> list[dict[str, Any]]:
        result = []
        for item in items:
            name = str(item.get("f14") or "").strip()
            if not name:
                continue
            result.append({
                "name": name,
                "code": str(item.get("f12") or "").strip(),
                "board_type": board_type,
                "change_pct": _num(item.get("f3")),
                "turnover": _num(item.get("f6")),
                "leading_stock": str(item.get("f128") or "").strip() or None,
                # 额外字段用于轮动判断
                "volume_ratio": _num(item.get("f10")),
                "capital_inflow": _num(item.get("f62")),
                "rise_count": int(item.get("f104") or 0),
                "fall_count": int(item.get("f105") or 0),
            })
        return result

    try:
        items = await asyncio.to_thread(_fetch_boards_sync, "m:90 t:2 f:!50")
        boards.extend(_parse_items(items, "industry"))
    except Exception as e:
        gaps.append(f"行业板块快照获取失败：{e}")

    try:
        items = await asyncio.to_thread(_fetch_boards_sync, "m:90 t:3 f:!50")
        boards.extend(_parse_items(items, "concept"))
    except Exception as e:
        gaps.append(f"概念板块快照获取失败：{e}")

    return boards, gaps


async def _fetch_market_boards(top_hot: int = 8, top_rotation: int = 8) -> dict[str, Any]:
    """采集市场热门 + 可能轮动板块（融合行业 + 概念，5 分钟缓存）"""
    cached_at: datetime | None = MARKET_BOARD_CACHE.get("fetched_at")
    cached_data = MARKET_BOARD_CACHE.get("data")
    cache_fresh = (
        cached_data
        and cached_at
        and (datetime.now() - cached_at).total_seconds() <= MARKET_BOARD_CACHE_TTL_SECONDS
    )
    # 仅当缓存有效且非空时才直接复用，避免空结果长时间留在缓存里
    if cache_fresh and (cached_data.get("hot_boards") or cached_data.get("rotation_boards")):
        return cached_data

    boards, gaps = await _fetch_market_boards_raw()
    if not boards:
        payload = {
            "hot_boards": [],
            "rotation_boards": [],
            "early_signals": [],
            "data_gaps": gaps or ["行业/概念板块快照均不可用"],
            "fetched_at": _now_iso(),
        }
        # 不写入缓存，便于下次重试
        return payload

    boards.sort(key=lambda b: (b.get("change_pct") if b.get("change_pct") is not None else -999), reverse=True)

    # 热门板块：当日涨幅 TOP N，快照自带量比和资金流向，无需再拉 K 线
    hot_boards: list[dict[str, Any]] = []
    for b in boards[:top_hot]:
        hot_boards.append({
            "name": b["name"],
            "code": b.get("code"),
            "board_type": b.get("board_type"),
            "change_pct": b.get("change_pct"),
            "volume_ratio": b.get("volume_ratio"),
            "capital_inflow": b.get("capital_inflow"),
            "leading_stock": b.get("leading_stock"),
            "turnover": b.get("turnover"),
            "rise_count": b.get("rise_count"),
            "fall_count": b.get("fall_count"),
            "return_5d": None,   # push2his blocked；留空不影响展示
            "return_20d": None,
            "reason": _hot_board_reason(b),
        })

    # 可能轮动板块：量比 > 1.2 且主力净流入 > 0，但涨幅相对落后（今日尚未大涨）
    # 这些板块可能是资金悄悄埋伏，下一轮启动候选
    rotation_boards: list[dict[str, Any]] = []
    early_signals: list[str] = []
    top_change = boards[0].get("change_pct") or 0 if boards else 0
    for b in boards:
        cp = b.get("change_pct") or 0
        vr = b.get("volume_ratio") or 0
        inflow = b.get("capital_inflow") or 0
        rise = b.get("rise_count") or 0
        fall = b.get("fall_count") or 0
        # 量比放大 + 主力净流入 + 涨幅未超过当日最大涨幅的 60%
        if vr > 1.2 and inflow > 0 and 0 < cp < top_change * 0.6:
            rotation_boards.append({
                "name": b["name"],
                "board_type": b.get("board_type"),
                "change_pct": cp,
                "volume_ratio": _round(vr, 2),
                "capital_inflow": inflow,
                "rise_count": rise,
                "fall_count": fall,
                "return_5d": None,
                "return_20d": None,
                "rotation_type": "rotating_in",
                "reason": f"量比 {vr}，主力净流入 {_round(inflow / 1e8, 2)}亿，今日涨幅 {cp}% 尚低，资金可能提前布局",
            })
        # 早期信号：量比高但今日微跌（资金试探性买入？）
        if vr > 1.5 and -1 < cp < 0 and inflow > 0:
            early_signals.append(
                f"【{b['name']}】今日微跌 {cp}% 但量比达 {vr}，主力净流入 {_round(inflow / 1e8, 2)}亿，疑似底部试探"
            )

    rotation_boards.sort(key=lambda x: (x.get("volume_ratio") or 0), reverse=True)
    rotation_boards = rotation_boards[:top_rotation]

    payload = {
        "hot_boards": hot_boards,
        "rotation_boards": rotation_boards,
        "early_signals": early_signals[:8],
        "data_gaps": gaps,
        "fetched_at": _now_iso(),
    }
    MARKET_BOARD_CACHE["data"] = payload
    MARKET_BOARD_CACHE["fetched_at"] = datetime.now()
    return payload


def _hot_board_reason(board: dict[str, Any]) -> str:
    parts = []
    cp = board.get("change_pct")
    if cp is not None:
        parts.append(f"当日 {('+' if cp > 0 else '')}{cp}%")
    vr = board.get("volume_ratio")
    if vr is not None:
        parts.append(f"量比 {vr}")
    inflow = board.get("capital_inflow")
    if inflow is not None:
        parts.append(f"主力净流入 {_round(inflow / 1e8, 2)}亿")
    rise = board.get("rise_count")
    fall = board.get("fall_count")
    if rise is not None and fall is not None:
        parts.append(f"涨{rise}跌{fall}")
    if board.get("leading_stock"):
        parts.append(f"领涨 {board['leading_stock']}")
    return "、".join(parts) if parts else "暂无足够数据"


def _fallback_match_etfs_for_board(
    board: dict[str, Any],
    watch_etfs: list[dict[str, Any]],
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """无 LLM 时的关键词匹配：板块名 ↔ ETF name / sector"""
    name = (board.get("name") or "").strip()
    if not name:
        return []
    keywords: list[str] = [name]
    # 行业板块名末尾常带「设备」「材料」等冗余词，提取 2 字内核更易命中
    if len(name) >= 4:
        keywords.append(name[:2])
    matched: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for etf in watch_etfs:
        if etf["code"] in seen_codes:
            continue
        haystack = f"{etf.get('name') or ''} {etf.get('sector') or ''}"
        if any(kw and kw in haystack for kw in keywords):
            matched.append({
                "code": etf["code"],
                "name": etf.get("name"),
                "sector": etf.get("sector"),
                "current_price": etf.get("current_price"),
                "trend": etf.get("trend"),
                "score": etf.get("score"),
                "is_watched": True,
                "match_reason": f"名称/分组包含「{keywords[0]}」",
            })
            seen_codes.add(etf["code"])
    matched.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return matched[:top_n]


def _strip_board_suffix(name: str) -> str:
    text = str(name or "").strip()
    for suffix in ("概念", "板块", "行业", "指数"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]
    return text.strip()


def _weighted_board_terms(board_name: str) -> list[tuple[str, float]]:
    name = str(board_name or "").strip()
    compact = _strip_board_suffix(name)
    weighted: dict[str, float] = {}

    def add(term: str | None, weight: float) -> None:
        term = str(term or "").strip()
        if len(term) < 2:
            return
        weighted[term] = max(weighted.get(term, 0), weight)

    add(name, 96)
    add(compact, 92)
    upper_name = name.upper()
    for key, aliases in ETF_BOARD_ALIASES.items():
        key_upper = key.upper()
        if key_upper in upper_name or upper_name in key_upper:
            for alias in aliases:
                add(alias, 82)

    for suffix in ("设备", "材料", "服务", "制造", "开发", "应用", "产业", "经济"):
        if compact.endswith(suffix) and len(compact) > len(suffix) + 1:
            add(compact[: -len(suffix)], 68)
    if len(compact) >= 4:
        add(compact[:3], 62)
        add(compact[:2], 58)
    return sorted(weighted.items(), key=lambda item: item[1], reverse=True)


def _etf_relevance_for_board(board: dict[str, Any], etf_name: str, fund_name: str | None = None) -> tuple[float, str | None]:
    board_name = str(board.get("name") or "").strip()
    haystack = f"{etf_name or ''} {fund_name or ''}".upper()
    best_score = 0.0
    best_term: str | None = None
    for term, base_score in _weighted_board_terms(board_name):
        if term.upper() in haystack:
            score = min(100.0, base_score + min(len(term), 4))
            if score > best_score:
                best_score = score
                best_term = term
    return best_score, best_term


def _is_non_equity_etf_name(name: str, matched_term: str | None) -> bool:
    if matched_term and matched_term in name:
        return False
    return any(keyword in name for keyword in ETF_NON_EQUITY_KEYWORDS)


def _score_liquidity(amount: float | None) -> float:
    if amount is None:
        return 45.0
    if amount >= 1_000_000_000:
        return 92.0
    if amount >= 300_000_000:
        return 78.0
    if amount >= 100_000_000:
        return 65.0
    if amount >= 30_000_000:
        return 48.0
    return 28.0


def _score_market_timing(change_pct: float | None, is_rotation_board: bool) -> float:
    if change_pct is None:
        return 50.0
    if is_rotation_board:
        if 0 <= change_pct <= 3:
            return 82.0
        if 3 < change_pct <= 6:
            return 70.0
        if -2 <= change_pct < 0:
            return 58.0
        if change_pct > 8:
            return 42.0
        return 50.0
    if change_pct < -3:
        return 30.0
    if change_pct < 0:
        return 45.0
    if change_pct <= 5:
        return 62.0 + change_pct * 5
    if change_pct <= 9:
        return 84.0
    return 70.0


def _score_discount(discount_rate: float | None) -> float:
    if discount_rate is None:
        return 50.0
    abs_discount = abs(discount_rate)
    if abs_discount <= 0.5:
        return 82.0
    if abs_discount <= 1:
        return 68.0
    if discount_rate > 2:
        return 28.0
    if discount_rate > 1:
        return 42.0
    return 58.0


def _score_scale(estimated_nav_value: float | None) -> float:
    if estimated_nav_value is None:
        return 50.0
    if estimated_nav_value >= 10_000_000_000:
        return 88.0
    if estimated_nav_value >= 3_000_000_000:
        return 72.0
    if estimated_nav_value >= 1_000_000_000:
        return 60.0
    if estimated_nav_value >= 300_000_000:
        return 45.0
    return 30.0


def _recommend_market_etfs_for_board(
    board: dict[str, Any],
    spot: dict[str, dict[str, Any]],
    fund_daily: dict[str, dict[str, Any]],
    etf_scale: dict[str, dict[str, Any]],
    excluded_codes: set[str],
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """关注列表无匹配时，从全市场真实 ETF 快照中按相关性和交易质量筛选替代候选。"""
    if not spot:
        return []
    is_rotation_board = bool(board.get("rotation_type"))
    candidates: list[dict[str, Any]] = []
    for code, quote in spot.items():
        clean_code = _normalize_code(code)
        if not clean_code or clean_code in excluded_codes:
            continue
        fund_info = fund_daily.get(clean_code) or {}
        name = str(quote.get("name") or fund_info.get("fund_name") or "").strip()
        if not name:
            continue
        relevance, matched_term = _etf_relevance_for_board(board, name, fund_info.get("fund_name"))
        if relevance < 58 or _is_non_equity_etf_name(name, matched_term):
            continue

        amount = _num(quote.get("amount"))
        funds = _funds_payload(clean_code, fund_daily, etf_scale)
        liquidity_score = _score_liquidity(amount)
        timing_score = _score_market_timing(_num(quote.get("change_pct")), is_rotation_board)
        discount_score = _score_discount(_num(funds.get("discount_rate")))
        scale_score = _score_scale(_num(funds.get("estimated_nav_value")))
        total_score = (
            relevance * 0.42
            + liquidity_score * 0.25
            + timing_score * 0.18
            + discount_score * 0.10
            + scale_score * 0.05
        )
        reason_parts = [
            f"全市场ETF名称匹配「{matched_term or _strip_board_suffix(str(board.get('name') or ''))}」",
            f"成交额 {_money_text(amount)}",
        ]
        change_pct = _num(quote.get("change_pct"))
        if change_pct is not None:
            reason_parts.append(f"当日涨跌幅 {_pct_basis(change_pct)}")
        discount_rate = _num(funds.get("discount_rate"))
        if discount_rate is not None:
            reason_parts.append(f"折溢价 {_pct_basis(discount_rate)}")
        estimated_nav_value = _num(funds.get("estimated_nav_value"))
        if estimated_nav_value is not None:
            reason_parts.append(f"规模估算 {_money_text(estimated_nav_value)}")
        candidates.append({
            "code": clean_code,
            "name": name,
            "sector": board.get("name"),
            "current_price": _round(_num(quote.get("price")), 3),
            "change_pct": change_pct,
            "amount": amount,
            "score": _round(total_score, 1),
            "is_watched": False,
            "match_reason": "；".join(reason_parts),
            "source": "market_etf_spot",
        })

    candidates.sort(key=lambda item: (item.get("score") or 0, item.get("amount") or 0), reverse=True)
    return candidates[:top_n]


async def _llm_match_boards_to_etfs(
    llm: LLMClient,
    boards: list[dict[str, Any]],
    watch_etfs: list[dict[str, Any]],
    purpose: str,
) -> dict[str, list[dict[str, Any]]]:
    """让 LLM 把每个板块映射到关注列表里的 ETF"""
    if not boards or not watch_etfs:
        return {}
    prompt = (
        "你是 ETF 投研助理。请为下列【市场板块】从用户【关注 ETF 列表】中挑出最贴合的标的，"
        "如果关注列表里没有符合该板块的 ETF，返回空数组。"
        "禁止编造代码或推荐不在列表中的 ETF。严格输出 JSON："
        '{"matches": [{"board": "板块名", "etfs": [{"code":"...","reason":"..."}]}]}'
        f"\n用途说明：{purpose}"
    )
    ctx = {
        "boards": [
            {
                "name": b.get("name"),
                "board_type": b.get("board_type"),
                "change_pct": b.get("change_pct"),
                "return_5d": b.get("return_5d"),
                "return_20d": b.get("return_20d"),
                "leading_stock": b.get("leading_stock"),
            }
            for b in boards
        ],
        "watch_etfs": [
            {
                "code": e["code"],
                "name": e.get("name"),
                "sector": e.get("sector"),
                "trend": e.get("trend"),
                "score": e.get("score"),
            }
            for e in watch_etfs
        ],
    }
    try:
        raw = await llm.chat_json(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)},
            ],
            temperature=0.1,
            max_tokens=1500,
        )
    except Exception as e:
        logger.warning(f"LLM 板块匹配失败：{e}")
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    code_to_etf = {e["code"]: e for e in watch_etfs}
    for m in (raw.get("matches") or []):
        board_name = str(m.get("board") or "").strip()
        if not board_name:
            continue
        picks: list[dict[str, Any]] = []
        for etf in (m.get("etfs") or []):
            code = _normalize_code(etf.get("code"))
            if not code or code not in code_to_etf:
                continue
            base = code_to_etf[code]
            picks.append({
                "code": code,
                "name": base.get("name"),
                "sector": base.get("sector"),
                "current_price": base.get("current_price"),
                "trend": base.get("trend"),
                "score": base.get("score"),
                "is_watched": True,
                "match_reason": str(etf.get("reason") or "").strip() or "LLM 研判与板块相关",
            })
        result[board_name] = picks
    return result


async def _attach_etf_recommendations(
    llm: LLMClient | None,
    boards: list[dict[str, Any]],
    watch_etfs: list[dict[str, Any]],
    purpose: str,
    market_spot: dict[str, dict[str, Any]] | None = None,
    fund_daily: dict[str, dict[str, Any]] | None = None,
    etf_scale: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """把每个 board 加上 recommended_etfs；关注列表无匹配时回退到全市场 ETF 优选。"""
    if not boards:
        return []
    matches: dict[str, list[dict[str, Any]]] = {}
    if llm is not None and llm.is_available():
        matches = await _llm_match_boards_to_etfs(llm, boards, watch_etfs, purpose)

    enriched: list[dict[str, Any]] = []
    watch_codes: set[str] = set()
    for etf in watch_etfs:
        code = _normalize_code(etf.get("code"))
        if code:
            watch_codes.add(code)
    for b in boards:
        name = b.get("name") or ""
        picks = matches.get(name)
        if not picks:
            picks = _fallback_match_etfs_for_board(b, watch_etfs)
        recommendation_source = "watchlist" if picks else "none"
        if not picks:
            picks = _recommend_market_etfs_for_board(
                b,
                market_spot or {},
                fund_daily or {},
                etf_scale or {},
                excluded_codes=watch_codes,
            )
            recommendation_source = "market_scan" if picks else "none"
        item = dict(b)
        item["recommended_etfs"] = picks
        item["recommendation_source"] = recommendation_source
        enriched.append(item)
    return enriched


# ========== 板块轮动检测（关注分组/单支 ETF 两种模式）==========


def _detect_sector_rotation(per_etf: list[dict[str, Any]]) -> dict[str, Any]:
    """对比各板块 ETF 5/20日涨幅，识别轮入/轮出和早期信号。
    未配置分组标签时，自动降级为单支 ETF 维度检测。"""

    # 判断是否有有效分组标签
    meaningful_sectors = {
        item.get("sector") for item in per_etf
        if item.get("sector") and item.get("sector") != "未分类"
    }
    use_individual = len(meaningful_sectors) <= 1

    if use_individual:
        # 无分组模式：每支 ETF 独立作为检测单元
        sector_stats: list[dict[str, Any]] = []
        rotating_in: list[dict[str, Any]] = []
        rotating_out: list[dict[str, Any]] = []
        early_signals: list[str] = []
        for item in per_etf:
            t = item.get("technicals") or {}
            r5 = t.get("return_5d")
            r20 = t.get("return_20d")
            vr = t.get("volume_ratio")
            label = item.get("name") or item.get("code", "")
            stat: dict[str, Any] = {
                "sector": label,
                "etf_count": 1,
                "avg_return_5d": _round(r5, 2),
                "avg_return_20d": _round(r20, 2),
                "avg_volume_ratio": _round(vr, 2),
            }
            sector_stats.append(stat)
            if r5 is None or r20 is None:
                continue
            if r5 > 0 and r5 > r20 and (vr or 0) > 1.1:
                rotating_in.append(stat)
            if r5 < 0 and r5 < r20:
                rotating_out.append(stat)
            if r20 < -3 and r5 > 0 and (vr or 0) > 1.2:
                early_signals.append(
                    f"【{label}】20日累计{r20}%下跌后5日转涨{r5}%，量比{vr}，疑似底部反转启动"
                )
        rotating_in.sort(key=lambda x: x.get("avg_return_5d") or 0, reverse=True)
        rotating_out.sort(key=lambda x: x.get("avg_return_5d") or 0)
        return {
            "sector_stats": sector_stats,
            "rotating_in": rotating_in[:5],
            "rotating_out": rotating_out[:5],
            "early_signals": early_signals,
        }

    # 有分组模式：按 sector 聚合
    sector_map: dict[str, list[dict[str, Any]]] = {}
    for item in per_etf:
        sector = item.get("sector") or "其他"
        sector_map.setdefault(sector, []).append(item)

    sector_stats_grouped: list[dict[str, Any]] = []
    for sector, items in sector_map.items():
        r5 = [i["technicals"]["return_5d"] for i in items if i["technicals"].get("return_5d") is not None]
        r20 = [i["technicals"]["return_20d"] for i in items if i["technicals"].get("return_20d") is not None]
        vr = [i["technicals"]["volume_ratio"] for i in items if i["technicals"].get("volume_ratio") is not None]
        sector_stats_grouped.append({
            "sector": sector,
            "etf_count": len(items),
            "avg_return_5d": _round(_avg(r5) if r5 else None, 2),
            "avg_return_20d": _round(_avg(r20) if r20 else None, 2),
            "avg_volume_ratio": _round(_avg(vr) if vr else None, 2),
        })

    rotating_in_g: list[dict[str, Any]] = []
    rotating_out_g: list[dict[str, Any]] = []
    early_signals_g: list[str] = []
    for s in sector_stats_grouped:
        r5 = s.get("avg_return_5d")
        r20 = s.get("avg_return_20d")
        vr = s.get("avg_volume_ratio")
        if r5 is None or r20 is None:
            continue
        if r5 > 0 and r5 > r20 and (vr or 0) > 1.1:
            rotating_in_g.append(s)
        if r5 < 0 and r5 < r20:
            rotating_out_g.append(s)
        if r20 < -3 and r5 > 0 and (vr or 0) > 1.2:
            early_signals_g.append(
                f"【{s['sector']}】20日累计{r20}%下跌后5日转涨{r5}%，量比{vr}，疑似底部反转启动"
            )

    rotating_in_g.sort(key=lambda x: x.get("avg_return_5d") or 0, reverse=True)
    rotating_out_g.sort(key=lambda x: x.get("avg_return_5d") or 0)

    return {
        "sector_stats": sector_stats_grouped,
        "rotating_in": rotating_in_g[:5],
        "rotating_out": rotating_out_g[:5],
        "early_signals": early_signals_g,
    }


# ========== 新闻情绪关联 ==========


async def _fetch_sector_news(db: AsyncSession, sectors: list[str], days: int = 7) -> dict[str, list[dict[str, Any]]]:
    """按板块关键词从已入库 NewsEvent 中匹配近期资讯"""
    if not sectors:
        return {}
    since = datetime.now() - timedelta(days=days)
    rows = (
        await db.execute(
            select(NewsEvent)
            .where(NewsEvent.publish_time >= since)
            .order_by(desc(NewsEvent.publish_time))
            .limit(500)
        )
    ).scalars().all()
    result: dict[str, list[dict[str, Any]]] = {sector: [] for sector in sectors}
    for row in rows:
        text = f"{row.title or ''} {row.content or ''}"
        for sector in sectors:
            if sector and sector in text:
                if len(result[sector]) < 5:
                    result[sector].append({
                        "title": row.title,
                        "publish_time": row.publish_time.isoformat(timespec="seconds") if row.publish_time else None,
                        "sentiment": row.sentiment,
                        "event_type": row.event_type,
                        "source": row.source,
                    })
    return result


def _score_sector_sentiment(news_list: list[dict[str, Any]]) -> float:
    if not news_list:
        return 50.0
    score = 50.0
    for n in news_list:
        s = n.get("sentiment")
        if s == "positive":
            score += 6
        elif s == "negative":
            score -= 6
    return max(0.0, min(100.0, score))


# ========== 综合评分（规则化）==========


def _score_technical(t: dict[str, Any]) -> float:
    score = 50.0
    trend = t.get("trend")
    if trend == "up":
        score += 15
    elif trend == "down":
        score -= 15
    macd_hist = (t.get("macd") or {}).get("hist")
    if macd_hist is not None:
        if macd_hist > 0:
            score += 8
        else:
            score -= 5
    rsi = t.get("rsi14")
    if rsi is not None:
        if 50 <= rsi <= 70:
            score += 8
        elif rsi > 80:
            score -= 8
        elif rsi < 30:
            score += 3  # 超卖反转候选
    r5 = t.get("return_5d") or 0
    if r5 > 0:
        score += min(r5, 10)
    else:
        score += max(r5, -10)
    return max(0.0, min(100.0, score))


def _score_volume(t: dict[str, Any]) -> float:
    vr = t.get("volume_ratio")
    if vr is None:
        return 50.0
    if vr > 1.5:
        return 75.0
    if vr > 1.2:
        return 65.0
    if vr < 0.7:
        return 35.0
    return 50.0


def _score_fund_flow(item: dict[str, Any]) -> float:
    quote = item.get("quote") or {}
    funds = item.get("funds") or {}
    score = 50.0

    amount = _num(quote.get("amount"))
    if amount is not None:
        if amount >= 1_000_000_000:
            score += 12
        elif amount >= 300_000_000:
            score += 8
        elif amount < 30_000_000:
            score -= 8

    turnover = _num(quote.get("turnover_rate"))
    if turnover is not None:
        if 1 <= turnover <= 8:
            score += 6
        elif turnover > 15:
            score -= 6
        elif turnover < 0.2:
            score -= 5

    share_delta_pct = _num(funds.get("share_delta_pct"))
    if share_delta_pct is not None:
        if share_delta_pct >= 3:
            score += 10
        elif share_delta_pct >= 1:
            score += 5
        elif share_delta_pct <= -3:
            score -= 10
        elif share_delta_pct <= -1:
            score -= 5

    discount_rate = _num(funds.get("discount_rate"))
    if discount_rate is not None:
        if abs(discount_rate) <= 0.5:
            score += 5
        elif discount_rate > 2:
            score -= 10
        elif discount_rate > 1:
            score -= 5
        elif discount_rate < -1:
            score += 3

    return max(0.0, min(100.0, score))


def _score_valuation(t: dict[str, Any]) -> float:
    """以最近60日价格区间内位置作为估值代理（位置越低越便宜）"""
    high = t.get("high_60d")
    low = t.get("low_60d")
    latest = t.get("latest_close")
    if not (high and low and latest) or high == low:
        return 50.0
    pos = (latest - low) / (high - low)
    # 位置 0-30%：80 分；30-50%：65；50-70%：50；70-90%：35；>90%：20
    if pos < 0.3:
        return 80.0
    if pos < 0.5:
        return 65.0
    if pos < 0.7:
        return 50.0
    if pos < 0.9:
        return 35.0
    return 20.0


def _decide_action(score: float, trend: str) -> str:
    if score >= 75 and trend == "up":
        return "buy"
    if score >= 65:
        return "add" if trend == "up" else "watch"
    if score >= 50:
        return "hold"
    if score >= 40:
        return "watch"
    return "reduce" if trend == "down" else "avoid"


def _rule_analysis_one(item: dict[str, Any], sector_score: float, news_score: float) -> dict[str, Any]:
    t = item["technicals"]
    quote = item.get("quote") or {}
    current_price = t.get("latest_close")
    if current_price is None:
        current_price = quote.get("price")
    tech = _score_technical(t)
    vol = _score_volume(t)
    fund = _score_fund_flow(item)
    val = _score_valuation(t)
    total = tech * 0.25 + vol * 0.10 + fund * 0.15 + sector_score * 0.20 + news_score * 0.10 + val * 0.20
    action = _decide_action(total, t.get("trend") or "consolidation")
    return {
        "code": item["code"],
        "name": item.get("name"),
        "sector": item.get("sector"),
        "current_price": _round(current_price, 3),
        "trend": t.get("trend"),
        "scores": {
            "technical": _round(tech, 1),
            "volume": _round(vol, 1),
            "fund_flow": _round(fund, 1),
            "sector_rotation": _round(sector_score, 1),
            "news": _round(news_score, 1),
            "valuation": _round(val, 1),
        },
        "score": _round(total, 1),
        "action": action,
        "action_label": ACTION_LABELS.get(action, action),
    }


def _build_recommendations(per_etf_analysis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从分析结果中筛选 buy/add 信号，构造入场价/止盈/止损/仓位建议"""
    candidates = [a for a in per_etf_analysis if a.get("action") in ("buy", "add") and a.get("current_price")]
    candidates.sort(key=lambda x: x.get("score") or 0, reverse=True)
    top = candidates[:5]
    if not top:
        return []
    # 仓位分配：top 越靠前权重越大；总仓位上限 60%
    total_weight = sum((c.get("score") or 0) for c in top) or 1.0
    recommendations: list[dict[str, Any]] = []
    for c in top:
        price = c["current_price"]
        weight = (c.get("score") or 0) / total_weight
        position_pct = round(60 * weight, 1)
        recommendations.append({
            "code": c["code"],
            "name": c.get("name"),
            "sector": c.get("sector"),
            "action": c["action"],
            "action_label": c.get("action_label"),
            "score": c.get("score"),
            "current_price": price,
            "entry_price": _round(price * 0.99, 3),
            "target_price": _round(price * 1.08, 3),
            "stop_loss_price": _round(price * 0.95, 3),
            "position_pct": position_pct,
            "reason": f"综合评分 {c.get('score')}，{c.get('trend')} 趋势，板块/技术/量能资金多维共振",
        })
    return recommendations


def _summarize(hot_sectors: list[dict[str, Any]], rotation: dict[str, Any], recs: list[dict[str, Any]], etf_count: int) -> str:
    parts: list[str] = []
    if hot_sectors:
        names = "、".join(s["sector"] for s in hot_sectors[:3])
        parts.append(f"当前关注分组热度：{names}")
        if etf_count < 3:
            parts.append("关注 ETF 数量不足，分组排序仅供参考")
    if rotation.get("rotating_in"):
        names = "、".join(s["sector"] for s in rotation["rotating_in"][:3])
        parts.append(f"资金正在流入：{names}")
    if rotation.get("early_signals"):
        parts.append(f"轮动早期信号 {len(rotation['early_signals'])} 条，关注潜在反转板块")
    if recs:
        parts.append(f"备选买入 {len(recs)} 只 ETF，最高分 {recs[0]['name'] or recs[0]['code']}（{recs[0]['score']}）")
    parts.append(f"本次共分析 {etf_count} 只 ETF。")
    return "；".join(parts)


def _llm_prompt() -> str:
    return (
        "你是一名 ETF 板块轮动研究员。基于用户提供的真实 ETF K线/行情/板块统计/资讯数据，"
        "给出板块轮动方向研判、热门板块排序、买入备选建议（含入场价/止盈/止损/仓位）和风险提示。"
        "禁止编造未提供的数据。请严格输出 JSON，字段："
        "summary(摘要), hot_sectors(数组, 含sector/score/reason), "
        "rotation_forecast(数组, 含sector/direction[in/out]/confidence/reason), "
        "buy_suggestions(数组, 含code/name/sector/entry_price/target_price/stop_loss_price/position_pct/reason), "
        "risk_warnings(数组)。"
        "不要输出 data_gaps 字段，数据质量信息由系统规则处理。"
    )


def _sanitize_llm_buy_suggestions(
    suggestions: list[Any],
    known_etfs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    code_map = {item["code"]: item for item in known_etfs if item.get("code")}
    sanitized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        code = _normalize_code(item.get("code"))
        if not code or code in seen or code not in code_map:
            continue
        base = code_map[code]
        action = str(item.get("action") or "buy")
        if action not in ACTION_LABELS:
            action = "buy"
        sanitized.append({
            "code": code,
            "name": base.get("name"),
            "sector": base.get("sector"),
            "action": action,
            "action_label": ACTION_LABELS[action],
            "entry_price": _round(_num(item.get("entry_price")), 3),
            "target_price": _round(_num(item.get("target_price")), 3),
            "stop_loss_price": _round(_num(item.get("stop_loss_price")), 3),
            "position_pct": _round(_num(item.get("position_pct")), 1),
            "reason": str(item.get("reason") or "").strip() or "LLM 基于已提供数据补充建议",
        })
        seen.add(code)
    return sanitized


def _merge_llm_result(rule_result: dict[str, Any], llm_raw: dict[str, Any]) -> dict[str, Any]:
    merged = dict(rule_result)
    if llm_raw.get("summary"):
        merged["summary"] = llm_raw["summary"]
    if isinstance(llm_raw.get("hot_sectors"), list) and llm_raw["hot_sectors"]:
        merged.setdefault("rotation_signals", {})["llm_hot_sectors"] = llm_raw["hot_sectors"]
    if isinstance(llm_raw.get("rotation_forecast"), list):
        merged.setdefault("rotation_signals", {})["llm_forecast"] = llm_raw["rotation_forecast"]
    if isinstance(llm_raw.get("buy_suggestions"), list) and llm_raw["buy_suggestions"]:
        merged["llm_recommendations"] = _sanitize_llm_buy_suggestions(
            llm_raw["buy_suggestions"],
            merged.get("individual_analysis") or [],
        )
    if isinstance(llm_raw.get("risk_warnings"), list):
        merged["risk_warnings"] = llm_raw["risk_warnings"]
    # data_gaps 由规则层统一管理，不合并 LLM 生成的内容
    return merged


# ========== ETF 关注列表 API ==========


def _watch_payload(row: EtfWatchItem, quote: dict[str, Any] | None = None) -> dict[str, Any]:
    cost = _num(row.cost_price)
    qty = row.quantity or 0
    cost_amount = (cost * qty) if (cost and qty) else None
    current_price = quote.get("price") if quote else None
    market_value = (current_price * qty) if (current_price is not None and qty) else None
    unrealized_profit = (market_value - cost_amount) if (market_value is not None and cost_amount is not None) else None
    return_pct = (unrealized_profit / cost_amount * 100) if (unrealized_profit is not None and cost_amount) else None
    target = _num(row.target_price)
    stop = _num(row.stop_loss_price)
    if current_price is None:
        threshold_status = "data_missing"
    elif target is not None and current_price >= target:
        threshold_status = "take_profit"
    elif stop is not None and current_price <= stop:
        threshold_status = "stop_loss"
    elif not row.is_holding:
        threshold_status = "watch"
    else:
        threshold_status = "holding"
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name or (quote.get("name") if quote else None),
        "sector": row.sector,
        "is_holding": bool(row.is_holding),
        "cost_price": cost,
        "quantity": qty if qty else None,
        "target_price": target,
        "stop_loss_price": stop,
        "note": row.note,
        "status": row.status,
        "current_price": current_price,
        "change_pct": quote.get("change_pct") if quote else None,
        "cost_amount": _money(cost_amount),
        "market_value": _money(market_value),
        "unrealized_profit": _money(unrealized_profit),
        "unrealized_return_pct": _round(return_pct, 2),
        "threshold_status": threshold_status,
        "quote_source": "akshare_spot" if quote else None,
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
        "updated_at": row.updated_at.isoformat(timespec="seconds") if row.updated_at else None,
    }


@router.get("/watchlist")
async def list_etf_watchlist(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(EtfWatchItem)
            .where(EtfWatchItem.status == "active")
            .order_by(desc(EtfWatchItem.is_holding), desc(EtfWatchItem.updated_at))
        )
    ).scalars().all()
    spot = await _fetch_etf_spot_cached(wait_timeout=3.0) if rows else {}
    items = [_watch_payload(r, spot.get(r.code)) for r in rows]
    holdings = [i for i in items if i["is_holding"]]
    summary = {
        "total": len(items),
        "holding_count": len(holdings),
        "watch_only": len(items) - len(holdings),
        "total_market_value": _money(sum((i["market_value"] or 0) for i in holdings)),
        "total_cost": _money(sum((i["cost_amount"] or 0) for i in holdings)),
        "total_unrealized_profit": _money(sum((i["unrealized_profit"] or 0) for i in holdings)),
    }
    return {"items": items, "summary": summary}


@router.post("/watchlist")
async def add_etf_watch(req: EtfWatchAddRequest, db: AsyncSession = Depends(get_db)):
    code = _normalize_code(req.code)
    if not code:
        raise HTTPException(status_code=400, detail="ETF代码无效")
    exists = (
        await db.execute(select(EtfWatchItem).where(EtfWatchItem.code == code))
    ).scalar_one_or_none()
    if exists:
        if exists.status != "active":
            exists.status = "active"
        provided = req.model_fields_set
        # 覆盖更新
        if "name" in provided:
            exists.name = req.name
        if "sector" in provided:
            exists.sector = req.sector
        if "is_holding" in provided:
            exists.is_holding = bool(req.is_holding)
        if "cost_price" in provided:
            exists.cost_price = _dec(req.cost_price)
        if "quantity" in provided:
            exists.quantity = req.quantity
        if "target_price" in provided:
            exists.target_price = _dec(req.target_price)
        if "stop_loss_price" in provided:
            exists.stop_loss_price = _dec(req.stop_loss_price)
        if "note" in provided:
            exists.note = req.note
        await db.commit()
        await db.refresh(exists)
        return _watch_payload(exists)
    row = EtfWatchItem(
        code=code,
        name=req.name,
        sector=req.sector,
        is_holding=bool(req.is_holding),
        cost_price=_dec(req.cost_price),
        quantity=req.quantity,
        target_price=_dec(req.target_price),
        stop_loss_price=_dec(req.stop_loss_price),
        note=req.note,
        status="active",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _watch_payload(row)


@router.patch("/watchlist/{item_id}")
async def update_etf_watch(item_id: int, req: EtfWatchUpdateRequest, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(EtfWatchItem).where(EtfWatchItem.id == item_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="关注项不存在")
    provided = req.model_fields_set
    if "name" in provided:
        row.name = req.name
    if "sector" in provided:
        row.sector = req.sector
    if "is_holding" in provided:
        row.is_holding = bool(req.is_holding)
    if "cost_price" in provided:
        row.cost_price = _dec(req.cost_price)
    if "quantity" in provided:
        row.quantity = req.quantity
    if "target_price" in provided:
        row.target_price = _dec(req.target_price)
    if "stop_loss_price" in provided:
        row.stop_loss_price = _dec(req.stop_loss_price)
    if "note" in provided:
        row.note = req.note
    await db.commit()
    await db.refresh(row)
    return _watch_payload(row)


@router.delete("/watchlist/{item_id}")
async def remove_etf_watch(item_id: int, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(EtfWatchItem).where(EtfWatchItem.id == item_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="关注项不存在")
    row.status = "removed"
    await db.commit()
    return {"id": item_id, "status": "removed"}


# ========== ETF 分析核心流程 ==========


def _iso_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = _parse_trade_date(value)
    return parsed.isoformat() if parsed else None


def _funds_payload(
    code: str,
    fund_daily: dict[str, dict[str, Any]],
    etf_scale: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    daily = fund_daily.get(code) or {}
    scale = etf_scale.get(code) or {}
    shares = _num(scale.get("shares"))
    unit_nav = _num(daily.get("unit_nav"))
    estimated_nav_value = shares * unit_nav if shares is not None and unit_nav is not None else None
    source_parts = [s for s in (daily.get("source"), scale.get("source")) if s]
    return {
        "unit_nav": unit_nav,
        "accum_nav": _num(daily.get("accum_nav")),
        "nav_growth_pct": _num(daily.get("nav_growth_pct")),
        "market_price": _num(daily.get("market_price")),
        "discount_rate": _num(daily.get("discount_rate")),
        "shares": shares,
        "scale_date": _iso_date(scale.get("scale_date")),
        "prev_shares": _num(scale.get("prev_shares")),
        "prev_scale_date": _iso_date(scale.get("prev_scale_date")),
        "share_delta": _num(scale.get("share_delta")),
        "share_delta_pct": _num(scale.get("share_delta_pct")),
        "estimated_nav_value": _money(estimated_nav_value),
        "source": "+".join(source_parts) if source_parts else None,
    }


async def _analyze_one_etf(
    db: AsyncSession,
    item: EtfWatchItem,
    lookback_days: int,
    spot: dict[str, dict[str, Any]],
    fund_daily: dict[str, dict[str, Any]],
    etf_scale: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    code = item.code
    kline, kline_source = await _load_etf_kline(db, code, lookback_days)
    technicals = _compute_technicals(kline)
    quote = spot.get(code) or {}
    funds = _funds_payload(code, fund_daily, etf_scale)
    return {
        "code": code,
        "name": item.name or quote.get("name"),
        "sector": item.sector or "未分类",
        "is_holding": bool(item.is_holding),
        "cost_price": _num(item.cost_price),
        "quantity": item.quantity,
        "quote": {
            "price": quote.get("price") or technicals.get("latest_close"),
            "change_pct": quote.get("change_pct"),
            "amount": quote.get("amount"),
            "turnover_rate": quote.get("turnover_rate"),
        },
        "funds": funds,
        "technicals": technicals,
        "kline_count": len(kline),
        "kline_source": kline_source,
    }


def _pct_basis(value: float | None) -> str:
    if value is None:
        return "数据缺失，热度按 0% 计"
    sign = "+" if value > 0 else ""
    return f"{sign}{_round(value, 2)}%"


def _volume_basis(value: float | None) -> str:
    if value is None:
        return "数据缺失，热度按 1.0 计"
    return str(_round(value, 2))


def _hot_sectors_from_stats(
    sector_stats: list[dict[str, Any]],
    news_scores: dict[str, float],
    sector_news: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    hot: list[dict[str, Any]] = []
    for s in sector_stats:
        sector = s["sector"]
        r5_raw = s.get("avg_return_5d")
        r20_raw = s.get("avg_return_20d")
        vr_raw = s.get("avg_volume_ratio")
        r5 = r5_raw if r5_raw is not None else 0
        r20 = r20_raw if r20_raw is not None else 0
        vr = vr_raw if vr_raw is not None else 1.0
        ns = news_scores.get(sector, 50.0)
        news_count = len((sector_news or {}).get(sector, []))
        # 综合热度：短期表现 60%、量比 20%、资讯情绪 20%
        heat = 50 + r5 * 2 + (vr - 1) * 20
        heat = heat * 0.6 + (vr * 30) * 0.2 + ns * 0.2
        heat = max(0.0, min(100.0, heat))
        basis = [
            f"覆盖 ETF {s.get('etf_count') or 0} 只",
            f"5日平均涨幅 {_pct_basis(r5_raw)}",
            f"20日平均涨幅 {_pct_basis(r20_raw)}",
            f"平均量比 {_volume_basis(vr_raw)}",
            f"近7日匹配资讯 {news_count} 条，新闻情绪分 {_round(ns, 1)}",
        ]
        hot.append({
            "sector": sector,
            "score": _round(heat, 1),
            "etf_count": s.get("etf_count"),
            "avg_return_5d": r5_raw,
            "avg_return_20d": r20_raw,
            "avg_volume_ratio": vr_raw,
            "news_sentiment_score": ns,
            "news_count": news_count,
            "basis": basis,
            "reason": "；".join(basis),
        })
    hot.sort(key=lambda x: x.get("score") or 0, reverse=True)
    return hot


async def _run_etf_analysis_inner(
    db: AsyncSession,
    use_llm: bool,
    lookback_days: int,
    trigger_type: str,
    task_id: str,
) -> dict[str, Any]:
    started = time.time()
    rows = (
        await db.execute(
            select(EtfWatchItem)
            .where(EtfWatchItem.status == "active")
            .order_by(EtfWatchItem.created_at)
        )
    ).scalars().all()
    if not rows:
        raise ValueError("当前没有 active 的 ETF 关注项，请先添加 ETF")

    _set_task(task_id, progress=10, step=f"加载 {len(rows)} 只 ETF 行情")
    spot = await _fetch_etf_spot_cached(wait_timeout=20.0)

    _set_task(task_id, progress=18, step="加载 ETF 净值/折溢价/份额")
    fund_daily, scale_result = await asyncio.gather(
        _fetch_etf_fund_daily_cached(),
        _fetch_etf_scale_cached(),
    )
    etf_scale, scale_gaps = scale_result

    _set_task(task_id, progress=25, step="批量拉取 ETF K 线")
    per_etf: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(1)

    async def _wrapped(item: EtfWatchItem) -> dict[str, Any]:
        async with sem:
            return await _analyze_one_etf(db, item, lookback_days, spot, fund_daily, etf_scale)

    per_etf = await asyncio.gather(*[_wrapped(r) for r in rows])
    _set_task(task_id, progress=50, step="检测板块轮动信号")

    rotation = _detect_sector_rotation(per_etf)
    sectors = list({i["sector"] for i in per_etf if i.get("sector")})

    _set_task(task_id, progress=58, step="拉取市场行业/概念板块快照")
    market_boards = await _fetch_market_boards(top_hot=8, top_rotation=8)

    _set_task(task_id, progress=65, step="匹配板块资讯情绪")
    sector_news = await _fetch_sector_news(db, sectors, days=7)
    news_scores: dict[str, float] = {s: _score_sector_sentiment(sector_news.get(s, [])) for s in sectors}

    hot_sectors = _hot_sectors_from_stats(rotation["sector_stats"], news_scores, sector_news)
    sector_score_map = {h["sector"]: h["score"] for h in hot_sectors}

    _set_task(task_id, progress=75, step="规则化综合评分")
    individual: list[dict[str, Any]] = []
    for item in per_etf:
        sector = item.get("sector") or "未分类"
        sec_score = sector_score_map.get(sector, 50.0)
        nws_score = news_scores.get(sector, 50.0)
        analysis = _rule_analysis_one(item, sec_score, nws_score)
        analysis["technicals"] = item["technicals"]
        analysis["is_holding"] = item.get("is_holding")
        analysis["cost_price"] = item.get("cost_price")
        analysis["kline_source"] = item.get("kline_source")
        analysis["funds"] = item.get("funds")
        individual.append(analysis)

    recommendations = _build_recommendations(individual)

    data_gaps: list[str] = []
    no_kline = [a for a in individual if (a.get("technicals") or {}).get("latest_close") is None]
    if no_kline:
        codes = [a["code"] for a in no_kline]
        data_gaps.append(
            f"{len(no_kline)} 只 ETF 缺少 K 线数据，已跳过技术分析；可点击「补 K 线」重试。代码：{','.join(codes[:6])}{'...' if len(codes) > 6 else ''}"
        )
    stale_kline = [a for a in individual if a.get("kline_source") == "cache_stale"]
    if stale_kline:
        data_gaps.append(f"{len(stale_kline)} 只 ETF 使用本地历史 K 线缓存，远端数据源暂不可用")
    has_kline_gaps = bool(no_kline or stale_kline)
    if not spot:
        data_gaps.append("ETF 实时行情快照获取失败，使用 K 线最新价代替")
    if not fund_daily:
        error = FUND_DAILY_CACHE.get("error")
        data_gaps.append(f"ETF 净值/折溢价数据不可用{f'：{error}' if error else ''}")
    missing_funds = [a for a in individual if not ((a.get("funds") or {}).get("source"))]
    if missing_funds:
        data_gaps.append(f"{len(missing_funds)} 只 ETF 缺少净值/份额资金面数据，资金面评分使用可得行情代理")
    for gap in scale_gaps:
        data_gaps.append(gap)
    # 深交所份额变动说明：接口仅提供当日快照，无历史对比，属正常限制
    szse_no_delta = [
        a["code"] for a in individual
        if (a.get("funds") or {}).get("source")
        and (a.get("funds") or {}).get("share_delta") is None
        and not str(a.get("code", "")).startswith(("5", "6", "9"))
    ]
    if szse_no_delta:
        data_gaps.append(
            f"深交所 ETF 份额变动不可用（接口仅提供当日快照，无历史对比），受影响：{','.join(szse_no_delta[:6])}"
        )
    # 仅当配置了有效板块标签且仍未匹配到资讯时才提示
    has_real_sectors = any(
        i.get("sector") and i.get("sector") != "未分类" for i in per_etf
    )
    if has_real_sectors and not any(bool(items) for items in sector_news.values()):
        data_gaps.append("近 7 日未匹配到板块资讯，新闻情绪打分使用中性值")
    for gap in market_boards.get("data_gaps") or []:
        data_gaps.append(gap)

    rule_result: dict[str, Any] = {
        "summary": _summarize(hot_sectors, rotation, recommendations, len(per_etf)),
        "hot_sectors": hot_sectors,
        "rotation_signals": {
            "rotating_in": rotation["rotating_in"],
            "rotating_out": rotation["rotating_out"],
            "early_signals": rotation["early_signals"],
        },
        "recommendations": recommendations,
        "individual_analysis": individual,
        "has_kline_gaps": has_kline_gaps,
        "market_overview": {
            "etf_count": len(per_etf),
            "sector_count": len(sectors),
            "holding_count": sum(1 for i in per_etf if i.get("is_holding")),
            "kline_sources": {
                source: sum(1 for i in per_etf if i.get("kline_source") == source)
                for source in sorted({str(i.get("kline_source") or "unknown") for i in per_etf})
            },
            "fund_data_sources": {
                source: sum(1 for i in individual if ((i.get("funds") or {}).get("source") or "missing") == source)
                for source in sorted({str((i.get("funds") or {}).get("source") or "missing") for i in individual})
            },
            "sector_news_summary": sector_news,
        },
        "data_gaps": data_gaps,
        "risk_warnings": [
            "板块轮动具有不确定性，建议分批建仓",
            "ETF 跌破止损价后应果断离场",
            "宏观政策、流动性变化可能逆转短期信号",
        ],
        "source_policy": SOURCE_POLICY,
    }

    _set_task(task_id, progress=85, step="LLM 增强综合研判" if use_llm else "跳过 LLM 增强")
    llm_used = False
    llm_error: str | None = None
    final_result = rule_result
    llm_for_match: LLMClient | None = None
    if use_llm:
        llm = LLMClient()
        llm_for_match = llm
        try:
            if llm.is_available():
                ctx_for_llm = {
                    "summary_input": rule_result["summary"],
                    "hot_sectors": hot_sectors[:8],
                    "rotation_signals": rule_result["rotation_signals"],
                    "individual_analysis": [
                        {k: v for k, v in a.items() if k not in ("technicals",)} for a in individual
                    ],
                    "recommendations": recommendations,
                    "market_overview": {
                        "etf_count": len(per_etf),
                        "sector_count": len(sectors),
                    },
                }
                raw = await llm.chat_json(
                    [
                        {"role": "system", "content": _llm_prompt()},
                        {"role": "user", "content": json.dumps(ctx_for_llm, ensure_ascii=False, default=str)},
                    ],
                    temperature=0.2,
                    max_tokens=3000,
                )
                final_result = _merge_llm_result(rule_result, raw)
                llm_used = True
        except Exception as e:
            llm_error = str(e)
            logger.warning(f"ETF analysis LLM failed: {e}")
            final_result = dict(rule_result)
            existing = list(final_result.get("data_gaps") or [])
            existing.append(f"LLM 增强失败，仅使用规则化结果: {llm_error}")
            final_result["data_gaps"] = existing

    _set_task(task_id, progress=90, step="匹配市场板块到关注 ETF")
    # 用 individual 作为关注 ETF 的画像（包含 trend / score / current_price 等）
    market_hot_boards = await _attach_etf_recommendations(
        llm_for_match,
        market_boards.get("hot_boards") or [],
        individual,
        purpose="为热门板块从关注列表挑出可买入的 ETF",
        market_spot=spot,
        fund_daily=fund_daily,
        etf_scale=etf_scale,
    )
    market_rotation_boards = await _attach_etf_recommendations(
        llm_for_match,
        market_boards.get("rotation_boards") or [],
        individual,
        purpose="为可能轮动板块从关注列表挑出可埋伏的 ETF",
        market_spot=spot,
        fund_daily=fund_daily,
        etf_scale=etf_scale,
    )

    if llm_for_match is not None:
        try:
            await llm_for_match.close()
        except Exception:
            pass

    overview = dict(final_result.get("market_overview") or {})
    overview["market_hot_boards"] = market_hot_boards
    overview["market_rotation_boards"] = market_rotation_boards
    overview["market_early_signals"] = market_boards.get("early_signals") or []
    overview["market_boards_fetched_at"] = market_boards.get("fetched_at")
    overview["risk_warnings"] = final_result.get("risk_warnings") or []
    overview["has_kline_gaps"] = bool(final_result.get("has_kline_gaps"))
    final_result["market_overview"] = overview

    _set_task(task_id, progress=95, step="保存分析记录")
    record = EtfAnalysisRecord(
        task_id=task_id,
        analysis_time=datetime.now(),
        trigger_type=trigger_type,
        etf_count=len(per_etf),
        hot_sectors={"items": final_result.get("hot_sectors") or []},
        rotation_signals=final_result.get("rotation_signals") or {},
        recommendations={"items": final_result.get("recommendations") or [], "llm": final_result.get("llm_recommendations") or []},
        individual_analysis={"items": final_result.get("individual_analysis") or []},
        market_overview=final_result.get("market_overview") or {},
        summary=final_result.get("summary"),
        llm_used=llm_used,
        data_gaps=final_result.get("data_gaps") or [],
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    payload = _record_payload(record)
    payload["llm_error"] = llm_error
    payload["execution_time_ms"] = int((time.time() - started) * 1000)
    payload["risk_warnings"] = final_result.get("risk_warnings") or []
    return payload


def _record_payload(row: EtfAnalysisRecord) -> dict[str, Any]:
    overview = row.market_overview or {}
    return {
        "id": row.id,
        "task_id": row.task_id,
        "analysis_time": row.analysis_time.isoformat(timespec="seconds") if row.analysis_time else None,
        "trigger_type": row.trigger_type,
        "etf_count": row.etf_count,
        "summary": row.summary,
        "hot_sectors": (row.hot_sectors or {}).get("items") if isinstance(row.hot_sectors, dict) else (row.hot_sectors or []),
        "rotation_signals": row.rotation_signals or {},
        "recommendations": (row.recommendations or {}).get("items") if isinstance(row.recommendations, dict) else (row.recommendations or []),
        "llm_recommendations": (row.recommendations or {}).get("llm") if isinstance(row.recommendations, dict) else [],
        "individual_analysis": (row.individual_analysis or {}).get("items") if isinstance(row.individual_analysis, dict) else (row.individual_analysis or []),
        "market_overview": overview,
        "market_hot_boards": overview.get("market_hot_boards") or [],
        "market_rotation_boards": overview.get("market_rotation_boards") or [],
        "market_early_signals": overview.get("market_early_signals") or [],
        "market_boards_fetched_at": overview.get("market_boards_fetched_at"),
        "risk_warnings": overview.get("risk_warnings") or [],
        "llm_used": bool(row.llm_used),
        "data_gaps": row.data_gaps or [],
        "has_kline_gaps": bool(overview.get("has_kline_gaps")),
        "source_policy": SOURCE_POLICY,
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    }


async def _run_etf_analysis_task(task_id: str, params: dict[str, Any], session_factory) -> None:
    try:
        if ETF_ANALYSIS_LOCK.locked():
            running = _running_etf_task()
            running_id = running.get("task_id") if running else "unknown"
            raise RuntimeError(f"已有 ETF 分析任务运行中：{running_id}")
        async with ETF_ANALYSIS_LOCK:
            _set_task(task_id, status="running", progress=5, step="开始分析")
            async with session_factory() as db:
                payload = await _run_etf_analysis_inner(
                    db=db,
                    use_llm=bool(params.get("use_llm", True)),
                    lookback_days=int(params.get("lookback_days") or 120),
                    trigger_type=str(params.get("trigger_type") or "manual"),
                    task_id=task_id,
                )
                _set_task(
                    task_id,
                    status="completed",
                    progress=100,
                    step="分析完成",
                    result=payload,
                    record_id=payload.get("id"),
                )
    except Exception as e:
        logger.error(f"ETF analysis task {task_id} failed: {e}")
        _set_task(task_id, status="failed", progress=100, step="分析失败", error_message=str(e))


async def run_scheduled_etf_analysis(session_factory) -> dict[str, Any]:
    """供 AgentScheduler 在定时任务中调用"""
    running = _running_etf_task()
    if ETF_ANALYSIS_LOCK.locked() or running:
        return {
            "status": "skipped",
            "reason": "已有 ETF 分析任务运行中",
            "existing_task_id": running.get("task_id") if running else None,
        }
    task_id = f"etf_analysis_{uuid.uuid4().hex[:8]}"
    _set_task(task_id, status="queued", progress=0, step="定时触发", trigger_type="scheduled")
    try:
        async with ETF_ANALYSIS_LOCK:
            async with session_factory() as db:
                payload = await _run_etf_analysis_inner(
                    db=db, use_llm=True, lookback_days=120, trigger_type="scheduled", task_id=task_id,
                )
                _set_task(
                    task_id,
                    status="completed",
                    progress=100,
                    step="分析完成",
                    result=payload,
                    record_id=payload.get("id"),
                )
                return payload
    except Exception as e:
        logger.error(f"Scheduled ETF analysis failed: {e}")
        _set_task(task_id, status="failed", progress=100, step="分析失败", error_message=str(e))
        return {"error": str(e), "task_id": task_id}


# ========== ETF 分析任务 API ==========


@router.post("/analysis/run")
async def trigger_etf_analysis(
    req: EtfAnalysisRunRequest,
    background_tasks: BackgroundTasks,
    session_factory=Depends(get_session_factory),
):
    running = _running_etf_task()
    if ETF_ANALYSIS_LOCK.locked() or running:
        task = running or {}
        task["already_running"] = True
        task["step"] = task.get("step") or "已有任务运行中"
        return dict(task)
    task_id = f"etf_analysis_{uuid.uuid4().hex[:8]}"
    task = _set_task(
        task_id,
        status="queued",
        progress=0,
        step="任务已创建",
        use_llm=req.use_llm,
        trigger_type=req.trigger_type or "manual",
    )
    background_tasks.add_task(_run_etf_analysis_task, task_id, req.model_dump(), session_factory)
    return dict(task)


@router.get("/analysis/tasks/{task_id}")
async def get_etf_analysis_task(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或服务已重启")
    return dict(task)


@router.get("/analysis/tasks")
async def list_etf_analysis_tasks(limit: int = Query(default=20, ge=1, le=100)):
    rows = sorted(TASKS.values(), key=lambda item: item.get("created_at") or "", reverse=True)
    return [dict(row) for row in rows[:limit]]


@router.get("/analysis/history")
async def list_etf_analysis_history(
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(EtfAnalysisRecord)
            .order_by(desc(EtfAnalysisRecord.analysis_time), desc(EtfAnalysisRecord.id))
            .limit(limit)
        )
    ).scalars().all()
    return [_record_payload(r) for r in rows]


@router.get("/analysis/latest")
async def get_etf_analysis_latest(db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(EtfAnalysisRecord)
            .order_by(desc(EtfAnalysisRecord.analysis_time), desc(EtfAnalysisRecord.id))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="暂无 ETF 分析记录")
    return _record_payload(row)


@router.get("/analysis/records/{record_id}")
async def get_etf_analysis_record(record_id: int, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(select(EtfAnalysisRecord).where(EtfAnalysisRecord.id == record_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="分析记录不存在")
    return _record_payload(row)


# ========== K 线补全 API ==========


class EtfKlineBackfillRequest(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    lookback_days: int = Field(default=120, ge=30, le=365)


class EtfKlineBackfillBatchRequest(BaseModel):
    record_id: int | None = None
    lookback_days: int = Field(default=120, ge=30, le=365)


class EtfQuoteRefreshRequest(BaseModel):
    codes: list[str] | None = None


@router.post("/kline/backfill")
async def backfill_single_etf_kline(req: EtfKlineBackfillRequest, db: AsyncSession = Depends(get_db)):
    """对单只 ETF 强制重拉 K 线，跳过缓存"""
    code = _normalize_code(req.code)
    if not code:
        raise HTTPException(status_code=400, detail="ETF 代码无效")
    result = await _force_fetch_etf_kline(db, code, req.lookback_days)
    return result


@router.post("/analysis/backfill_missing")
async def backfill_missing_etf_kline(
    req: EtfKlineBackfillBatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量补全：从指定分析记录（或最新记录）中找出缺/陈旧 K 线的 ETF，并强制重拉"""
    if req.record_id:
        row = (
            await db.execute(select(EtfAnalysisRecord).where(EtfAnalysisRecord.id == req.record_id))
        ).scalar_one_or_none()
    else:
        row = (
            await db.execute(
                select(EtfAnalysisRecord)
                .order_by(desc(EtfAnalysisRecord.analysis_time), desc(EtfAnalysisRecord.id))
                .limit(1)
            )
        ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="未找到分析记录，请先运行一次分析")

    payload = _record_payload(row)
    individual = payload.get("individual_analysis") or []
    missing_codes: list[str] = []
    for a in individual:
        kline_source = a.get("kline_source")
        latest_close = ((a.get("technicals") or {}).get("latest_close"))
        if latest_close is None or kline_source in ("missing", "cache_stale"):
            code = _normalize_code(a.get("code"))
            if code and code not in missing_codes:
                missing_codes.append(code)

    if not missing_codes:
        return {"record_id": row.id, "missing_codes": [], "results": []}

    results: list[dict[str, Any]] = []
    for code in missing_codes:
        results.append(await _force_fetch_etf_kline(db, code, req.lookback_days))
    success = [r for r in results if r.get("ok")]
    return {
        "record_id": row.id,
        "missing_codes": missing_codes,
        "success_count": len(success),
        "fail_count": len(results) - len(success),
        "results": results,
    }


@router.post("/quote/refresh")
async def refresh_etf_quote_cache(req: EtfQuoteRefreshRequest | None = None) -> dict[str, Any]:
    """强制刷新全市场 ETF 实时行情缓存，返回最新快照（可选按 codes 过滤）。"""
    data = await _refresh_etf_spot_cache()
    fetched_at = SPOT_CACHE.get("fetched_at")
    snapshot: dict[str, dict[str, Any]] = {}
    codes = (req.codes if req else None) or []
    if codes:
        wanted = {_normalize_code(c) for c in codes if _normalize_code(c)}
        snapshot = {c: data[c] for c in wanted if c in data}
    return {
        "ok": bool(data),
        "count": len(data),
        "fetched_at": fetched_at.isoformat(timespec="seconds") if fetched_at else None,
        "error": SPOT_CACHE.get("error"),
        "quotes": snapshot,
    }
