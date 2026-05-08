"""产业链发现路由：手动触发、查询历史"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_session_factory
from common.models import AgentLog

router = APIRouter(prefix="/discovery", tags=["产业链发现"])

# 内存状态，记录最近一次执行
_discovery_status: dict = {
    "running": False,
    "result": None,
    "error": None,
}


def _market_source_resolution_steps() -> list[str]:
    return [
        "检查运行机器是否能访问东方财富/AKShare 相关接口；RemoteDisconnected 通常是网络、代理、反爬或出口限制导致。",
        "如果在公司网络内运行，配置可用代理或放通东方财富行情域名后重试。",
        "升级 AKShare 到当前版本后重试概念板块和行业板块接口。",
            "系统已内置新浪板块备用源；若仍失败，优先检查运行机器到外部财经站点的网络出口或代理配置。",
        "只有需要扩展图谱候选且接受低置信度时，才显式开启 allow_local_fallback=true；该模式不能用于热门板块或交易信号。",
    ]


def _source_assessment(
    source_mode: str | None,
    market_success_count: int = 0,
    cached_market_source_count: int = 0,
) -> dict[str, Any]:
    if source_mode == "market_boards":
        all_cached = market_success_count > 0 and cached_market_source_count == market_success_count
        partly_cached = cached_market_source_count > 0 and not all_cached
        return {
            "confidence": "medium" if not all_cached else "low",
            "is_realtime_market": not all_cached,
            "is_market_hot": True,
            "is_simulated": False,
            "is_usable_for_discovery": True,
            "action_required": False,
            "data_source": "eastmoney_or_sina_market_boards",
            "label": "短期缓存市场板块" if all_cached else "实时市场板块",
            "explanation": (
                f"实时接口当前不可用，使用 {market_success_count} 个 4 小时内成功采集的外部板块缓存。"
                if all_cached
                else f"至少 {market_success_count} 个外部概念/行业板块源可用"
                + (f"，其中 {cached_market_source_count} 个来自短期缓存" if partly_cached else "")
                + "，可用于热门板块发现。"
            ),
            "recommended_usage": "可作为产业链自动发现候选，但仍需结合信号、财报和人工复核。",
        }
    if source_mode == "local_fallback":
        return {
            "confidence": "low",
            "is_realtime_market": False,
            "is_market_hot": False,
            "is_simulated": False,
            "is_usable_for_discovery": False,
            "action_required": True,
            "data_source": "local_stock_industry_grouping",
            "label": "本地行业降级",
            "explanation": "外部概念/行业板块源失败后，系统使用本地 stocks.industry 分组生成候选；这不是模拟数据，但不包含实时涨幅、成交额或市场热度。",
            "recommended_usage": "默认不应作为自动发现输入；仅在人工明确允许时用于扩展图谱候选。",
            "resolution_steps": _market_source_resolution_steps(),
        }
    if source_mode == "market_unavailable":
        return {
            "confidence": "none",
            "is_realtime_market": False,
            "is_market_hot": False,
            "is_simulated": False,
            "is_usable_for_discovery": False,
            "action_required": True,
            "data_source": "market_board_sources_failed",
            "label": "市场源异常",
            "explanation": "外部概念/行业板块数据源不可用，系统已暂停自动发现，未使用本地低置信度数据生成新图谱。",
            "recommended_usage": "先修复市场数据源，再重新运行自动发现。",
            "resolution_steps": _market_source_resolution_steps(),
        }
    return {
        "confidence": "none",
        "is_realtime_market": False,
        "is_market_hot": False,
        "is_simulated": False,
        "is_usable_for_discovery": False,
        "action_required": True,
        "data_source": "none",
        "label": "无可用数据",
        "explanation": "没有可用于产业链发现的市场源或本地降级源。",
        "recommended_usage": "不可用于发现任务。",
        "resolution_steps": _market_source_resolution_steps(),
    }


def _enrich_output(output: dict[str, Any]) -> dict[str, Any]:
    if not output:
        return {}
    enriched = dict(output)
    source_mode = enriched.get("source_mode")
    source_summary = enriched.get("source_summary") or {}
    default_assessment = _source_assessment(
        source_mode,
        int(source_summary.get("market_sources_succeeded") or 0),
        int(source_summary.get("cached_market_sources") or 0),
    )
    existing_assessment = enriched.get("source_assessment") or {}
    if source_mode in {"local_fallback", "market_unavailable"}:
        enriched["source_assessment"] = {**existing_assessment, **default_assessment}
    else:
        enriched["source_assessment"] = {**default_assessment, **existing_assessment}

    local_fallback_enabled = bool(source_summary.get("local_fallback_enabled"))
    if source_mode == "local_fallback" and not local_fallback_enabled:
        original_status = enriched.get("status")
        if original_status in {"completed", "degraded"}:
            enriched["original_status"] = original_status
            enriched["status"] = "market_source_unavailable"
        enriched["message"] = (
            "此前结果来自外部市场源失败后的本地行业降级，已标记为不可用于自动发现；"
            "请先修复实时市场板块数据源后重新运行。"
        )
    elif source_mode == "local_fallback":
        enriched.setdefault(
            "message",
            "外部概念/行业板块源不可用，已降级使用本地股票行业分组；结果不是模拟数据，但不代表实时热门板块。",
        )
    return enriched


def _serialize_log(row: AgentLog | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "task_id": row.task_id,
        "status": row.status,
        "output": _enrich_output(row.output_data or {}),
        "error": row.error_message,
        "duration_ms": row.duration_ms,
        "created_at": str(row.created_at) if row.created_at else None,
    }


async def _latest_discovery_log(db: AsyncSession) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(AgentLog).where(AgentLog.agent_id == "chain_discovery").order_by(desc(AgentLog.created_at)).limit(1)
        )
    ).scalar_one_or_none()
    return _serialize_log(row)


@router.post("/trigger")
async def trigger_discovery(
    background_tasks: BackgroundTasks,
    top_n: int = Query(20, ge=5, le=50, description="扫描热门板块数量"),
    min_change_pct: float = Query(0.0, description="最低涨幅筛选(%)"),
    dry_run: bool = Query(False, description="空跑模式，不写入 Neo4j"),
    allow_local_fallback: bool = Query(
        False,
        description="允许在外部板块源失败时使用本地行业分组；该模式不代表实时热门板块",
    ),
    session_factory=Depends(get_session_factory),
):
    """手动触发产业链发现（后台执行）"""
    if _discovery_status["running"]:
        return {"status": "already_running", "message": "产业链发现正在执行中，请稍后查看结果"}

    async def _run():
        from agents.chain_discovery import ChainDiscoveryAgent
        from agents.llm_client import LLMClient

        _discovery_status["running"] = True
        _discovery_status["result"] = None
        _discovery_status["error"] = None
        try:
            llm = LLMClient()
            agent = ChainDiscoveryAgent(session_factory, llm if llm.is_available() else None)
            result = await agent.run(
                {
                    "top_n": top_n,
                    "min_change_pct": min_change_pct,
                    "dry_run": dry_run,
                    "allow_local_fallback": allow_local_fallback,
                    "workflow_type": "chain_discovery",
                }
            )
            await llm.close()
            _discovery_status["result"] = _enrich_output(result.result)
        except Exception as e:
            _discovery_status["error"] = str(e)
        finally:
            _discovery_status["running"] = False

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "message": "产业链发现已在后台启动，通过 GET /discovery/status 查看进度",
    }


@router.get("/status")
async def discovery_status(db: AsyncSession = Depends(get_db)):
    """查看当前发现任务状态。

    API 重启会清空内存态，因此这里会回填最近一次持久化任务，避免前端误显示为“空闲”。
    """
    latest = await _latest_discovery_log(db)
    status = {**_discovery_status, "latest": latest, "from_history": False}
    if status.get("result"):
        status["result"] = _enrich_output(status["result"])
    if not status["running"] and status["result"] is None and status["error"] is None and latest:
        status["result"] = latest.get("output") or None
        status["error"] = latest.get("error")
        status["from_history"] = True
    return status


@router.get("/history")
async def discovery_history(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """查看产业链发现历史执行记录"""
    stmt = (
        select(AgentLog).where(AgentLog.agent_id == "chain_discovery").order_by(desc(AgentLog.created_at)).limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_serialize_log(r) for r in rows]
