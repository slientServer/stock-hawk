"""产业链路由：产业链查询、关系展示。"""

import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from common.models import ChainScore, Signal, Stock
from api.routes.graph_data import chain_topology_with_fallback, graph_chains_with_fallback

router = APIRouter(prefix="/chains", tags=["产业链"])


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else value


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


def _codes_from_payload(payload: Any) -> set[str]:
    if payload is None:
        return set()
    if isinstance(payload, str):
        try:
            return _codes_from_payload(json.loads(payload))
        except json.JSONDecodeError:
            code = _normalize_code(payload)
            return {code} if code else set()
    if isinstance(payload, list):
        return {code for item in payload if (code := _normalize_code(item))}
    if isinstance(payload, dict):
        codes: set[str] = set()
        for value in payload.values():
            codes.update(_codes_from_payload(value))
        return codes
    code = _normalize_code(payload)
    return {code} if code else set()


def _signal_codes(signal: Signal) -> set[str]:
    codes = _codes_from_payload(signal.target_codes)
    source = _normalize_code(signal.source_entity)
    if source:
        codes.add(source)
    if signal.detail:
        codes.update(match.group(0) for match in re.finditer(r"(?<!\d)\d{6}(?!\d)", signal.detail))
    return codes


async def _stock_name_map(db: AsyncSession, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    try:
        rows = (
            await db.execute(select(Stock.code, Stock.name).where(Stock.code.in_(codes)))
        ).all()
    except Exception:
        return {}
    return {str(code): str(name) for code, name in rows if code and name}


def _signal_item(signal: Signal, stock_names: dict[str, str]) -> dict[str, Any]:
    codes = sorted(_signal_codes(signal))
    return {
        "id": signal.id,
        "signal_type": signal.signal_type,
        "chain_id": signal.chain_id,
        "source_entity": signal.source_entity,
        "target_codes": signal.target_codes,
        "target_stocks": [
            {"code": code, "name": stock_names.get(code)}
            for code in codes
        ],
        "strength": _num(signal.strength),
        "confidence": _num(signal.confidence),
        "detail": signal.detail,
        "trigger_date": str(signal.trigger_date) if signal.trigger_date else None,
        "expire_date": str(signal.expire_date) if signal.expire_date else None,
        "source": signal.source,
    }


def _summary_from_topology(topology: dict[str, Any]) -> dict[str, Any]:
    chain = topology.get("chain") or {}
    name = chain.get("name")
    return {
        "chain_id": name,
        "chain_name": name,
        "name": name,
        "description": chain.get("description"),
        "status": chain.get("status", "active"),
        "segment_count": len(topology.get("segments", [])),
        "company_count": len(topology.get("companies", [])),
        "latest_score": None,
        "score": None,
        "score_date": None,
        "signal_count": 0,
        "data_source": topology.get("data_source", "neo4j"),
    }


@router.get("")
async def list_chains(limit: int = Query(20, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    chains = await graph_chains_with_fallback()
    chain_ids = [
        str(chain.get("chain_id") or chain.get("name") or chain.get("chain_name"))
        for chain in chains
        if chain.get("chain_id") or chain.get("name") or chain.get("chain_name")
    ]
    if not chain_ids:
        return chains[:limit]

    try:
        score_rows = (
            await db.execute(
                select(ChainScore)
                .where(ChainScore.chain_id.in_(chain_ids))
                .order_by(ChainScore.chain_id, desc(ChainScore.score_date), desc(ChainScore.created_at))
            )
        ).scalars().all()
        score_history: dict[str, list[ChainScore]] = {}
        for row in score_rows:
            bucket = score_history.setdefault(str(row.chain_id), [])
            if len(bucket) < 2:
                bucket.append(row)

        now = datetime.now()
        signal_counts = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    select(Signal.chain_id, func.count())
                    .where(
                        Signal.chain_id.in_(chain_ids),
                        (Signal.expire_date.is_(None)) | (Signal.expire_date >= now),
                    )
                    .group_by(Signal.chain_id)
                )
            ).all()
            if row[0]
        }
    except Exception:
        return chains[:limit]

    enriched = []
    for chain in chains:
        chain_id = str(chain.get("chain_id") or chain.get("name") or chain.get("chain_name") or "")
        history = score_history.get(chain_id, [])
        latest = history[0] if history else None
        previous = history[1] if len(history) > 1 else None
        latest_score = _num(latest.score) if latest else None
        previous_score = _num(previous.score) if previous else None
        signal_count = signal_counts.get(chain_id, 0)
        enriched.append(
            {
                **chain,
                "latest_score": latest_score,
                "score": latest_score,
                "previous_score": previous_score,
                "score_delta": (
                    round(float(latest_score) - float(previous_score), 2)
                    if latest_score is not None and previous_score is not None
                    else None
                ),
                "score_date": str(latest.score_date) if latest and latest.score_date else None,
                "signal_count": signal_count or 0,
                "score_detail": latest.score_detail if latest else None,
            }
        )

    enriched.sort(
        key=lambda item: (
            item.get("score") is not None,
            item.get("score") or -1,
            item.get("signal_count") or 0,
        ),
        reverse=True,
    )
    return enriched[:limit]


@router.get("/{chain_id}")
async def get_chain(chain_id: str, db: AsyncSession = Depends(get_db)):
    topology = await chain_topology_with_fallback(chain_id)
    if not topology:
        raise HTTPException(status_code=404, detail="Chain not found")

    latest_score = None
    signals = []
    active_signal_count = 0
    try:
        latest_score_row = (
            await db.execute(
                select(ChainScore)
                .where(ChainScore.chain_id == chain_id)
                .order_by(desc(ChainScore.score_date), desc(ChainScore.created_at))
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_score_row:
            latest_score = {
                "score": _num(latest_score_row.score),
                "score_detail": latest_score_row.score_detail,
                "signal_count": latest_score_row.signal_count or 0,
                "score_date": str(latest_score_row.score_date),
            }
        now = datetime.now()
        active_filter = (Signal.expire_date.is_(None)) | (Signal.expire_date >= now)
        active_signal_count = (
            await db.execute(
                select(func.count()).select_from(Signal).where(Signal.chain_id == chain_id, active_filter)
            )
        ).scalar() or 0
        signal_rows = (
            await db.execute(
                select(Signal)
                .where(Signal.chain_id == chain_id, active_filter)
                .order_by(desc(Signal.trigger_date), desc(Signal.created_at))
                .limit(200)
            )
        ).scalars().all()
        stock_names = await _stock_name_map(db, set().union(*[_signal_codes(s) for s in signal_rows]) if signal_rows else set())
        signals = [_signal_item(s, stock_names) for s in signal_rows]
    except Exception:
        pass

    detail = _summary_from_topology(topology)
    detail["latest_score"] = latest_score or {"score": None, "signal_count": 0, "score_date": None}
    detail["latest_score"]["signal_count"] = active_signal_count
    detail["active_signal_count"] = active_signal_count
    detail["segments"] = topology.get("segments", [])
    detail["companies"] = topology.get("companies", [])
    detail["signals"] = signals
    return detail


@router.get("/{chain_id}/scores")
async def get_chain_scores(
    chain_id: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = (
            await db.execute(
                select(ChainScore)
                .where(ChainScore.chain_id == chain_id)
                .order_by(desc(ChainScore.score_date))
                .limit(days)
            )
        ).scalars().all()
    except Exception:
        return []

    return [
        {
            "score_date": str(row.score_date),
            "score": _num(row.score),
            "score_detail": row.score_detail,
            "signal_count": row.signal_count or 0,
        }
        for row in reversed(rows)
    ]
