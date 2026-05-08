"""信号路由：信号列表、详情、历史。"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_session_factory
from common.models import Signal
from knowledge_graph.neo4j_client import Neo4jClient
from knowledge_graph.query import KnowledgeGraphQuery
from signal_engine import SignalEngine

router = APIRouter(prefix="/signals", tags=["信号"])

SIGNAL_TYPES = [
    "demand_inflection",
    "supply_shortage",
    "earnings_inflection",
    "chip_concentration",
    "overseas_mapping",
    "catalyst",
    "north_flow_stock",
    "sector_linkage",
    "valuation_percentile",
]

_scan_status = {
    "running": False,
    "progress": "idle",
    "total_chains": 0,
    "scanned_chains": 0,
    "signals_found": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


class ScanRequest(BaseModel):
    chain_id: str | None = None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


def _signal_item(row: Signal) -> dict[str, Any]:
    return {
        "id": row.id,
        "signal_type": row.signal_type,
        "chain_id": row.chain_id,
        "source_entity": row.source_entity,
        "target_codes": row.target_codes,
        "strength": _num(row.strength),
        "confidence": _num(row.confidence),
        "detail": row.detail,
        "raw_data_ref": row.raw_data_ref,
        "trigger_date": str(row.trigger_date) if row.trigger_date else None,
        "expire_date": str(row.expire_date) if row.expire_date else None,
        "source": row.source,
        "created_at": str(row.created_at) if row.created_at else None,
    }


@router.get("")
async def list_signals(
    chain_id: str | None = Query(None),
    signal_type: str | None = Query(None),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Signal)
    count_stmt = select(func.count()).select_from(Signal)
    if chain_id:
        stmt = stmt.where(Signal.chain_id == chain_id)
        count_stmt = count_stmt.where(Signal.chain_id == chain_id)
    if signal_type:
        stmt = stmt.where(Signal.signal_type == signal_type)
        count_stmt = count_stmt.where(Signal.signal_type == signal_type)

    try:
        total = (await db.execute(count_stmt)).scalar() or 0
        rows = (
            (
                await db.execute(
                    stmt.order_by(desc(Signal.trigger_date), desc(Signal.created_at)).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
    except Exception:
        return {"total": 0, "items": []}

    return {"total": total, "items": [_signal_item(row) for row in rows]}


@router.get("/types")
async def signal_types(db: AsyncSession = Depends(get_db)):
    try:
        rows = (
            await db.execute(
                select(Signal.signal_type, func.count())
                .where(Signal.signal_type.isnot(None))
                .group_by(Signal.signal_type)
            )
        ).all()
    except Exception:
        return [{"signal_type": signal_type, "count": 0} for signal_type in SIGNAL_TYPES]

    counts = {row[0]: row[1] for row in rows}
    types = sorted(set(SIGNAL_TYPES) | set(counts))
    return [{"signal_type": signal_type, "count": counts.get(signal_type, 0)} for signal_type in types]


async def _run_scan_background(req: ScanRequest):
    _scan_status.update(
        {
            "running": True,
            "progress": "starting",
            "total_chains": 0,
            "scanned_chains": 0,
            "signals_found": 0,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "error": None,
        }
    )
    try:
        engine = SignalEngine(get_session_factory())
        if req.chain_id:
            chains = [{"name": req.chain_id}]
        else:
            kg_query = KnowledgeGraphQuery(await Neo4jClient.get_instance())
            chains = await kg_query.list_chains()

        _scan_status["total_chains"] = len(chains)
        for chain in chains:
            chain_name = chain.get("name")
            if not chain_name:
                continue
            _scan_status["progress"] = f"scanning:{chain_name}"
            result = await engine.scan_chain(chain_name)
            _scan_status["scanned_chains"] += 1
            _scan_status["signals_found"] += result.signal_count

        _scan_status.update(
            {
                "running": False,
                "progress": "completed",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "error": None,
            }
        )
    except Exception as e:
        _scan_status.update(
            {
                "running": False,
                "progress": "failed",
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "error": str(e),
            }
        )


@router.post("/scan")
async def trigger_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    if _scan_status.get("running"):
        return {
            "status": "already_running",
            "message": "已有信号扫描任务正在执行",
            "current": _scan_status,
        }
    background_tasks.add_task(_run_scan_background, req)
    return {
        "status": "started",
        "message": "信号扫描已启动",
        "chain_id": req.chain_id,
    }


@router.get("/scan/status")
async def scan_status():
    return _scan_status
