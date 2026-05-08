"""报告路由：研报生成、查看。"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_session_factory
from api.routes.graph_data import chain_topology_with_fallback
from agents.orchestrator import Orchestrator
from common.models import AgentLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["报告"])


class WorkflowRequest(BaseModel):
    workflow_type: str
    chain_id: str | None = None


def _output_text(output_data: Any) -> str:
    if isinstance(output_data, dict):
        for key in ("report", "content", "text", "summary"):
            if output_data.get(key):
                return str(output_data[key])
        return str(output_data)
    return str(output_data or "")


@router.get("")
async def list_reports(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = (
            await db.execute(
                select(AgentLog)
                .where(AgentLog.agent_id.in_(["report_writer", "chain_analyst", "stock_screener"]))
                .order_by(desc(AgentLog.created_at))
                .limit(limit)
            )
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
            "output_data": row.output_data,
            "output_text": _output_text(row.output_data),
            "duration_ms": row.duration_ms,
            "created_at": str(row.created_at) if row.created_at else None,
        }
        for row in rows
    ]


def _extract_structured_data(agent_id: str | None, output_data: dict) -> dict:
    """按 agent 类型提取结构化展示数据。"""
    if agent_id == "chain_analyst":
        return {
            "type": "chain_analysis",
            "score": output_data.get("score"),
            "trend_type": output_data.get("trend_type"),
            "current_stage": output_data.get("current_stage"),
            "stage_evidence": output_data.get("stage_evidence"),
            "driving_factors": output_data.get("driving_factors"),
            "transmission_path": output_data.get("transmission_path"),
            "signal_summary": output_data.get("signal_summary"),
            "financial_summary": output_data.get("financial_summary"),
            "data_gaps": output_data.get("data_gaps"),
            "confidence": output_data.get("confidence"),
        }
    if agent_id == "stock_screener":
        return {
            "type": "stock_screening",
            "recommendations": output_data.get("recommendations"),
            "universe": output_data.get("universe"),
            "methodology": output_data.get("methodology"),
            "data_gaps": output_data.get("data_gaps"),
            "confidence": output_data.get("confidence"),
        }
    if agent_id == "report_writer":
        return {
            "type": "report",
            "report_type": output_data.get("report_type"),
            "confidence": output_data.get("confidence"),
        }
    return {"type": "unknown"}


@router.get("/{report_id}")
async def get_report_detail(
    report_id: int,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(AgentLog, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")

    output_data = row.output_data or {}
    input_data = row.input_data or {}

    chain_id = (
        output_data.get("chain_id")
        or output_data.get("chain_name")
        or input_data.get("chain_id")
    )

    background = None
    if chain_id:
        try:
            topology = await chain_topology_with_fallback(chain_id)
            if topology:
                background = {
                    "chain": topology.get("chain"),
                    "segments": topology.get("segments"),
                    "technologies": topology.get("technologies"),
                    "products": topology.get("products"),
                    "company_count": len(topology.get("companies") or []),
                }
        except Exception as e:
            logger.warning(f"获取产业链背景数据失败: {e}")

    structured = _extract_structured_data(row.agent_id, output_data)

    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "task_id": row.task_id,
        "workflow_type": row.workflow_type,
        "status": row.status,
        "output_text": _output_text(output_data),
        "duration_ms": row.duration_ms,
        "created_at": str(row.created_at) if row.created_at else None,
        "background": background,
        "structured": structured,
    }


@router.post("/trigger")
async def trigger_workflow(req: WorkflowRequest, session_factory=Depends(get_session_factory)):
    workflow_type = req.workflow_type
    orchestrator = Orchestrator(session_factory)
    if workflow_type in {"daily", "daily_scan"}:
        return await orchestrator.run_daily_scan()
    if workflow_type in {"weekly", "weekly_analysis"}:
        return await orchestrator.run_weekly_analysis()
    if workflow_type in {"deep", "deep_research"}:
        return await orchestrator.run_deep_research(req.chain_id or "")
    if workflow_type in {"risk", "risk_check"}:
        return await orchestrator.run_risk_check(req.chain_id or "")
    return {"status": "failed", "error": f"Unknown workflow_type: {workflow_type}", "request": req.model_dump()}
