"""资讯中心 API：财经源管理、资讯拉取、今日小结和历史留存。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.deps import get_db, get_session_factory
from common.models import FinanceDailySummary, FinanceNewsArticle, FinanceNewsSource
from data_collector.sources.finance_news import (
    FinanceNewsService,
    _article_payload,
    _source_payload,
    _summary_payload,
)

router = APIRouter(prefix="/news-center", tags=["资讯中心"])


class FinanceSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    url: str = Field(min_length=8, max_length=1000)
    category: str | None = Field(default=None, max_length=50)
    source_type: str = Field(default="rss", max_length=30)
    enabled: bool = True


class FinanceSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    url: str | None = Field(default=None, min_length=8, max_length=1000)
    category: str | None = Field(default=None, max_length=50)
    enabled: bool | None = None


class CollectRequest(BaseModel):
    use_llm: bool = True
    limit_per_source: int = Field(default=40, ge=5, le=100)


def _validate_user_source(data: FinanceSourceCreate) -> None:
    if data.source_type not in {"rss", "atom"}:
        raise HTTPException(status_code=400, detail="自定义财经源当前仅支持 RSS/Atom")
    if not data.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="RSS/Atom URL 需要是 http(s) 地址")


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    service = FinanceNewsService(get_session_factory())
    return {"items": await service.list_sources(db)}


@router.post("/sources")
async def create_source(data: FinanceSourceCreate, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    _validate_user_source(data)
    source = FinanceNewsSource(
        name=data.name.strip(),
        url=data.url.strip(),
        source_type=data.source_type,
        category=data.category.strip() if data.category else None,
        enabled=data.enabled,
    )
    db.add(source)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"财经源已存在或保存失败: {e}") from e
    await db.refresh(source)
    return _source_payload(source)


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: int,
    data: FinanceSourceUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    source = await db.get(FinanceNewsSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="财经源不存在")
    if data.name is not None:
        source.name = data.name.strip()
    if data.url is not None:
        if source.source_type in {"rss", "atom"} and not data.url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="RSS/Atom URL 需要是 http(s) 地址")
        source.url = data.url.strip()
    if data.category is not None:
        source.category = data.category.strip() or None
    if data.enabled is not None:
        source.enabled = data.enabled
    await db.commit()
    await db.refresh(source)
    return _source_payload(source)


@router.delete("/sources/{source_id}")
async def disable_source(source_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    source = await db.get(FinanceNewsSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="财经源不存在")
    source.enabled = False
    await db.commit()
    return {"status": "disabled", "id": source_id}


@router.post("/collect")
async def collect_news(req: CollectRequest, session_factory=Depends(get_session_factory)) -> dict[str, Any]:
    service = FinanceNewsService(session_factory)
    return await service.collect_latest(limit_per_source=req.limit_per_source, use_llm=req.use_llm)


@router.post("/summarize")
async def summarize_today(
    summary_date: date | None = None,
    use_llm: bool = True,
    session_factory=Depends(get_session_factory),
) -> dict[str, Any]:
    service = FinanceNewsService(session_factory)
    return await service.generate_daily_summary(summary_date or date.today(), use_llm=use_llm)


@router.get("/today")
async def today_news(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    today = date.today()
    service = FinanceNewsService(get_session_factory())
    await service.ensure_default_sources(db)
    summary = (
        await db.execute(
            select(FinanceDailySummary)
            .where(FinanceDailySummary.summary_date == today)
            .order_by(desc(FinanceDailySummary.generated_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    articles = await service.articles_for_date(db, today, limit=100)
    return {
        "summary": _summary_payload(summary),
        "articles": [_article_payload(row) for row in articles],
        "article_count": len(articles),
    }


@router.get("/articles")
async def list_articles(
    target_date: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = FinanceNewsService(get_session_factory())
    rows = await service.articles_for_date(db, target_date or date.today(), limit=limit)
    return {"items": [_article_payload(row) for row in rows]}


@router.get("/summaries")
async def list_summaries(
    limit: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(FinanceDailySummary)
            .order_by(desc(FinanceDailySummary.summary_date), desc(FinanceDailySummary.generated_at))
            .limit(limit)
        )
    ).scalars().all()
    return {"items": [_summary_payload(row) for row in rows]}


@router.get("/summaries/{summary_date}")
async def get_summary(summary_date: date, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = (
        await db.execute(
            select(FinanceDailySummary)
            .where(FinanceDailySummary.summary_date == summary_date)
            .order_by(desc(FinanceDailySummary.generated_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="小结不存在")
    return _summary_payload(row) or {}


async def run_scheduled_finance_news(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    service = FinanceNewsService(session_factory)
    result = await service.collect_latest(limit_per_source=40, use_llm=True)
    result["trigger_type"] = "cron"
    result["finished_at"] = datetime.now().isoformat(timespec="seconds")
    return result
