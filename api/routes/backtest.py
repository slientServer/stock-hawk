"""回测路由：回测任务管理、结果查看。"""

from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_session_factory
from backtest.engine import BacktestEngine
from common.models import BacktestResult

router = APIRouter(prefix="/backtest", tags=["回测"])


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    signal_type: str | None = None
    chain_id: str | None = None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def _item(row: BacktestResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "signal_type": row.signal_type,
        "start_date": str(row.start_date) if row.start_date else None,
        "end_date": str(row.end_date) if row.end_date else None,
        "total_signals": row.total_signals or 0,
        "win_rate": _num(row.win_rate) or 0,
        "avg_return_30d": _num(row.avg_return_30d) or 0,
        "avg_return_60d": _num(row.avg_return_60d) or 0,
        "avg_return_90d": _num(row.avg_return_90d) or 0,
        "max_drawdown": _num(row.max_drawdown) or 0,
        "result_detail": row.result_detail,
        "created_at": str(row.created_at) if row.created_at else None,
    }


@router.get("/results")
async def list_results(
    task_id: str | None = Query(None),
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(BacktestResult)
    if task_id:
        stmt = stmt.where(BacktestResult.task_id == task_id)
    try:
        rows = (
            await db.execute(stmt.order_by(desc(BacktestResult.created_at)).limit(limit))
        ).scalars().all()
    except Exception:
        return []
    return [_item(row) for row in rows]


@router.post("/run")
async def run_backtest(req: BacktestRequest, session_factory=Depends(get_session_factory)):
    if req.start_date > req.end_date:
        raise HTTPException(status_code=400, detail="start_date must be earlier than or equal to end_date")
    engine = BacktestEngine(session_factory)
    return await engine.run(
        req.start_date,
        req.end_date,
        signal_type=req.signal_type,
        chain_id=req.chain_id,
    )
