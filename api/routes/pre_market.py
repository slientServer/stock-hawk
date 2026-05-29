"""盘前选股 API 路由"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.llm_client import LLMClient
from agents.tools.notification_tools import NotificationTools
from api.deps import get_db, get_session_factory
from common.logger import get_logger
from common.models import DailyKline, EtfDailyKline, PreMarketResult, SectorCatalyst
from data_collector.cache.redis_cache import RedisCache
from data_collector.sources.main_flow import MainFlowCollector
from data_collector.storage import DataStorage
from pre_market.catalyst_analyzer import CatalystAnalyzer
from pre_market.config import PreMarketConfig
from pre_market.screener import PreMarketScreener

logger = get_logger(__name__)

router = APIRouter(prefix="/pre-market", tags=["盘前选股"])

TASKS: dict[str, dict[str, Any]] = {}
PRE_MARKET_LOCK = asyncio.Lock()


# ── helpers ─────────────────────────────────────────────────────────────────


def _set_task(task_id: str, **kwargs) -> dict[str, Any]:
    TASKS.setdefault(task_id, {"task_id": task_id})
    TASKS[task_id].update(kwargs)
    return TASKS[task_id]


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _serialize_result(row: PreMarketResult) -> dict:
    return {
        "id": row.id,
        "trade_date": str(row.trade_date) if row.trade_date else None,
        "result_type": row.result_type,
        "code": row.code,
        "name": row.name,
        "close_price": _num(row.close_price),
        "change_pct_5d": _num(row.change_pct_5d),
        "change_pct_1d": _num(row.change_pct_1d),
        "change_pct_3d": _num(row.change_pct_3d),
        "turnover_rate": _num(row.turnover_rate),
        "volume_ratio": _num(row.volume_ratio),
        "market_cap": _num(row.market_cap),
        "main_net_1d": _num(row.main_net_1d),
        "main_net_3d": _num(row.main_net_3d),
        "above_ma5": row.above_ma5,
        "catalyst_sector": row.catalyst_sector,
        "catalyst_strength": row.catalyst_strength,
        "ma5_direction": row.ma5_direction,
        "ma5_deviation": _num(row.ma5_deviation),
        "amount_ratio": _num(row.amount_ratio),
        "avg_amplitude": _num(row.avg_amplitude),
        "score": _num(row.score),
        "score_detail": row.score_detail,
        "rank": row.rank,
        "target_price": _num(row.target_price),
        "stop_loss_price": _num(row.stop_loss_price),
        "suggestion": row.suggestion,
        "actual_return_pct": _num(row.actual_return_pct),
        "actual_exit_date": str(row.actual_exit_date) if row.actual_exit_date else None,
        "actual_exit_price": _num(row.actual_exit_price),
        "exit_type": row.exit_type,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def _resolve_trade_date(
    trade_date: date | None,
    session_factory: async_sessionmaker[AsyncSession],
) -> date | None:
    if trade_date is not None:
        return trade_date
    async with session_factory() as session:
        result = (
            await session.execute(
                select(func.max(DailyKline.trade_date)).where(DailyKline.trade_date <= date.today())
            )
        ).scalar_one_or_none()
    return result


# ── core task ────────────────────────────────────────────────────────────────


async def _run_pre_market_task(
    task_id: str,
    trade_date: date,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict:
    try:
        _set_task(task_id, status="running", progress=5, step="初始化")

        config = PreMarketConfig.load()
        llm = LLMClient()
        notifier = NotificationTools()

        # Step 0: 自动补采最新 K 线（避免定时任务漏跑导致数据过期）
        _set_task(task_id, progress=8, step="自动补采最新K线")
        try:
            from data_collector.sources.market_kline import KlineCollector
            from data_collector.storage import DataStorage
            kline_result = await KlineCollector(DataStorage(session_factory), RedisCache()).collect_full_market_daily(lookback_days=5)
            logger.info("[PreMarket] K线补采完成: trade_date=%s records=%s", kline_result.get("trade_date"), kline_result.get("records_count"))
            # 采完后重新解析最新交易日，确保用最新数据
            latest = await _resolve_trade_date(None, session_factory)
            if latest and latest > trade_date:
                logger.info("[PreMarket] 交易日更新: %s -> %s", trade_date, latest)
                trade_date = latest
                _set_task(task_id, trade_date=str(trade_date))
        except Exception as e:
            logger.warning("[PreMarket] K线补采失败（跳过，继续选股）: %s", e)

        # Step 1: 催化分析
        _set_task(task_id, progress=10, step="分析昨夜催化板块")
        analyzer = CatalystAnalyzer(session_factory, config, llm)
        catalysts = await analyzer.analyze(trade_date)

        # Step 2: 补齐 T-1 全市场主力资金
        _set_task(task_id, progress=25, step="补齐主力资金数据")
        main_flow_count = await MainFlowCollector(
            DataStorage(session_factory),
            RedisCache(),
        ).collect_tushare_moneyflow(trade_date)

        # Step 3: 选股
        _set_task(task_id, progress=35, step="激进标+稳健标筛选")
        screener = PreMarketScreener(session_factory, config, llm)
        results = await screener.run(trade_date, catalysts, persist=True)

        aggressive = results["aggressive"]
        stable = results["stable"]
        fallback_main = results["fallback_main"]
        fallback_backup = results["fallback_backup"]
        _set_task(task_id, progress=85, step="结果已保存", trade_date=str(trade_date))

        # Step 4: 飞书通知
        _set_task(task_id, progress=92, step="发送飞书通知")
        msg = _build_feishu_message(trade_date, aggressive, fallback_main, fallback_backup, stable, catalysts)
        await notifier.send_feishu(msg)

        payload = {
            "task_id": task_id,
            "trade_date": str(trade_date),
            "aggressive_count": len(aggressive),
            "fallback_main_count": len(results["fallback_main"]),
            "fallback_backup_count": len(results["fallback_backup"]),
            "stable_count": len(stable),
            "catalyst_count": len(catalysts),
            "main_flow_count": main_flow_count,
            "aggressive": aggressive,
            "fallback_main": results["fallback_main"],
            "fallback_backup": results["fallback_backup"],
            "stable": stable,
            "catalysts": catalysts,
        }
        _set_task(task_id, status="completed", progress=100, step="完成", result=payload)
        return payload

    except Exception as e:
        logger.error(f"Pre-market task {task_id} failed: {e}")
        _set_task(task_id, status="failed", progress=100, step="失败", error_message=str(e))
        return {"error": str(e), "task_id": task_id}


def _build_feishu_message(
    trade_date: date,
    aggressive: list[dict],
    fallback_main: list[dict],
    fallback_backup: list[dict],
    stable: list[dict],
    catalysts: list[dict],
) -> str:
    lines = [f"CtxHub 【盘前选股 {trade_date} 07:00】"]

    if aggressive:
        lines.append(f"🔥 激进标（目标+5%，止损-3%）共{len(aggressive)}只")
        for i, item in enumerate(aggressive[:5], 1):
            tp = item.get("target_price", 0)
            sl = item.get("stop_loss_price", 0)
            close = item.get("close_price", 0)
            lines.append(
                f"{i}. {item.get('name', '')}({item.get('code', '')}) 评分{item.get('score', 0)} | "
                f"催化:{item.get('catalyst_sector', '未知')}(强度{item.get('catalyst_strength', 0)})\n"
                f"   参考价:{close:.2f} | 目标:{tp:.2f} | 止损:{sl:.2f}"
            )
    elif fallback_main:
        lines.append(f"⚡ 激进标（降级·纯技术面）主推{len(fallback_main)}只 备用{len(fallback_backup)}只")
        for label, items in [("主推", fallback_main), ("备用", fallback_backup)]:
            for item in items:
                tp = item.get("target_price", 0)
                sl = item.get("stop_loss_price", 0)
                close = item.get("close_price", 0)
                lines.append(
                    f"[{label}] {item.get('name', '')}({item.get('code', '')}) 评分{item.get('score', 0)}\n"
                    f"   参考价:{close:.2f} | 目标:{tp:.2f} | 止损:{sl:.2f}"
                )
    else:
        lines.append("🔥 激进标：暂无符合条件标的")

    lines.append(f"\n🛡 稳健标（目标+2%，止损-1.5%）共{len(stable)}只")
    for i, item in enumerate(stable[:3], 1):
        rtype = item.get("result_type", "stable")
        type_label = "个股" if rtype == "stable_stock" else "ETF"
        change = item.get("change_pct_3d") or item.get("change_pct_5d", 0)
        tp = item.get("target_price", 0)
        sl = item.get("stop_loss_price", 0)
        close = item.get("close_price", 0)
        lines.append(
            f"{i}. [{type_label}] {item.get('name', '')}({item.get('code', '')}) 评分{item.get('score', 0)} | 涨幅{change:.2f}%\n"
            f"   参考价:{close:.2f} | 目标:{tp:.2f} | 止损:{sl:.2f}"
        )

    if catalysts:
        lines.append("\n📰 主要催化板块: " + "、".join(
            f"{c['sector_name']}(强度{c['catalyst_strength']})" for c in catalysts[:4]
        ))
    return "\n".join(lines)


# ── performance backfill ─────────────────────────────────────────────────────


async def _run_perf_backfill(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    """T+1～T+3 自动回填绩效数据"""
    since = date.today() - timedelta(days=5)
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(PreMarketResult).where(
                    PreMarketResult.trade_date >= since,
                    PreMarketResult.exit_type.in_(["pending", None]),
                )
            )
        ).scalars().all()

    logger.info(f"[PerfBackfill] 待回填记录: {len(rows)}")
    updated = 0
    for row in rows:
        if not row.trade_date or not row.close_price:
            continue
        exit_info = await _simulate_exit(row, session_factory)
        if exit_info:
            async with session_factory() as session:
                r = await session.get(PreMarketResult, row.id)
                if r:
                    r.actual_return_pct = Decimal(str(exit_info["return_pct"]))
                    r.actual_exit_date = exit_info["exit_date"]
                    r.actual_exit_price = Decimal(str(exit_info["exit_price"]))
                    r.exit_type = exit_info["exit_type"]
                    await session.commit()
                    updated += 1
    return {"updated": updated, "checked": len(rows)}


async def _simulate_exit(
    row: PreMarketResult,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict | None:
    """逐日模拟持有期内的止盈/止损/到期平仓"""
    entry = float(row.close_price)
    tp_price = float(row.target_price) if row.target_price else entry * 1.05
    sl_price = float(row.stop_loss_price) if row.stop_loss_price else entry * 0.97
    max_hold = 3
    start = row.trade_date + timedelta(days=1)

    is_etf = row.result_type == "stable"
    KlineModel = EtfDailyKline if is_etf else DailyKline

    async with session_factory() as session:
        klines = (
            await session.execute(
                select(
                    KlineModel.trade_date,
                    KlineModel.open,
                    KlineModel.high,
                    KlineModel.low,
                    KlineModel.close,
                ).where(
                    KlineModel.code == row.code,
                    KlineModel.trade_date >= start,
                    KlineModel.trade_date <= start + timedelta(days=6),
                ).order_by(KlineModel.trade_date)
            )
        ).all()

    trading_days = klines[:max_hold]
    if not trading_days:
        return None

    for day in trading_days:
        open_p = float(day.open or 0)
        high = float(day.high or 0)
        low = float(day.low or 0)
        close = float(day.close or 0)

        # 开盘跳空触发
        if open_p >= tp_price:
            ret = (open_p - entry) / entry * 100
            return {"exit_price": open_p, "exit_date": day.trade_date, "return_pct": round(ret, 4), "exit_type": "take_profit"}
        if open_p <= sl_price:
            ret = (open_p - entry) / entry * 100
            return {"exit_price": open_p, "exit_date": day.trade_date, "return_pct": round(ret, 4), "exit_type": "stop_loss"}

        # 日内
        if low <= sl_price:
            ret = (sl_price - entry) / entry * 100
            return {"exit_price": sl_price, "exit_date": day.trade_date, "return_pct": round(ret, 4), "exit_type": "stop_loss"}
        if high >= tp_price:
            ret = (tp_price - entry) / entry * 100
            return {"exit_price": tp_price, "exit_date": day.trade_date, "return_pct": round(ret, 4), "exit_type": "take_profit"}

    # 持满到期
    last = trading_days[-1]
    exit_price = float(last.close or entry)
    ret = (exit_price - entry) / entry * 100
    return {"exit_price": exit_price, "exit_date": last.trade_date, "return_pct": round(ret, 4), "exit_type": "max_hold"}


# ── scheduled entry points ────────────────────────────────────────────────────


async def run_scheduled_pre_market_screen(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    """供 AgentScheduler 7:00 AM cron 调用"""
    if PRE_MARKET_LOCK.locked():
        return {"status": "skipped", "reason": "已有盘前选股任务运行中"}
    trade_date = await _resolve_trade_date(None, session_factory)
    if not trade_date:
        return {"status": "skipped", "reason": "无可用交易日K线数据"}
    task_id = f"pre_market_{uuid.uuid4().hex[:8]}"
    _set_task(task_id, status="queued", progress=0, step="定时触发", trade_date=str(trade_date))
    async with PRE_MARKET_LOCK:
        return await _run_pre_market_task(task_id, trade_date, session_factory)


async def run_scheduled_perf_update(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    """供 AgentScheduler 16:30 cron 调用"""
    return await _run_perf_backfill(session_factory)


# ── API endpoints ─────────────────────────────────────────────────────────────


@router.post("/run")
async def trigger_pre_market(
    background_tasks: BackgroundTasks,
    trade_date: str | None = Query(default=None),
    session_factory=Depends(get_session_factory),
):
    if PRE_MARKET_LOCK.locked():
        running = next((t for t in TASKS.values() if t.get("status") == "running"), None)
        return {"already_running": True, **(running or {})}

    parsed_date: date | None = None
    if trade_date:
        try:
            parsed_date = date.fromisoformat(trade_date)
        except ValueError:
            return {"error": f"Invalid date format: {trade_date}"}

    resolved = await _resolve_trade_date(parsed_date, session_factory)
    if not resolved:
        return {"error": "无可用交易日K线数据"}

    task_id = f"pre_market_{uuid.uuid4().hex[:8]}"
    _set_task(task_id, status="queued", progress=0, step="已加入队列", trade_date=str(resolved))

    async def _bg():
        async with PRE_MARKET_LOCK:
            await _run_pre_market_task(task_id, resolved, session_factory)

    background_tasks.add_task(_bg)
    return {"task_id": task_id, "trade_date": str(resolved), "status": "queued"}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        return {"error": "task not found"}
    # avoid returning large result payload on status poll
    return {k: v for k, v in task.items() if k != "result"}


@router.get("/latest")
async def get_latest(session_factory=Depends(get_session_factory)):
    async with session_factory() as session:
        latest_date = (
            await session.execute(select(func.max(PreMarketResult.trade_date)))
        ).scalar_one_or_none()
        if not latest_date:
            return {"trade_date": None, "aggressive": [], "stable": []}
        rows = (
            await session.execute(
                select(PreMarketResult)
                .where(PreMarketResult.trade_date == latest_date)
                .order_by(PreMarketResult.result_type, PreMarketResult.rank)
            )
        ).scalars().all()

    aggressive = [_serialize_result(r) for r in rows if r.result_type == "aggressive"]
    fallback_main = [_serialize_result(r) for r in rows if r.result_type == "aggressive_main"]
    fallback_backup = [_serialize_result(r) for r in rows if r.result_type == "aggressive_backup"]
    stable = [_serialize_result(r) for r in rows if r.result_type in ("stable", "stable_stock")]
    return {
        "trade_date": str(latest_date),
        "aggressive": aggressive,
        "fallback_main": fallback_main,
        "fallback_backup": fallback_backup,
        "stable": stable,
    }


@router.get("/history")
async def get_history(
    limit: int = Query(default=30, ge=1, le=90),
    session_factory=Depends(get_session_factory),
):
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(
                    PreMarketResult.trade_date,
                    func.count(PreMarketResult.id).label("total"),
                )
                .group_by(PreMarketResult.trade_date)
                .order_by(desc(PreMarketResult.trade_date))
                .limit(limit)
            )
        ).all()
    return [{"trade_date": str(r.trade_date), "total": r.total} for r in rows]


@router.get("/performance")
async def get_performance(
    days: int = Query(default=30, ge=7, le=180),
    session_factory=Depends(get_session_factory),
):
    since = date.today() - timedelta(days=days)
    async with session_factory() as session:
        # 已结仓记录用于统计
        closed_rows = (
            await session.execute(
                select(PreMarketResult).where(
                    PreMarketResult.trade_date >= since,
                    PreMarketResult.exit_type.isnot(None),
                    PreMarketResult.exit_type.notin_(["pending"]),
                )
            )
        ).scalars().all()
        # 全部记录（含进行中）用于明细展示
        all_rows = (
            await session.execute(
                select(PreMarketResult).where(
                    PreMarketResult.trade_date >= since,
                )
            )
        ).scalars().all()

    def _stats(items):
        if not items:
            return {"count": 0, "win_rate": None, "avg_return": None, "profit_loss_ratio": None}
        returns = [float(r.actual_return_pct) for r in items if r.actual_return_pct is not None]
        if not returns:
            return {"count": len(items), "win_rate": None, "avg_return": None, "profit_loss_ratio": None}
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        win_rate = len(wins) / len(returns)
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 1
        pl_ratio = avg_win / avg_loss if avg_loss > 0 else None
        return {
            "count": len(returns),
            "win_rate": round(win_rate, 4),
            "avg_return": round(sum(returns) / len(returns), 4),
            "profit_loss_ratio": round(pl_ratio, 4) if pl_ratio else None,
        }

    agg_rows = [r for r in closed_rows if r.result_type in ("aggressive", "aggressive_main", "aggressive_backup")]
    stable_rows = [r for r in closed_rows if r.result_type in ("stable", "stable_stock")]

    today = date.today()

    def _detail(items):
        result = []
        for r in items:
            # 持仓天数：已结仓用 exit_date - trade_date，进行中用 today - trade_date
            if r.actual_exit_date and r.trade_date:
                holding_days = (r.actual_exit_date - r.trade_date).days
            elif r.trade_date:
                holding_days = (today - r.trade_date).days
            else:
                holding_days = None

            # 截止日判断：trade_date + ~5个日历日（3个交易日约等于5天）
            deadline_passed = r.trade_date and (today - r.trade_date).days > 5

            result.append({
                "code": r.code,
                "name": r.name,
                "result_type": r.result_type,
                "trade_date": str(r.trade_date) if r.trade_date else None,
                "entry_price": float(r.close_price) if r.close_price is not None else None,
                "target_price": float(r.target_price) if r.target_price is not None else None,
                "stop_loss_price": float(r.stop_loss_price) if r.stop_loss_price is not None else None,
                "exit_date": str(r.actual_exit_date) if r.actual_exit_date else None,
                "exit_price": float(r.actual_exit_price) if r.actual_exit_price is not None else None,
                "exit_type": r.exit_type,
                "holding_days": holding_days,
                "deadline_passed": deadline_passed,
                "return_pct": float(r.actual_return_pct) if r.actual_return_pct is not None else None,
            })
        # 按推荐日倒序
        result.sort(key=lambda x: x["trade_date"] or "", reverse=True)
        return result

    return {
        "since": str(since),
        "aggressive": _stats(agg_rows),
        "stable": _stats(stable_rows),
        "combined": _stats(closed_rows),
        "details": _detail(all_rows),
    }


@router.get("/{date_str}/catalysts")
async def get_catalysts(date_str: str, session_factory=Depends(get_session_factory)):
    try:
        trade_date = date.fromisoformat(date_str)
    except ValueError:
        return {"error": f"Invalid date: {date_str}"}
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(SectorCatalyst)
                .where(SectorCatalyst.trade_date == trade_date)
                .order_by(desc(SectorCatalyst.catalyst_strength))
            )
        ).scalars().all()
    return [
        {
            "sector_name": r.sector_name,
            "catalyst_strength": r.catalyst_strength,
            "catalyst_type": r.catalyst_type,
            "summary": r.summary,
            "related_codes": r.related_codes or [],
            "llm_used": r.llm_used,
        }
        for r in rows
    ]


@router.get("/{date_str}")
async def get_by_date(date_str: str, session_factory=Depends(get_session_factory)):
    try:
        trade_date = date.fromisoformat(date_str)
    except ValueError:
        return {"error": f"Invalid date: {date_str}"}
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(PreMarketResult)
                .where(PreMarketResult.trade_date == trade_date)
                .order_by(PreMarketResult.result_type, PreMarketResult.rank)
            )
        ).scalars().all()
    aggressive = [_serialize_result(r) for r in rows if r.result_type == "aggressive"]
    fallback_main = [_serialize_result(r) for r in rows if r.result_type == "aggressive_main"]
    fallback_backup = [_serialize_result(r) for r in rows if r.result_type == "aggressive_backup"]
    stable = [_serialize_result(r) for r in rows if r.result_type in ("stable", "stable_stock")]
    return {
        "trade_date": date_str,
        "aggressive": aggressive,
        "fallback_main": fallback_main,
        "fallback_backup": fallback_backup,
        "stable": stable,
    }
