"""Automation workflows for scheduled and manual operations."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.orchestrator import Orchestrator
from common.logger import get_logger
from common.models import AgentLog

logger = get_logger(__name__)


class AutomationRunner:
    """Run end-to-end scheduled workflows and persist one audit row per run."""

    agent_id = "automation_scheduler"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._lock = asyncio.Lock()
        self._running: set[str] = set()
        self._running_details: dict[str, dict[str, Any]] = {}

    def is_running(self, workflow_type: str | None = None) -> bool:
        if workflow_type:
            return workflow_type in self._running
        return bool(self._running)

    def running_workflows(self) -> list[str]:
        return sorted(self._running)

    def running_details(self) -> list[dict[str, Any]]:
        return [self._json_safe(self._running_details[key]) for key in sorted(self._running_details)]

    async def run(
        self,
        workflow_type: str,
        *,
        trigger: str = "manual",
        params: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        normalized = self._normalize_workflow_type(workflow_type)
        task_id = task_id or f"auto_{normalized}_{uuid.uuid4().hex[:8]}"[:50]
        started_at = datetime.now()
        expected_steps = self._expected_steps(normalized)
        steps: list[dict[str, Any]] = []

        async with self._lock:
            if normalized in self._running:
                details = self._running_details.get(normalized) or {}
                return {
                    "status": "already_running",
                    "workflow_type": normalized,
                    "task_id": details.get("task_id") or task_id,
                    "running": self.running_workflows(),
                    "running_details": self.running_details(),
                }
            self._running.add(normalized)
            self._running_details[normalized] = self._progress_payload(
                {
                    "task_id": task_id,
                    "workflow_type": normalized,
                    "trigger": trigger,
                    "started_at": started_at,
                    "expected_steps": expected_steps,
                    "steps": steps,
                },
                status="running",
            )

        log_id: int | None = None
        ctx: dict[str, Any] = {
            "task_id": task_id,
            "workflow_type": normalized,
            "trigger": trigger,
            "params": params,
            "started_at": started_at,
            "expected_steps": expected_steps,
            "steps": steps,
            "log_id": None,
        }
        status = "completed"
        error_message = ""
        result: dict[str, Any] = {}

        try:
            initial_output = self._progress_payload(ctx, status="running")
            log_id = await self._start_log(task_id, normalized, trigger, params, started_at, initial_output)
            ctx["log_id"] = log_id
            result = await self._execute(normalized, params, ctx)
        except Exception as e:
            logger.exception("Automation workflow failed: %s", normalized)
            status = "failed"
            error_message = str(e)
            result = {"error": error_message}
        finally:
            finished_at = datetime.now()
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            output = self._progress_payload(
                ctx,
                status=status,
                result=result,
                error_message=error_message,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
            if log_id is not None:
                await self._finish_log(log_id, status, output, duration_ms, error_message)
            async with self._lock:
                self._running.discard(normalized)
                self._running_details.pop(normalized, None)

        return {
            "status": status,
            "workflow_type": normalized,
            "task_id": task_id,
            "steps": steps,
            "result": result,
            "error": error_message or None,
        }

    async def _execute(self, workflow_type: str, params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        if workflow_type == "daily_after_close":
            return await self._daily_after_close(params, ctx)
        if workflow_type == "weekly_discovery":
            return await self._weekly_discovery(params, ctx)
        if workflow_type == "daily_scan":
            return await self._step(ctx, "daily_scan", lambda: Orchestrator(self._session_factory).run_daily_scan())
        if workflow_type == "weekly_analysis":
            return await self._step(
                ctx,
                "weekly_analysis",
                lambda: Orchestrator(self._session_factory).run_weekly_analysis(),
            )
        if workflow_type == "chain_discovery":
            top_n = int(params.get("top_n", 20))
            min_change_pct = float(params.get("min_change_pct", 0.0))
            dry_run = bool(params.get("dry_run", False))
            return await self._step(
                ctx,
                "chain_discovery",
                lambda: Orchestrator(self._session_factory).run_chain_discovery(
                    top_n=top_n,
                    min_change_pct=min_change_pct,
                    dry_run=dry_run,
                ),
            )
        if workflow_type == "risk_check":
            return await self._step(
                ctx,
                "risk_check",
                lambda: Orchestrator(self._session_factory).run_risk_check(
                    chain_id=str(params.get("chain_id") or ""),
                    watch_codes=params.get("watch_codes"),
                ),
            )
        raise ValueError(f"Unknown automation workflow_type: {workflow_type}")

    async def _daily_after_close(self, params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        days = int(params.get("days", 180))
        years = int(params.get("years", 3))
        result: dict[str, Any] = {}
        result["news_events"] = await self._step(
            ctx,
            "collect_news",
            lambda: self._collect("news_events"),
        )
        result["commodity_prices"] = await self._step(
            ctx,
            "collect_commodity",
            lambda: self._collect("commodity_prices"),
        )
        result["focus_data"] = await self._step(
            ctx,
            "collect_focus_data",
            lambda: self._collect("focus_all", days=days, years=years),
        )
        result["fund_flow"] = await self._step(
            ctx,
            "collect_fund_flow",
            lambda: self._collect("fund_flow", days=min(days, 365), years=years),
        )
        result["stock_detail"] = await self._step(
            ctx,
            "collect_stock_detail",
            lambda: self._collect("stock_detail"),
        )
        result["daily_scan"] = await self._step(
            ctx,
            "daily_scan",
            lambda: Orchestrator(self._session_factory).run_daily_scan(),
        )
        return result

    async def _weekly_discovery(self, params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        top_n = int(params.get("top_n", 20))
        min_change_pct = float(params.get("min_change_pct", 0.0))
        dry_run = bool(params.get("dry_run", False))
        days = int(params.get("days", 365))
        years = int(params.get("years", 3))
        result: dict[str, Any] = {}
        result["overseas_stocks"] = await self._step(
            ctx,
            "collect_overseas",
            lambda: self._collect("overseas_stocks"),
        )
        result["institutional_holdings"] = await self._step(
            ctx,
            "collect_holdings",
            lambda: self._collect("institutional_holdings"),
        )
        result["chain_discovery"] = await self._step(
            ctx,
            "chain_discovery",
            lambda: Orchestrator(self._session_factory).run_chain_discovery(
                top_n=top_n,
                min_change_pct=min_change_pct,
                dry_run=dry_run,
            ),
        )
        result["focus_data"] = await self._step(
            ctx,
            "collect_focus_data",
            lambda: self._collect("focus_all", days=days, years=years),
        )
        result["weekly_analysis"] = await self._step(
            ctx,
            "weekly_analysis",
            lambda: Orchestrator(self._session_factory).run_weekly_analysis(),
        )
        return result

    async def _collect(self, task: str, *, days: int | None = None, years: int | None = None) -> dict[str, Any]:
        # Reuse the same collection implementation as the manual data page.
        from api.routes.stocks import DataCollectRequest, _run_collect_task

        payload: dict[str, Any] = {"task": task}
        if days is not None:
            payload["days"] = days
        if years is not None:
            payload["years"] = years
        return await _run_collect_task(DataCollectRequest(**payload))

    async def _step(self, ctx: dict[str, Any], name: str, fn: Callable[[], Awaitable[Any]]) -> Any:
        started = datetime.now()
        entry: dict[str, Any] = {
            "name": name,
            "status": "running",
            "started_at": started.isoformat(timespec="seconds"),
            "heartbeat_at": started.isoformat(timespec="seconds"),
        }
        steps: list[dict[str, Any]] = ctx["steps"]
        steps.append(entry)
        start = time.time()
        await self._persist_progress(ctx, status="running")
        heartbeat_task = asyncio.create_task(self._heartbeat(ctx, entry))
        try:
            result = await fn()
            entry.update(
                {
                    "status": "completed",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "duration_ms": int((time.time() - start) * 1000),
                    "summary": self._summary(result),
                }
            )
            await self._persist_progress(ctx, status="running")
            return result
        except Exception as e:
            entry.update(
                {
                    "status": "failed",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "duration_ms": int((time.time() - start) * 1000),
                    "error": str(e),
                }
            )
            await self._persist_progress(ctx, status="failed", error_message=str(e))
            raise
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _heartbeat(self, ctx: dict[str, Any], entry: dict[str, Any]) -> None:
        while True:
            await asyncio.sleep(15)
            now = datetime.now()
            entry["heartbeat_at"] = now.isoformat(timespec="seconds")
            entry["elapsed_ms"] = int((now - datetime.fromisoformat(entry["started_at"])).total_seconds() * 1000)
            await self._persist_progress(ctx, status="running")

    async def _persist_progress(self, ctx: dict[str, Any], *, status: str, error_message: str = "") -> None:
        try:
            payload = self._progress_payload(ctx, status=status, error_message=error_message)
            workflow_type = str(ctx["workflow_type"])
            async with self._lock:
                if workflow_type in self._running:
                    self._running_details[workflow_type] = payload

            log_id = ctx.get("log_id")
            if log_id is None:
                return

            async with self._session_factory() as session:
                row = await session.get(AgentLog, log_id)
                if not row:
                    return
                row.output_data = self._json_safe(payload)
                if status == "failed":
                    row.status = "failed"
                    row.error_message = error_message or None
                await session.commit()
        except Exception:
            logger.warning("Failed to persist automation progress", exc_info=True)

    async def _start_log(
        self,
        task_id: str,
        workflow_type: str,
        trigger: str,
        params: dict[str, Any],
        started_at: datetime,
        initial_output: dict[str, Any],
    ) -> int:
        async with self._session_factory() as session:
            row = AgentLog(
                agent_id=self.agent_id,
                task_id=task_id,
                workflow_type=workflow_type,
                input_data={
                    "workflow_type": workflow_type,
                    "trigger": trigger,
                    "params": self._json_safe(params),
                    "started_at": started_at.isoformat(timespec="seconds"),
                    "expected_steps": initial_output.get("expected_steps") or [],
                },
                output_data=self._json_safe(initial_output),
                status="running",
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return int(row.id)

    async def _finish_log(
        self,
        log_id: int,
        status: str,
        output: dict[str, Any],
        duration_ms: int,
        error_message: str,
    ) -> None:
        async with self._session_factory() as session:
            row = await session.get(AgentLog, log_id)
            if not row:
                return
            row.status = status
            row.output_data = self._json_safe(output)
            row.duration_ms = duration_ms
            row.error_message = error_message or None
            await session.commit()

    @staticmethod
    def _expected_steps(workflow_type: str) -> list[str]:
        return {
            "daily_after_close": ["collect_news", "collect_commodity", "collect_focus_data", "collect_fund_flow", "collect_stock_detail", "daily_scan"],
            "weekly_discovery": ["collect_overseas", "collect_holdings", "chain_discovery", "collect_focus_data", "weekly_analysis"],
            "daily_scan": ["daily_scan"],
            "weekly_analysis": ["weekly_analysis"],
            "chain_discovery": ["chain_discovery"],
            "risk_check": ["risk_check"],
        }.get(workflow_type, [])

    def _progress_payload(
        self,
        ctx: dict[str, Any],
        *,
        status: str,
        result: Any | None = None,
        error_message: str = "",
        finished_at: datetime | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        now = datetime.now()
        steps = self._json_safe(ctx.get("steps") or [])
        expected_steps = list(ctx.get("expected_steps") or [])
        total_steps = len(expected_steps) or len(steps)
        completed_steps = sum(1 for step in steps if step.get("status") == "completed")
        failed_steps = sum(1 for step in steps if step.get("status") == "failed")
        running_step = next((step for step in steps if step.get("status") == "running"), None)
        current_step = running_step.get("name") if running_step else (steps[-1].get("name") if steps else None)
        current_step_index = None
        if current_step:
            if current_step in expected_steps:
                current_step_index = expected_steps.index(current_step) + 1
            else:
                current_step_index = len(steps)

        if status == "completed":
            progress_percent = 100
        elif total_steps:
            progress_percent = min(99, int((completed_steps / total_steps) * 100))
        else:
            progress_percent = 0

        if running_step and current_step_index and total_steps:
            message = f"正在执行 {running_step['name']}（{current_step_index}/{total_steps}）"
        elif status == "failed":
            message = error_message or "任务失败"
        elif status == "completed":
            message = "任务完成"
        elif completed_steps and total_steps:
            message = f"已完成 {completed_steps}/{total_steps} 步，等待下一步"
        else:
            message = "任务已启动，等待第一步"

        payload: dict[str, Any] = {
            "status": status,
            "workflow_type": ctx.get("workflow_type"),
            "task_id": ctx.get("task_id"),
            "trigger": ctx.get("trigger"),
            "started_at": ctx["started_at"].isoformat(timespec="seconds")
            if isinstance(ctx.get("started_at"), datetime)
            else ctx.get("started_at"),
            "updated_at": now.isoformat(timespec="seconds"),
            "heartbeat_at": now.isoformat(timespec="seconds"),
            "expected_steps": expected_steps,
            "steps": steps,
            "current_step": current_step,
            "current_step_index": current_step_index,
            "total_steps": total_steps,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "progress_percent": progress_percent,
            "message": message,
        }
        if finished_at:
            payload["finished_at"] = finished_at.isoformat(timespec="seconds")
        if duration_ms is not None:
            payload["duration_ms"] = duration_ms
        if result is not None:
            payload["result"] = result
        if error_message:
            payload["error_message"] = error_message
        return self._json_safe(payload)

    @staticmethod
    def _normalize_workflow_type(value: str) -> str:
        aliases = {
            "daily": "daily_after_close",
            "daily_after_close": "daily_after_close",
            "after_close": "daily_after_close",
            "daily_scan": "daily_scan",
            "weekly": "weekly_discovery",
            "weekly_discovery": "weekly_discovery",
            "weekly_discovery_report": "weekly_discovery",
            "weekly_analysis": "weekly_analysis",
            "chain_discovery": "chain_discovery",
            "risk": "risk_check",
            "risk_check": "risk_check",
        }
        return aliases.get(value, value)

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    @classmethod
    def _summary(cls, value: Any) -> dict[str, Any]:
        safe = cls._json_safe(value)
        if isinstance(safe, dict):
            summary: dict[str, Any] = {}
            for key in (
                "status",
                "workflow_type",
                "total_signals",
                "valid_signals",
                "signals_found",
                "hot_boards_scanned",
                "new_chains",
                "top_chains",
                "significant_chains",
            ):
                if key in safe:
                    val = safe[key]
                    summary[key] = len(val) if isinstance(val, list) else val
            if not summary:
                summary["keys"] = list(safe.keys())[:10]
            return summary
        if isinstance(safe, list):
            return {"items": len(safe)}
        return {"value": safe}


async def list_automation_runs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[AgentLog]:
    async with session_factory() as session:
        stmt = select(AgentLog).where(AgentLog.agent_id == AutomationRunner.agent_id)
        if workflow_type:
            stmt = stmt.where(AgentLog.workflow_type == AutomationRunner._normalize_workflow_type(workflow_type))
        if status:
            stmt = stmt.where(AgentLog.status == status)
        rows = (
            await session.execute(stmt.order_by(AgentLog.created_at.desc(), AgentLog.id.desc()).limit(limit))
        ).scalars().all()
        return list(rows)


async def get_automation_run(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: str,
) -> AgentLog | None:
    async with session_factory() as session:
        return (
            await session.execute(
                select(AgentLog)
                .where(AgentLog.agent_id == AutomationRunner.agent_id, AgentLog.task_id == task_id)
                .limit(1)
            )
        ).scalar_one_or_none()
