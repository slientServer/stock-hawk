"""Automation routes: scheduler status, run history, and manual triggers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from agents.automation import AutomationRunner, get_automation_run, list_automation_runs
from api.deps import get_session_factory
from common.models import AgentLog

router = APIRouter(prefix="/automation", tags=["自动任务"])

WorkflowType = Literal[
    "daily_after_close",
    "daily_scan",
    "weekly_discovery",
    "weekly_analysis",
    "chain_discovery",
    "risk_check",
]


class AutomationTriggerRequest(BaseModel):
    workflow_type: WorkflowType
    params: dict[str, Any] = Field(default_factory=dict)


def _runner(request: Request) -> AutomationRunner:
    runner = getattr(request.app.state, "automation_runner", None)
    if runner is None:
        runner = AutomationRunner(get_session_factory())
        request.app.state.automation_runner = runner
    return runner


def _run_item(row: AgentLog) -> dict[str, Any]:
    output = row.output_data or {}
    input_data = row.input_data or {}
    heartbeat_at = output.get("heartbeat_at") or output.get("updated_at")
    heartbeat_age_seconds = None
    if heartbeat_at:
        try:
            heartbeat_age_seconds = int((datetime.now() - datetime.fromisoformat(str(heartbeat_at))).total_seconds())
        except (TypeError, ValueError):
            heartbeat_age_seconds = None
    return {
        "id": row.id,
        "task_id": row.task_id,
        "workflow_type": row.workflow_type,
        "status": row.status,
        "trigger": output.get("trigger") or input_data.get("trigger"),
        "started_at": output.get("started_at") or input_data.get("started_at"),
        "finished_at": output.get("finished_at"),
        "duration_ms": row.duration_ms or output.get("duration_ms"),
        "updated_at": output.get("updated_at"),
        "heartbeat_at": heartbeat_at,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale": row.status == "running" and heartbeat_age_seconds is not None and heartbeat_age_seconds > 180,
        "message": output.get("message"),
        "current_step": output.get("current_step"),
        "current_step_index": output.get("current_step_index"),
        "total_steps": output.get("total_steps"),
        "completed_steps": output.get("completed_steps"),
        "failed_steps": output.get("failed_steps"),
        "progress_percent": output.get("progress_percent"),
        "expected_steps": output.get("expected_steps") or input_data.get("expected_steps") or [],
        "steps": output.get("steps") or [],
        "error_message": row.error_message,
        "created_at": str(row.created_at) if row.created_at else None,
    }


@router.get("/jobs")
async def automation_jobs(request: Request):
    scheduler = getattr(request.app.state, "agent_scheduler", None)
    runner = _runner(request)
    jobs = scheduler.get_jobs() if scheduler else []
    return {
        "status": "started" if scheduler else "not_started",
        "running": runner.running_workflows(),
        "running_details": runner.running_details(),
        "jobs": jobs,
        "workflows": [
            {
                "workflow_type": "daily_after_close",
                "name": "交易日收盘自动流程",
                "description": "采集重点股票数据和资金流，随后执行每日信号扫描、归因和预警报告。",
            },
            {
                "workflow_type": "weekly_discovery",
                "name": "周末产业链发现与周报",
                "description": "发现新产业链，补采相关股票数据，随后执行周度扫描、筛选和周报。",
            },
            {
                "workflow_type": "daily_scan",
                "name": "仅信号扫描",
                "description": "不采集数据，直接扫描当前知识图谱中的产业链。",
            },
            {
                "workflow_type": "chain_discovery",
                "name": "仅产业链发现",
                "description": "只运行热门板块到产业链图谱的发现流程。",
            },
            {
                "workflow_type": "weekly_analysis",
                "name": "仅周度分析",
                "description": "不发现新链条，直接基于现有图谱执行周度扫描、筛选和周报。",
            },
            {
                "workflow_type": "risk_check",
                "name": "风险检查",
                "description": "检查当前关注标的和产业链的风险提示。",
            },
        ],
    }


@router.get("/runs")
async def automation_runs(
    workflow_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session_factory=Depends(get_session_factory),
):
    rows = await list_automation_runs(
        session_factory,
        workflow_type=workflow_type,
        status=status,
        limit=limit,
    )
    return [_run_item(row) for row in rows]


@router.get("/runs/{task_id}")
async def automation_run_detail(task_id: str, session_factory=Depends(get_session_factory)):
    row = await get_automation_run(session_factory, task_id)
    if not row:
        raise HTTPException(status_code=404, detail="automation run not found")
    return {
        **_run_item(row),
        "input_data": row.input_data,
        "output_data": row.output_data,
    }


@router.post("/trigger")
async def trigger_automation(req: AutomationTriggerRequest, background_tasks: BackgroundTasks, request: Request):
    runner = _runner(request)
    if runner.is_running(req.workflow_type):
        return {
            "status": "already_running",
            "workflow_type": req.workflow_type,
            "running": runner.running_workflows(),
            "running_details": runner.running_details(),
        }

    task_id = f"auto_{req.workflow_type}_{uuid.uuid4().hex[:8]}"[:50]
    background_tasks.add_task(
        runner.run,
        req.workflow_type,
        trigger="manual",
        params=req.params,
        task_id=task_id,
    )
    return {
        "status": "started",
        "workflow_type": req.workflow_type,
        "task_id": task_id,
        "message": "自动任务已启动，可通过 /automation/runs 查询执行情况",
    }
