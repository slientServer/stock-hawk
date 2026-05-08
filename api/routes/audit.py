"""审计路由：操作日志、信号追溯。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from common.models import AgentLog, CollectLog, DailyKline, FinancialReport, Signal, Stock
from knowledge_graph.neo4j_client import Neo4jClient

router = APIRouter(prefix="/audit", tags=["审计"])


@router.get("/stats")
async def audit_stats(db: AsyncSession = Depends(get_db)):
    try:
        agent_executions = (await db.execute(select(func.count()).select_from(AgentLog))).scalar() or 0
        agent_failures = (
            await db.execute(select(func.count()).select_from(AgentLog).where(AgentLog.status == "failed"))
        ).scalar() or 0
        collect_runs = (await db.execute(select(func.count()).select_from(CollectLog))).scalar() or 0
        signal_count = (await db.execute(select(func.count()).select_from(Signal))).scalar() or 0
    except Exception:
        return {
            "agent_executions": 0,
            "agent_failures": 0,
            "collect_runs": 0,
            "signal_count": 0,
            "status": "degraded",
        }
    return {
        "agent_executions": agent_executions,
        "agent_failures": agent_failures,
        "collect_runs": collect_runs,
        "signal_count": signal_count,
        "status": "ok",
    }


@router.get("/data-quality")
async def data_quality(db: AsyncSession = Depends(get_db)):
    try:
        stock_count = (await db.execute(select(func.count()).select_from(Stock))).scalar() or 0
        kline_count = (await db.execute(select(func.count()).select_from(DailyKline))).scalar() or 0
        kline_stock_count = (await db.execute(select(func.count(distinct(DailyKline.code))))).scalar() or 0
        financial_count = (await db.execute(select(func.count()).select_from(FinancialReport))).scalar() or 0
        financial_stock_count = (await db.execute(select(func.count(distinct(FinancialReport.code))))).scalar() or 0
    except Exception:
        return {
            "status": "blocked",
            "blocking_issues": ["数据库不可用，无法验证数据质量"],
            "warnings": [],
            "confidence": "low",
        }

    blocking_issues = []
    warnings = []
    details = {
        "stock_count": stock_count,
        "kline_count": kline_count,
        "kline_stock_coverage": kline_stock_count,
        "kline_coverage_ratio": _ratio(kline_stock_count, stock_count),
        "financial_count": financial_count,
        "financial_stock_coverage": financial_stock_count,
        "financial_coverage_ratio": _ratio(financial_stock_count, stock_count),
        "graph_stock_mismatches": [],
    }
    if stock_count == 0:
        blocking_issues.append("股票基础数据缺失")
    if kline_count == 0:
        warnings.append("K线数据缺失，信号和回测结果不可用")
    elif stock_count and kline_stock_count / stock_count < 0.2:
        warnings.append(f"K线覆盖不足：仅覆盖 {kline_stock_count}/{stock_count} 只股票")
    if financial_count == 0:
        warnings.append("财报数据缺失，业绩拐点信号不可用")
    elif stock_count and financial_stock_count / stock_count < 0.2:
        warnings.append(f"财报覆盖不足：仅覆盖 {financial_stock_count}/{stock_count} 只股票")
    mismatches = await _graph_stock_mismatches(db)
    if mismatches:
        details["graph_stock_mismatches"] = mismatches[:20]
        warnings.append(f"知识图谱公司与股票主数据存在 {len(mismatches)} 个代码/名称不一致")
    return {
        "status": "blocked" if blocking_issues else "ok",
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "confidence": "low" if blocking_issues else "medium" if warnings else "high",
        "details": details,
    }


def _ratio(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


async def _graph_stock_mismatches(db: AsyncSession) -> list[dict]:
    try:
        client = await Neo4jClient.get_instance()
        graph_rows = await client.run(
            """
            MATCH (c:Company)
            WHERE c.code IS NOT NULL AND c.name IS NOT NULL
            RETURN c.code AS code, c.name AS graph_name
            LIMIT 2000
            """
        )
    except Exception:
        return []
    codes = [row["code"] for row in graph_rows if row.get("code")]
    if not codes:
        return []
    stock_rows = (await db.execute(select(Stock.code, Stock.name).where(Stock.code.in_(codes)))).all()
    stock_names = {code: name for code, name in stock_rows}
    mismatches = []
    for row in graph_rows:
        code = row.get("code")
        graph_name = row.get("graph_name")
        stock_name = stock_names.get(code)
        if stock_name and graph_name and stock_name != graph_name:
            mismatches.append({"code": code, "graph_name": graph_name, "stock_name": stock_name})
    return mismatches


@router.get("/agent-logs")
async def agent_logs(
    agent_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AgentLog)
    if agent_id:
        stmt = stmt.where(AgentLog.agent_id == agent_id)
    try:
        rows = (
            await db.execute(stmt.order_by(desc(AgentLog.created_at)).limit(limit))
        ).scalars().all()
    except Exception:
        return []
    return [
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "task_id": row.task_id,
            "workflow_type": row.workflow_type,
            "status": row.status,
            "duration_ms": row.duration_ms,
            "tokens_used": row.tokens_used,
            "error_message": row.error_message,
            "created_at": str(row.created_at) if row.created_at else None,
        }
        for row in rows
    ]


@router.get("/collect-logs")
async def collect_logs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = (
            await db.execute(select(CollectLog).order_by(desc(CollectLog.started_at)).limit(limit))
        ).scalars().all()
    except Exception:
        return []
    return [
        {
            "id": row.id,
            "source": row.source,
            "task_type": row.task_type,
            "status": row.status,
            "records_count": row.records_count,
            "error_message": row.error_message,
            "started_at": str(row.started_at) if row.started_at else None,
            "finished_at": str(row.finished_at) if row.finished_at else None,
        }
        for row in rows
    ]
