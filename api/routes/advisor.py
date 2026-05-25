"""投研工作台 API：基于真实数据的选股、分析和盯盘聚合。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import AgentResult
from agents.llm_client import LLMClient
from agents.stock_analysis import StockAnalysisAgent
from api.deps import get_db, get_session_factory
from common.config import get_settings
from common.models import AgentLog, ChainScore, FundFlow, Signal
from common.stock_service import (
    build_picks,
    candidate_data_counts,
    chain_maps,
    data_counts,
    num,
    query_main_flows,
    signal_codes,
    stock_name_map,
)
from knowledge_graph.service import chain_topology_with_fallback, graph_chains_with_fallback

router = APIRouter(prefix="/advisor", tags=["投研工作台"])


class StockAnalysisMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=12000)


class StockAnalysisChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=12000)
    history: list[StockAnalysisMessage] = Field(default_factory=list, max_length=20)
    filters: dict[str, Any] = Field(default_factory=dict)
    codes: list[str] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=10, ge=1, le=50)
    use_llm: bool = True
    page_context: dict[str, Any] = Field(default_factory=dict)


# ─── 本文件私有辅助函数（API 响应特有，不共享给 Agent 层）────────────────────────


def _company_payload(company: dict[str, Any]) -> dict[str, Any]:
    code = str(company.get("code") or "")
    return {
        "code": code,
        "name": company.get("name") or code,
        "market": company.get("market"),
        "industry": company.get("industry"),
    }


def _stream_line(event: str, data: Any) -> str:
    return json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str) + "\n"


def _text_chunks(text: str, size: int = 18):
    for index in range(0, len(text), size):
        yield text[index:index + size]


def _target_stocks(signal: Signal, stock_names: dict[str, str]) -> list[dict[str, str | None]]:
    return [
        {"code": code, "name": stock_names.get(code)}
        for code in sorted(signal_codes(signal))
    ]


async def _latest_discovery(db: AsyncSession) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(AgentLog)
            .where(AgentLog.agent_id == "chain_discovery")
            .order_by(desc(AgentLog.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        return None
    return {
        "status": row.status,
        "created_at": str(row.created_at) if row.created_at else None,
        "output": row.output_data or {},
        "error": row.error_message,
    }


def _watch_risk_type(reasons: list[str]) -> str:
    if any("跌幅" in reason or "回撤" in reason for reason in reasons):
        return "price_risk"
    if any("缺少" in reason for reason in reasons):
        return "data_quality"
    if any("ST" == reason for reason in reasons):
        return "special_treatment"
    return "signal_tracking"


def _watch_action_suggestion(level: str, risk_type: str, reasons: list[str]) -> str:
    if level == "warning" and risk_type == "price_risk":
        return "优先复核最新K线和触发信号，若回撤继续扩大或信号失效，降低关注优先级。"
    if risk_type == "data_quality":
        return "先补齐缺失的K线或财报数据，再扩大基本面和回撤结论。"
    if any("ST" == reason for reason in reasons):
        return "按高风险标的处理，进入低风险筛选时应剔除。"
    return "持续跟踪信号有效期、最新财报和短期价格变化。"


def _watch_alert_from_pick(item: dict[str, Any], score_threshold: int = 60) -> dict[str, Any] | None:
    level = "info"
    reasons = list(item.get("risk_flags") or [])
    metrics = item.get("metrics") or {}
    financial = item.get("financial") or {}
    ret5 = metrics.get("return_5d")
    drawdown = metrics.get("drawdown_60d")
    if ret5 is not None and ret5 < -5:
        level = "warning"
        reasons.append("近5日跌幅超过5%")
    if drawdown is not None and drawdown < -15:
        level = "warning"
        reasons.append("60日回撤超过15%")
    if not reasons and item["score"] >= score_threshold:
        reasons.append("候选评分较高，建议持续跟踪信号有效期")
    if not reasons:
        return None

    risk_type = _watch_risk_type(reasons)
    data_quality = item.get("data_quality") or {}
    data_gaps = []
    if data_quality.get("has_kline") is False:
        data_gaps.append("K线数据缺失")
    if data_quality.get("has_financial") is False:
        data_gaps.append("财报数据缺失")
    if data_quality.get("has_graph") is False:
        data_gaps.append("图谱归属缺失")

    return {
        "code": item["code"],
        "name": item["name"],
        "level": level,
        "risk_type": risk_type,
        "score": item["score"],
        "tier": item.get("tier"),
        "industry": item.get("industry"),
        "chain_names": item.get("chain_names") or [],
        "segments": item.get("segments") or [],
        "signal_count": item.get("signal_count") or 0,
        "latest_signal": item.get("latest_signal"),
        "reasons": reasons,
        "metrics": {
            "return_5d": ret5,
            "return_20d": metrics.get("return_20d"),
            "drawdown_60d": drawdown,
            "avg_amount_20d": metrics.get("avg_amount_20d"),
            "latest_trade_date": metrics.get("latest_trade_date"),
        },
        "financial": {
            "report_date": financial.get("report_date"),
            "revenue_yoy": financial.get("revenue_yoy"),
            "net_profit_yoy": financial.get("net_profit_yoy"),
            "pe_ratio": financial.get("pe_ratio"),
        } if financial else None,
        "data_quality": data_quality,
        "data_gaps": data_gaps,
        "action_suggestion": _watch_action_suggestion(level, risk_type, reasons),
    }


async def _chain_code_groups(chain_name: str | None = None) -> dict[str, set[str]]:
    """按产业链或环节分组获取股票代码。"""
    _, code_map = await chain_maps()
    groups: dict[str, set[str]] = defaultdict(set)
    for code, memberships in code_map.items():
        for item in memberships:
            if chain_name is None:
                groups[item["chain"]].add(code)
            elif item["chain"] == chain_name:
                segment = item.get("segment") or "未分类"
                groups[segment].add(code)
    return groups


async def _north_flow_summary(db: AsyncSession, period: int) -> dict[str, Any]:
    latest_date = (await db.execute(select(func.max(FundFlow.trade_date)))).scalar()
    if not latest_date:
        return {"latest_date": None, "north_net_period": None, "north_net_latest": None}
    start = latest_date - timedelta(days=period * 2 + 5)
    rows = (
        await db.execute(
            select(FundFlow)
            .where(FundFlow.trade_date >= start)
            .order_by(FundFlow.trade_date)
        )
    ).scalars().all()
    recent_rows = rows[-period:] if len(rows) >= period else rows
    valid_nets = [float(r.north_net) for r in recent_rows if r.north_net is not None]
    net_total = sum(valid_nets) if valid_nets else None
    latest_net = (
        float(recent_rows[-1].north_net)
        if recent_rows and recent_rows[-1].north_net is not None
        else None
    )
    latest_d = str(recent_rows[-1].trade_date) if recent_rows else None
    return {
        "latest_date": latest_d,
        "north_net_period": round(net_total, 2) if net_total is not None else None,
        "north_net_latest": round(latest_net, 2) if latest_net is not None else None,
    }


def _aggregate_fund_flow(
    groups: dict[str, set[str]],
    flows: list,
    period: int,
    stock_names: dict[str, str],
) -> list[dict[str, Any]]:
    by_code: dict[str, list] = defaultdict(list)
    for flow in flows:
        by_code[flow.code].append(flow)

    all_dates = sorted({flow.trade_date for flow in flows})
    recent_dates = all_dates[-period:] if len(all_dates) >= period else all_dates

    results = []
    for name, codes in groups.items():
        daily_total: dict = defaultdict(lambda: {"main_net": 0.0, "retail_net": 0.0})
        stock_totals: dict[str, float] = defaultdict(float)
        for code in codes:
            for flow in by_code.get(code, []):
                if flow.trade_date in recent_dates:
                    main_net_val = float(flow.main_net or 0)
                    retail_net_val = float(flow.retail_net or 0)
                    daily_total[flow.trade_date]["main_net"] += main_net_val
                    daily_total[flow.trade_date]["retail_net"] += retail_net_val
                    stock_totals[code] += main_net_val

        main_net_total = sum(d["main_net"] for d in daily_total.values())
        retail_net_total = sum(d["retail_net"] for d in daily_total.values())
        day_count = len(daily_total) or 1
        pct_values = [
            float(f.main_net_pct or 0)
            for code in codes
            for f in by_code.get(code, [])
            if f.trade_date in recent_dates and f.main_net_pct is not None
        ]
        avg_pct = sum(pct_values) / len(pct_values) if pct_values else None
        trend = [
            {
                "date": str(d),
                "main_net": round(daily_total[d]["main_net"], 2),
                "retail_net": round(daily_total[d]["retail_net"], 2),
            }
            for d in sorted(daily_total.keys())
        ]
        sorted_stocks = sorted(stock_totals.items(), key=lambda x: x[1], reverse=True)
        top_inflow = [
            {"code": c, "name": stock_names.get(c, c), "main_net": round(v, 2)}
            for c, v in sorted_stocks[:3] if v > 0
        ]
        top_outflow = [
            {"code": c, "name": stock_names.get(c, c), "main_net": round(v, 2)}
            for c, v in sorted_stocks if v < 0
        ][-3:][::-1]
        if not top_outflow:
            top_outflow = [
                {"code": c, "name": stock_names.get(c, c), "main_net": round(v, 2)}
                for c, v in reversed(sorted_stocks) if v < 0
            ][:3]

        results.append({
            "name": name,
            "main_net_total": round(main_net_total, 2),
            "main_net_daily_avg": round(main_net_total / day_count, 2),
            "main_net_pct_avg": round(avg_pct, 2) if avg_pct is not None else None,
            "retail_net_total": round(retail_net_total, 2),
            "stock_count": len(codes),
            "data_days": len(daily_total),
            "trend": trend,
            "top_inflow": top_inflow,
            "top_outflow": top_outflow,
        })

    results.sort(key=lambda x: x["main_net_total"], reverse=True)
    return results


# ─── API 路由 ────────────────────────────────────────────────────────────────────


@router.get("/overview")
async def advisor_overview(db: AsyncSession = Depends(get_db)):
    counts = await data_counts(db)
    candidate_counts = await candidate_data_counts(db)
    chains = await graph_chains_with_fallback()
    discovery = await _latest_discovery(db)
    settings = get_settings()
    latest_discovery_status = (discovery or {}).get("output", {}).get("status")
    llm_blocked = latest_discovery_status == "llm_unavailable"
    blockers = []
    candidate_count = candidate_counts["candidate_count"]
    if candidate_count:
        kline_coverage = candidate_counts["candidate_kline_coverage"]
        financial_coverage = candidate_counts["candidate_financial_coverage"]
        if kline_coverage / candidate_count < 0.8:
            blockers.append(f"候选池K线覆盖不足（{kline_coverage}/{candidate_count}），动量和盯盘判断置信度偏低")
        if financial_coverage / candidate_count < 0.8:
            blockers.append(
                f"候选池财报覆盖不足（{financial_coverage}/{candidate_count}），基本面选股置信度偏低"
            )
    else:
        blockers.append("候选池为空，需要先灌入知识图谱或产生入库信号")
    if llm_blocked:
        blockers.append("自定义 LLM 调用失败，需要检查模型平台账号、Key、模型权限或网络")
    if not chains:
        blockers.append("知识图谱为空，无法做产业链归因")

    capabilities = [
        {
            "key": "data",
            "name": "数据底座",
            "status": "ready" if counts["stock_count"] > 0 else "blocked",
            "detail": (
                f"{counts['stock_count']} 只股票，候选池K线 "
                f"{candidate_counts['candidate_kline_coverage']}/{candidate_count}"
            ),
        },
        {
            "key": "graph",
            "name": "产业链图谱",
            "status": "ready" if chains else "blocked",
            "detail": f"{len(chains)} 条产业链",
        },
        {
            "key": "selection",
            "name": "规则化选股",
            "status": "ready" if counts["signal_count"] or counts["kline_stock_coverage"] else "blocked",
            "detail": f"{counts['signal_count']} 个信号，候选池 {candidate_count} 只",
        },
        {
            "key": "llm",
            "name": "LLM 深度分析",
            "status": "blocked" if llm_blocked else (
                "configured" if settings.llm.custom_base_url else "not_configured"
            ),
            "detail": settings.llm.custom_base_url or "未配置 Custom Base URL",
        },
    ]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "counts": {**counts, **candidate_counts, "chain_count": len(chains)},
        "capabilities": capabilities,
        "blockers": blockers,
        "latest_discovery": discovery,
    }


@router.get("/picks")
async def advisor_picks(
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await build_picks(db, limit=limit)


@router.post("/stock-analysis/chat")
async def advisor_stock_analysis_chat(
    req: StockAnalysisChatRequest,
    session_factory=Depends(get_session_factory),
):
    llm = LLMClient()
    try:
        agent = StockAnalysisAgent(session_factory, llm if req.use_llm and llm.is_available() else None)
        result = await agent.run({**req.model_dump(), "workflow_type": "stock_analysis_chat"})
        return result.model_dump(mode="json")
    finally:
        await llm.close()


@router.post("/stock-analysis/chat/stream")
async def advisor_stock_analysis_chat_stream(
    req: StockAnalysisChatRequest,
    session_factory=Depends(get_session_factory),
):
    async def generate():
        llm = LLMClient()
        started = time.time()
        task_id = f"stock_analysis_stream_{uuid.uuid4().hex[:8]}"
        params = {**req.model_dump(), "workflow_type": "stock_analysis_chat_stream"}
        agent = StockAnalysisAgent(session_factory, llm if req.use_llm and llm.is_available() else None)
        result_payload: dict[str, Any] | None = None
        status = "degraded"
        error_message = ""
        used_llm = False
        try:
            yield _stream_line("status", {"message": "读取投研上下文"})
            context = await agent.build_stream_context(params)
            base_result = agent.fallback_from_context(context)
            yield _stream_line(
                "meta",
                {
                    "agent_id": agent.agent_id,
                    "task_id": task_id,
                    "status": "running",
                    "result": {**base_result, "answer": ""},
                    "metadata": {"used_llm": False, "streaming": True},
                },
            )

            if req.use_llm and llm.is_available():
                chunks: list[str] = []
                try:
                    yield _stream_line("status", {"message": "调用 LLM 流式生成"})
                    async for chunk in llm.stream_chat(
                        [
                            {"role": "system", "content": StockAnalysisAgent.stream_system_prompt()},
                            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
                        ],
                        temperature=0.2,
                        max_tokens=1800,
                    ):
                        if not chunk:
                            continue
                        chunks.append(chunk)
                        yield _stream_line("delta", chunk)
                    answer = "".join(chunks).strip()
                    if not answer:
                        raise RuntimeError("LLM stream returned empty answer")
                    result_payload = agent.normalize_stream_result(answer, context, base_result)
                    status = "completed"
                    used_llm = True
                except Exception as e:
                    error_message = str(e)
                    if chunks:
                        answer = "".join(chunks).strip()
                        result_payload = agent.normalize_stream_result(answer, context, base_result)
                        gaps = list(result_payload.get("data_gaps") or [])
                        gaps.append(f"LLM 流式输出中断: {error_message}")
                        result_payload["data_gaps"] = gaps
                    else:
                        yield _stream_line("status", {"message": "LLM 流式不可用，使用规则化分析"})
                        result_payload = {**base_result, "llm_error": error_message}
                        for chunk in _text_chunks(str(result_payload.get("answer") or "没有返回分析结果")):
                            yield _stream_line("delta", chunk)
                            await asyncio.sleep(0)
                    status = "degraded"
            else:
                yield _stream_line("status", {"message": "LLM 未配置，使用规则化分析"})
                result_payload = base_result
                for chunk in _text_chunks(str(result_payload.get("answer") or "没有返回分析结果")):
                    yield _stream_line("delta", chunk)
                    await asyncio.sleep(0)
            payload = {
                "agent_id": agent.agent_id,
                "task_id": task_id,
                "status": status,
                "result": result_payload,
                "error_message": error_message,
                "metadata": {
                    "execution_time_ms": int((time.time() - started) * 1000),
                    "llm_calls": getattr(llm, "last_call_count", 0) if used_llm else 0,
                    "tokens_used": getattr(llm, "last_tokens_used", 0) if used_llm else 0,
                    "used_llm": used_llm,
                    "streaming": True,
                },
            }
            yield _stream_line("done", payload)
        except Exception as e:
            status = "failed"
            error_message = str(e)
            yield _stream_line("error", {"message": str(e)})
        finally:
            elapsed = int((time.time() - started) * 1000)
            await agent._save_log(
                AgentResult(
                    agent_id=agent.agent_id,
                    task_id=task_id,
                    status=status,
                    result=result_payload or {},
                    error_message=error_message,
                    metadata={
                        "execution_time_ms": elapsed,
                        "llm_calls": getattr(llm, "last_call_count", 0) if used_llm else 0,
                        "tokens_used": getattr(llm, "last_tokens_used", 0) if used_llm else 0,
                        "used_llm": used_llm,
                        "streaming": True,
                    },
                ),
                params,
            )
            await llm.close()

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/watchlist")
async def advisor_watchlist(
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    picks = await build_picks(db, limit=limit)
    alerts = []
    for item in picks["items"]:
        alert = _watch_alert_from_pick(item, score_threshold=60)
        if alert:
            alerts.append(alert)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "alerts": alerts,
        "data_source": "advisor_picks",
        "monitoring_scope": [
            "候选池评分和风险标签",
            "近5日涨跌幅",
            "60日回撤",
            "K线/财报/图谱数据覆盖",
            "最新信号和财报指标摘要",
        ],
    }


@router.get("/chains/{chain_name}/analysis")
async def advisor_chain_analysis(
    chain_name: str,
    db: AsyncSession = Depends(get_db),
):
    topology = await chain_topology_with_fallback(chain_name)
    if not topology:
        return {"status": "not_found", "chain_name": chain_name}
    signals = (
        await db.execute(
            select(Signal)
            .where(Signal.chain_id == chain_name)
            .order_by(desc(Signal.trigger_date), desc(Signal.created_at))
            .limit(20)
        )
    ).scalars().all()
    latest_score = (
        await db.execute(
            select(ChainScore)
            .where(ChainScore.chain_id == chain_name)
            .order_by(desc(ChainScore.score_date), desc(ChainScore.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    signal_types = sorted({s.signal_type for s in signals if s.signal_type})
    segments = topology.get("segments", [])
    all_signal_codes = set().union(*[signal_codes(s) for s in signals]) if signals else set()
    names = await stock_name_map(db, all_signal_codes)
    transmission_path = [
        {
            "position": seg.get("position"),
            "segment": seg.get("segment_name") or seg.get("name"),
            "company_count": len(seg.get("companies", [])),
            "companies": [_company_payload(company) for company in seg.get("companies", [])],
        }
        for seg in segments
    ]
    data_gaps = []
    if not signals:
        data_gaps.append("暂无近期信号，阶段判断只能基于图谱结构")
    if not latest_score:
        data_gaps.append("暂无最新产业链评分")
    return {
        "status": "completed",
        "chain_name": chain_name,
        "summary": (
            f"{chain_name} 当前有 {len(segments)} 个环节、"
            f"{len(topology.get('companies', []))} 家图谱公司、{len(signals)} 个近期信号。"
        ),
        "trend_type": (
            "event_driven" if "catalyst" in signal_types
            else ("market_momentum" if "sector_linkage" in signal_types else "data_insufficient")
        ),
        "current_stage": "verification" if len(signals) >= 3 else "watching",
        "score": num(latest_score.score) if latest_score else None,
        "signal_types": signal_types,
        "transmission_path": transmission_path,
        "key_signals": [
            {
                "signal_type": s.signal_type,
                "source_entity": s.source_entity,
                "target_codes": s.target_codes,
                "target_stocks": _target_stocks(s, names),
                "strength": num(s.strength),
                "confidence": num(s.confidence),
                "detail": s.detail,
                "trigger_date": str(s.trigger_date) if s.trigger_date else None,
                "source": s.source,
            }
            for s in signals[:8]
        ],
        "data_gaps": data_gaps,
        "confidence": "medium" if signals and latest_score else "low",
    }


@router.get("/fund-flow")
async def advisor_fund_flow(
    chain_name: str | None = Query(None),
    period: int = Query(5, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """产业链主力资金流向。chain_name 为空时返回所有产业链对比；指定时返回该链各环节对比。"""
    groups = await _chain_code_groups(chain_name)
    if not groups:
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "chain_detail" if chain_name else "overall",
            "period": period,
            "chain_name": chain_name,
            "items": [],
            "north_flow_summary": {"latest_date": None, "north_net_period": None, "north_net_latest": None},
            "data_gaps": ["知识图谱中无产业链数据" if not chain_name else f"未找到产业链: {chain_name}"],
        }

    all_codes = set().union(*groups.values())
    flows = await query_main_flows(db, all_codes, period)
    names = await stock_name_map(db, all_codes)

    if not flows:
        north_summary = await _north_flow_summary(db, period)
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "chain_detail" if chain_name else "overall",
            "period": period,
            "chain_name": chain_name,
            "items": [],
            "north_flow_summary": north_summary,
            "data_gaps": ["暂无主力资金流数据，请先运行数据采集"],
        }

    items = _aggregate_fund_flow(groups, flows, period, names)
    north_summary = await _north_flow_summary(db, period)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "chain_detail" if chain_name else "overall",
        "period": period,
        "chain_name": chain_name,
        "items": items,
        "north_flow_summary": north_summary,
    }


# ─── 向后兼容：保留供其他 API 路由文件直接调用的别名 ─────────────────────────────
# 其他路由只需 from api.routes.advisor import _build_picks 等的情况已通过
# common.stock_service 统一，此处不再 re-export 内部私有函数。
# 如需使用，请直接从 common.stock_service 导入。
