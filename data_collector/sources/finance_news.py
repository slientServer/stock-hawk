"""财经资讯源采集与今日小结生成。"""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.llm_client import LLMClient
from common.config import get_settings
from common.logger import get_logger
from common.models import FinanceDailySummary, FinanceNewsArticle, FinanceNewsSource

logger = get_logger(__name__)

DEFAULT_FINANCE_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "name": "东方财富全球财经",
        "url": "akshare://stock_info_global_em",
        "source_type": "eastmoney_flash",
        "category": "A股",
        "enabled": True,
    },
    {
        "name": "Tushare 东财新闻",
        "url": "tushare://news/eastmoney",
        "source_type": "tushare_news",
        "category": "A股",
        "enabled": True,
    },
    {
        "name": "新浪财经滚动",
        "url": "https://rss.sina.com.cn/finance/rollnews.xml",
        "source_type": "rss",
        "category": "A股",
        "enabled": False,  # 新浪 RSS 经常失效，默认禁用
    },
    {
        "name": "CNBC Markets",
        "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "source_type": "rss",
        "category": "全球市场",
        "enabled": True,
    },
    {
        "name": "MarketWatch Top Stories",
        "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "source_type": "rss",
        "category": "全球市场",
        "enabled": True,
    },
    {
        "name": "Nasdaq Markets",
        "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
        "source_type": "rss",
        "category": "全球市场",
        "enabled": True,
    },
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def _clean_text(value: Any, limit: int | None = None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip()
    return text


def _normalize_key(value: str) -> str:
    return SPACE_RE.sub("", value.lower()).strip()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _article_hash(title: str, url: str | None, content: str | None) -> str:
    normalized_url = str(url or "").strip().lower()
    if normalized_url and not normalized_url.startswith("akshare://"):
        basis = normalized_url
    else:
        basis = f"{_normalize_key(title)}|{_normalize_key(content or '')[:500]}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _source_payload(row: FinanceNewsSource) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "url": row.url,
        "source_type": row.source_type,
        "category": row.category,
        "enabled": row.enabled,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _article_payload(row: FinanceNewsArticle) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "source_name": row.source_name,
        "title": row.title,
        "url": row.url,
        "content": row.content,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
    }


def _summary_payload(row: FinanceDailySummary | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "summary_date": row.summary_date.isoformat() if row.summary_date else None,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "title": row.title,
        "content": row.content,
        "key_points": row.key_points or [],
        "watch_items": row.watch_items or [],
        "article_ids": row.article_ids or [],
        "source_names": row.source_names or [],
        "article_count": row.article_count or 0,
        "source_count": row.source_count or 0,
        "llm_used": bool(row.llm_used),
        "model": row.model,
        "status": row.status,
        "data_gaps": row.data_gaps or [],
    }


class FinanceNewsService:
    """采集 RSS/内置财经资讯源，并生成可审计的今日小结。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def ensure_default_sources(self, session: AsyncSession) -> None:
        stmt = pg_insert(FinanceNewsSource).values(list(DEFAULT_FINANCE_SOURCES))
        stmt = stmt.on_conflict_do_update(
            index_elements=["source_type", "url"],
            set_={
                "name": stmt.excluded.name,
                "category": stmt.excluded.category,
                "updated_at": datetime.now(),
            },
        )
        await session.execute(stmt)
        await session.commit()

    async def list_sources(self, session: AsyncSession) -> list[dict[str, Any]]:
        await self.ensure_default_sources(session)
        rows = (
            await session.execute(
                select(FinanceNewsSource).order_by(FinanceNewsSource.enabled.desc(), FinanceNewsSource.id.asc())
            )
        ).scalars().all()
        return [_source_payload(row) for row in rows]

    async def collect_latest(self, limit_per_source: int = 40, use_llm: bool = True) -> dict[str, Any]:
        async with self.session_factory() as session:
            await self.ensure_default_sources(session)
            sources = (
                await session.execute(
                    select(FinanceNewsSource)
                    .where(FinanceNewsSource.enabled == True)  # noqa: E712
                    .order_by(FinanceNewsSource.id.asc())
                )
            ).scalars().all()

        semaphore = asyncio.Semaphore(5)

        async def fetch_one(source: FinanceNewsSource) -> tuple[FinanceNewsSource, list[dict[str, Any]], str | None]:
            async with semaphore:
                try:
                    records = await self._fetch_source(source, limit_per_source=limit_per_source)
                    return source, records, None
                except Exception as e:
                    logger.warning("finance source fetch failed: %s %s", source.name, e)
                    return source, [], str(e)

        fetched = await asyncio.gather(*(fetch_one(source) for source in sources))
        records = [record for _, items, _ in fetched for record in items]
        errors = [{"source": source.name, "error": error} for source, _, error in fetched if error]
        upsert_result = await self._upsert_articles(records)
        summary = await self.generate_daily_summary(date.today(), use_llm=use_llm)
        return {
            "status": "ok",
            "sources": len(sources),
            "fetched_count": len(records),
            "inserted_count": upsert_result["inserted_count"],
            "updated_count": upsert_result["updated_count"],
            "errors": errors,
            "summary": summary,
        }

    async def _fetch_source(self, source: FinanceNewsSource, limit_per_source: int) -> list[dict[str, Any]]:
        if source.source_type == "eastmoney_flash":
            return await self._fetch_eastmoney(source, limit_per_source)
        if source.source_type == "tushare_news":
            return await self._fetch_tushare_news(source, limit_per_source)
        return await self._fetch_rss(source, limit_per_source)

    async def _fetch_rss(self, source: FinanceNewsSource, limit_per_source: int) -> list[dict[str, Any]]:
        base_timeout = max(5, min(get_settings().data_source.market_request_timeout or 15, 60))
        # 境外源在境内网络经常超时，单独限短以免拖慢整体采集
        timeout = min(base_timeout, 8) if source.category == "全球市场" else base_timeout
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
            response = await client.get(source.url)
            response.raise_for_status()
        root = ET.fromstring(response.content)
        items = self._rss_items(root)
        now = datetime.now()
        records: list[dict[str, Any]] = []
        for item in items[:limit_per_source]:
            title = _clean_text(item.get("title"), 500)
            if len(title) < 4:
                continue
            content = _clean_text(item.get("content") or item.get("description"), 5000) or None
            url = str(item.get("link") or "").strip() or None
            published_at = _parse_datetime(item.get("published_at")) or now
            records.append(
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "title": title,
                    "url": url,
                    "content": content,
                    "published_at": published_at,
                    "fetched_at": now,
                    "content_hash": _article_hash(title, url, content),
                    "raw_metadata": {"source_type": source.source_type, "category": source.category},
                }
            )
        return records

    async def _fetch_tushare_news(self, source: FinanceNewsSource, limit_per_source: int) -> list[dict[str, Any]]:
        """通过 Tushare news 接口采集财经新闻（需 2000 积分）。

        URL 格式：tushare://news/<src>，src 可选 eastmoney/sina/wallstreetcn/10jqka 等。
        """
        token = get_settings().data_source.tushare_token
        if not token:
            raise RuntimeError("TUSHARE_TOKEN 未配置，无法采集 Tushare 新闻")
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError("Python package 'tushare' 未安装") from exc

        # 解析 src：tushare://news/eastmoney → eastmoney
        src = source.url.rsplit("/", 1)[-1] if "/" in source.url else "eastmoney"

        now = datetime.now()
        start = now - timedelta(hours=8)
        start_str = start.strftime("%Y-%m-%d %H:%M:%S")
        end_str = now.strftime("%Y-%m-%d %H:%M:%S")

        def _fetch():
            ts.set_token(token)
            pro = ts.pro_api(token)
            return pro.news(src=src, start_date=start_str, end_date=end_str)

        try:
            df = await asyncio.to_thread(_fetch)
        except Exception as exc:
            raise RuntimeError(f"Tushare news fetch failed (src={src}): {exc}") from exc

        if df is None or df.empty:
            return []

        records: list[dict[str, Any]] = []
        for _, row in df.head(limit_per_source).iterrows():
            title = _clean_text(row.get("title"), 500)
            if len(title) < 4:
                continue
            content = _clean_text(row.get("content") or "", 5000) or None
            url = str(row.get("url") or "").strip() or None
            published_at = _parse_datetime(row.get("datetime") or row.get("pub_time")) or now
            records.append(
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "title": title,
                    "url": url,
                    "content": content,
                    "published_at": published_at,
                    "fetched_at": now,
                    "content_hash": _article_hash(title, url, content),
                    "raw_metadata": {"source_type": "tushare_news", "category": source.category, "src": src},
                }
            )
        return records

    async def _fetch_eastmoney(self, source: FinanceNewsSource, limit_per_source: int) -> list[dict[str, Any]]:
        import akshare as ak

        try:
            df = await asyncio.to_thread(ak.stock_info_global_em)
        except Exception:
            df = await asyncio.to_thread(ak.stock_news_em, symbol="")
        if df is None or df.empty:
            return []

        now = datetime.now()
        records: list[dict[str, Any]] = []
        for _, row in df.head(limit_per_source).iterrows():
            title = _clean_text(
                row.get("标题") or row.get("新闻标题") or row.get("title") or row.get("事件") or row.get("内容"),
                500,
            )
            if len(title) < 4:
                continue
            content = _clean_text(row.get("摘要") or row.get("新闻内容") or row.get("content") or "", 5000) or None
            url = str(row.get("链接") or row.get("新闻链接") or row.get("url") or "").strip() or None
            published_at = _parse_datetime(
                row.get("发布时间") or row.get("时间") or row.get("datetime") or row.get("日期")
            ) or now
            records.append(
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "title": title,
                    "url": url,
                    "content": content,
                    "published_at": published_at,
                    "fetched_at": now,
                    "content_hash": _article_hash(title, url, content),
                    "raw_metadata": {"source_type": source.source_type, "category": source.category},
                }
            )
        return records

    @staticmethod
    def _rss_items(root: ET.Element) -> list[dict[str, Any]]:
        channel_items = root.findall(".//item")
        if channel_items:
            return [FinanceNewsService._rss_item_payload(item) for item in channel_items]
        atom_ns = "{http://www.w3.org/2005/Atom}"
        return [FinanceNewsService._atom_entry_payload(entry, atom_ns) for entry in root.findall(f".//{atom_ns}entry")]

    @staticmethod
    def _rss_item_payload(item: ET.Element) -> dict[str, Any]:
        def text(name: str) -> str | None:
            found = item.find(name)
            return found.text if found is not None else None

        content = None
        for child in item:
            if child.tag.endswith("encoded"):
                content = child.text
                break
        return {
            "title": text("title"),
            "link": text("link") or text("guid"),
            "description": text("description"),
            "content": content,
            "published_at": text("pubDate") or text("published") or text("updated"),
        }

    @staticmethod
    def _atom_entry_payload(entry: ET.Element, ns: str) -> dict[str, Any]:
        def text(name: str) -> str | None:
            found = entry.find(f"{ns}{name}")
            return found.text if found is not None else None

        link = None
        for item in entry.findall(f"{ns}link"):
            href = item.attrib.get("href")
            rel = item.attrib.get("rel")
            if href and (rel in {None, "", "alternate"}):
                link = href
                break
        return {
            "title": text("title"),
            "link": link,
            "description": text("summary"),
            "content": text("content"),
            "published_at": text("published") or text("updated"),
        }

    async def _upsert_articles(self, records: list[dict[str, Any]]) -> dict[str, int]:
        if not records:
            return {"inserted_count": 0, "updated_count": 0}
        unique_records = list({record["content_hash"]: record for record in records}.values())
        hashes = [record["content_hash"] for record in unique_records]
        async with self.session_factory() as session:
            existing = set(
                (
                    await session.execute(
                        select(FinanceNewsArticle.content_hash).where(FinanceNewsArticle.content_hash.in_(hashes))
                    )
                ).scalars().all()
            )
            stmt = pg_insert(FinanceNewsArticle).values(unique_records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["content_hash"],
                set_={
                    "source_id": stmt.excluded.source_id,
                    "source_name": stmt.excluded.source_name,
                    "title": stmt.excluded.title,
                    "url": stmt.excluded.url,
                    "content": stmt.excluded.content,
                    "published_at": stmt.excluded.published_at,
                    "fetched_at": stmt.excluded.fetched_at,
                    "raw_metadata": stmt.excluded.raw_metadata,
                },
            )
            await session.execute(stmt)
            await session.commit()
        inserted = len([h for h in hashes if h not in existing])
        return {"inserted_count": inserted, "updated_count": len(unique_records) - inserted}

    async def articles_for_date(
        self,
        session: AsyncSession,
        summary_date: date,
        limit: int = 200,
    ) -> list[FinanceNewsArticle]:
        start = datetime.combine(summary_date, time.min)
        end = start + timedelta(days=1)
        rows = (
            await session.execute(
                select(FinanceNewsArticle)
                .where(FinanceNewsArticle.published_at >= start)
                .where(FinanceNewsArticle.published_at < end)
                .order_by(desc(FinanceNewsArticle.published_at))
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def generate_daily_summary(self, summary_date: date, use_llm: bool = True) -> dict[str, Any]:
        async with self.session_factory() as session:
            articles = await self.articles_for_date(session, summary_date, limit=240)
        deduped = self._dedupe_articles(articles)
        if not deduped:
            payload = {
                "title": "今日财经小结",
                "content": "今日尚未采集到财经资讯。",
                "key_points": [],
                "watch_items": [],
                "article_ids": [],
                "source_names": [],
                "article_count": 0,
                "source_count": 0,
                "llm_used": False,
                "model": None,
                "status": "empty",
                "data_gaps": ["今日暂无入库资讯"],
            }
            return await self._save_summary(summary_date, payload)

        llm = LLMClient()
        data_gaps: list[str] = []
        if use_llm and llm.is_available():
            try:
                payload = await self._llm_summary(llm, summary_date, deduped[:80])
                payload["llm_used"] = True
                payload["model"] = get_settings().llm.custom_model or "custom"
            except Exception as e:
                logger.warning("finance daily llm summary failed: %s", e)
                data_gaps.append(f"LLM 汇总失败，已降级为规则化小结: {e}")
                payload = self._rule_summary(summary_date, deduped)
        else:
            data_gaps.append("LLM 未配置，已使用规则化标题去重小结")
            payload = self._rule_summary(summary_date, deduped)

        payload.setdefault("data_gaps", [])
        payload["data_gaps"] = [*payload["data_gaps"], *data_gaps]
        payload["article_ids"] = [article.id for article in deduped]
        payload["source_names"] = sorted({article.source_name or "未知来源" for article in deduped})
        payload["article_count"] = len(deduped)
        payload["source_count"] = len(payload["source_names"])
        payload.setdefault("status", "ok")
        return await self._save_summary(summary_date, payload)

    @staticmethod
    def _dedupe_articles(articles: list[FinanceNewsArticle]) -> list[FinanceNewsArticle]:
        seen: set[str] = set()
        deduped: list[FinanceNewsArticle] = []
        for article in articles:
            key = _normalize_key(article.title)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(article)
        return deduped

    async def _llm_summary(
        self,
        llm: LLMClient,
        summary_date: date,
        articles: list[FinanceNewsArticle],
    ) -> dict[str, Any]:
        article_lines = []
        for article in articles:
            article_lines.append(
                {
                    "id": article.id,
                    "time": article.published_at.isoformat() if article.published_at else None,
                    "source": article.source_name,
                    "title": article.title,
                    "content": _clean_text(article.content or "", 220),
                }
            )
        prompt = f"""请基于以下真实入库财经资讯生成 {summary_date.isoformat()} 的今日财经小结。

要求：
1. 先合并重复或同一事件的资讯，再总结，不得补造未提供事实。
2. 按重要性输出 5-8 条 key_points，覆盖 A股、全球市场、宏观政策、产业/公司事件。
3. content 为 300-600 字中文综述，结论先行。
4. watch_items 给出 3-6 个后续关注变量，不写投资建议。
5. 返回严格 JSON。

JSON 格式：
{{
  "title": "今日财经小结",
  "content": "...",
  "key_points": [
    {{"topic": "主题", "summary": "去重后的要点", "sources": ["来源"], "article_ids": [1, 2]}}
  ],
  "watch_items": ["关注变量1"]
}}

资讯列表：
{article_lines}
"""
        result = await llm.chat_json(
            [
                {"role": "system", "content": "你是严谨的财经资讯编辑，只能基于输入资讯做去重和总结。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=3000,
        )
        return {
            "title": str(result.get("title") or "今日财经小结")[:200],
            "content": _clean_text(result.get("content"), 6000),
            "key_points": result.get("key_points") if isinstance(result.get("key_points"), list) else [],
            "watch_items": result.get("watch_items") if isinstance(result.get("watch_items"), list) else [],
            "status": "ok",
            "data_gaps": [],
        }

    def _rule_summary(self, summary_date: date, articles: list[FinanceNewsArticle]) -> dict[str, Any]:
        top_articles = articles[:12]
        key_points = [
            {
                "topic": article.title[:80],
                "summary": _clean_text(article.content, 180) or article.title,
                "sources": [article.source_name or "未知来源"],
                "article_ids": [article.id],
            }
            for article in top_articles[:8]
        ]
        lines = [
            f"{idx + 1}. {article.title}（{article.source_name or '未知来源'}）"
            for idx, article in enumerate(top_articles[:8])
        ]
        content = f"{summary_date.isoformat()} 已采集 {len(articles)} 条去重财经资讯。"
        if lines:
            content += " 重点包括：" + "；".join(lines)
        return {
            "title": "今日财经小结",
            "content": content,
            "key_points": key_points,
            "watch_items": ["等待 LLM 配置后生成跨来源合并的关注变量"],
            "llm_used": False,
            "model": None,
            "status": "fallback",
            "data_gaps": [],
        }

    async def _save_summary(self, summary_date: date, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now()
        values = {
            "summary_date": summary_date,
            "generated_at": now,
            "title": payload.get("title") or "今日财经小结",
            "content": payload.get("content") or "",
            "key_points": payload.get("key_points") or [],
            "watch_items": payload.get("watch_items") or [],
            "article_ids": payload.get("article_ids") or [],
            "source_names": payload.get("source_names") or [],
            "article_count": int(payload.get("article_count") or 0),
            "source_count": int(payload.get("source_count") or 0),
            "llm_used": bool(payload.get("llm_used")),
            "model": payload.get("model"),
            "status": payload.get("status") or "ok",
            "data_gaps": payload.get("data_gaps") or [],
            "updated_at": now,
        }
        async with self.session_factory() as session:
            stmt = pg_insert(FinanceDailySummary).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["summary_date"],
                set_={key: getattr(stmt.excluded, key) for key in values if key != "summary_date"},
            ).returning(FinanceDailySummary)
            row = (await session.execute(stmt)).scalar_one()
            await session.commit()
            return _summary_payload(row) or {}
