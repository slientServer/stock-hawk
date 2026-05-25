"""催化板块分析：LLM优先 + 规则降级"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.llm_client import LLMClient
from common.models import FinanceNewsArticle, SectorCatalyst
from pre_market.config import PreMarketConfig

logger = logging.getLogger(__name__)

# 规则降级：板块 → 关键词
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "AI/算力": ["AI", "人工智能", "算力", "大模型", "GPU", "英伟达", "智算", "训练", "推理"],
    "半导体/芯片": ["芯片", "半导体", "光刻", "晶圆", "IC设计", "存储", "国产替代"],
    "光通信": ["光模块", "光纤", "光芯片", "400G", "800G", "光通信", "数据中心"],
    "新能源车": ["新能源车", "电动车", "锂电池", "固态电池", "充电桩", "智驾", "特斯拉"],
    "光伏/储能": ["光伏", "储能", "钙钛矿", "逆变器", "电站", "N型", "TOPCon"],
    "军工": ["军工", "国防", "导弹", "无人机", "航空发动机", "军费"],
    "医药/生物": ["创新药", "医药", "生物科技", "ADC", "减肥药", "GLP-1", "出海"],
    "机器人": ["机器人", "人形机器人", "具身智能", "工业机器人", "减速器"],
    "消费": ["消费", "双11", "618", "内需", "零售", "出行", "旅游", "免税"],
    "有色金属": ["铜", "黄金", "铝", "锂", "稀土", "贵金属", "铜价"],
    "煤炭/能源": ["煤炭", "煤价", "能源", "原油", "天然气", "电力"],
    "证券/金融": ["券商", "证券", "公募", "降息", "降准", "并购", "IPO"],
    "房地产": ["房地产", "地产", "楼市", "政策放松", "限购解除"],
    "商业航天": ["卫星", "火箭", "低轨", "商业航天", "发射", "星链"],
}


class CatalystAnalyzer:
    """分析昨夜新闻，识别催化板块，写入 sector_catalysts 表"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: PreMarketConfig | None = None,
        llm_client: LLMClient | None = None,
    ):
        self._session_factory = session_factory
        self.config = config or PreMarketConfig.load()
        self._llm = llm_client or LLMClient()

    async def analyze(self, trade_date: date) -> list[dict]:
        """
        分析当日催化板块。
        返回 list[{sector_name, catalyst_strength, catalyst_type, summary, related_codes}]
        """
        # 并行获取新闻和 ETF 热点板块
        news_result, etf_boards = await asyncio.gather(
            self._fetch_recent_news(trade_date),
            self._fetch_etf_hot_boards(),
            return_exceptions=True,
        )
        articles: list[dict] = news_result if not isinstance(news_result, Exception) else []
        etf_boards = etf_boards if not isinstance(etf_boards, Exception) else []
        if isinstance(news_result, Exception):
            logger.warning(f"[CatalystAnalyzer] 新闻获取异常: {news_result}")

        catalysts: list[dict] = []
        llm_used = False

        if articles:
            if self._llm.is_available():
                try:
                    catalysts = await self._analyze_with_llm(articles)
                    llm_used = True
                except Exception as e:
                    logger.warning(f"[CatalystAnalyzer] LLM调用失败，降级为规则分析: {e}")
            if not catalysts:
                catalysts = self._analyze_with_rules(articles)
        else:
            logger.warning(f"[CatalystAnalyzer] {trade_date} 无最近新闻数据，跳过新闻分析")

        # 补充 ETF 热点板块（新闻催化优先，ETF 仅补充缺失板块）
        if etf_boards:
            existing_sectors = {c["sector_name"] for c in catalysts}
            appended = 0
            for b in etf_boards:
                if b["sector_name"] not in existing_sectors:
                    catalysts.append(b)
                    appended += 1
            if appended:
                logger.info(f"[CatalystAnalyzer] ETF热点补充 {appended} 个板块，合计 {len(catalysts)} 个")

        if not catalysts:
            logger.info(f"[CatalystAnalyzer] {trade_date} 无有效催化板块")
            return []

        # 过滤弱催化
        catalysts = [c for c in catalysts if c.get("catalyst_strength", 0) >= self.config.agg_catalyst_strength_min]

        await self._persist(trade_date, catalysts, llm_used=llm_used)
        logger.info(f"[CatalystAnalyzer] {trade_date} 识别催化板块 {len(catalysts)} 个 (llm={llm_used})")
        return catalysts

    async def _fetch_etf_hot_boards(self) -> list[dict]:
        """从 ETF 分析服务获取当日热点板块，作为新闻催化的补充"""
        try:
            from api.routes.etf_analysis import _fetch_market_boards  # noqa: PLC0415
            boards_data = await _fetch_market_boards(top_hot=10, top_rotation=0)
            hot_boards = boards_data.get("hot_boards", [])
            if not hot_boards:
                return []

            catalysts = []
            for b in hot_boards:
                name = b.get("name", "")
                change_pct = b.get("change_pct") or 0
                capital_inflow = b.get("capital_inflow") or 0
                if not name or change_pct < 1.5 or capital_inflow <= 0:
                    continue

                if change_pct >= 5:
                    strength = 5
                elif change_pct >= 3:
                    strength = 4
                elif change_pct >= 2:
                    strength = 3
                else:
                    strength = 2

                catalysts.append({
                    "sector_name": name,
                    "catalyst_strength": strength,
                    "catalyst_type": "fund_flow",
                    "summary": b.get("reason") or f"ETF热点板块：当日涨幅{change_pct:.1f}%，主力净流入正值",
                    "related_codes": [],
                })

            logger.info(f"[CatalystAnalyzer] ETF热点板块: {len(catalysts)} 个有效板块")
            return catalysts
        except Exception as e:
            logger.warning(f"[CatalystAnalyzer] ETF热点板块获取失败（降级忽略）: {e}")
            return []

    async def get_catalysts(self, trade_date: date) -> list[dict]:
        """从DB读取已分析的催化板块"""
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(SectorCatalyst).where(SectorCatalyst.trade_date == trade_date)
                )
            ).scalars().all()
        return [
            {
                "sector_name": r.sector_name,
                "catalyst_strength": r.catalyst_strength,
                "catalyst_type": r.catalyst_type,
                "summary": r.summary,
                "related_codes": r.related_codes or [],
            }
            for r in rows
        ]

    async def _fetch_recent_news(self, trade_date: date) -> list[dict]:
        """取前一日18:00 ~ 当日07:00的新闻"""
        tz = timezone(timedelta(hours=8))
        end_dt = datetime(trade_date.year, trade_date.month, trade_date.day, 7, 0, 0, tzinfo=tz)
        start_dt = end_dt - timedelta(hours=self.config.news_lookback_hours)

        async with self._session_factory() as session:
            stmt = (
                select(FinanceNewsArticle.title, FinanceNewsArticle.content, FinanceNewsArticle.published_at)
                .where(
                    FinanceNewsArticle.published_at >= start_dt.replace(tzinfo=None),
                    FinanceNewsArticle.published_at <= end_dt.replace(tzinfo=None),
                )
                .order_by(FinanceNewsArticle.published_at.desc())
                .limit(self.config.news_max_articles)
            )
            rows = (await session.execute(stmt)).all()

        return [
            {
                "title": r.title or "",
                "content": (r.content or "")[:200],
                "published_at": str(r.published_at),
            }
            for r in rows
        ]

    async def _analyze_with_llm(self, articles: list[dict]) -> list[dict]:
        titles = "\n".join(f"- {a['title']}" for a in articles)
        messages = [
            {
                "role": "system",
                "content": (
                    "你是A股短线催化事件识别专家。分析以下资讯标题，"
                    "识别有明确催化事件的A股板块（政策利好、业绩超预期、技术突破、资金异动等）。"
                    "只输出JSON，不要任何解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"以下是最近财经资讯标题：\n{titles}\n\n"
                    "请输出有催化的板块列表，格式：\n"
                    '{"catalysts": [{"sector": "板块名", "catalyst_strength": 1-5, '
                    '"catalyst_type": "policy|earnings|tech|fund_flow|other", '
                    '"summary": "一句话说明催化事件", "related_codes": []}]}\n'
                    "catalyst_strength说明: 5=重大利好(政策/业绩爆雷级), 4=明确利好, 3=有一定催化, 2=弱催化, 1=无明显催化\n"
                    "只列出strength>=3的板块，最多8个。"
                ),
            },
        ]
        result = await self._llm.chat_json(messages, temperature=0.1, max_tokens=1024)
        catalysts = result.get("catalysts", [])
        return [
            {
                "sector_name": c.get("sector", ""),
                "catalyst_strength": int(c.get("catalyst_strength", 3)),
                "catalyst_type": c.get("catalyst_type", "other"),
                "summary": c.get("summary", ""),
                "related_codes": c.get("related_codes", []),
            }
            for c in catalysts
            if c.get("sector")
        ]

    def _analyze_with_rules(self, articles: list[dict]) -> list[dict]:
        """规则降级：统计各板块关键词出现频率"""
        counts: Counter[str] = Counter()
        all_text = " ".join(a["title"] + " " + a["content"] for a in articles)
        for sector, keywords in SECTOR_KEYWORDS.items():
            for kw in keywords:
                counts[sector] += len(re.findall(re.escape(kw), all_text, re.IGNORECASE))

        catalysts = []
        for sector, count in counts.most_common(8):
            if count == 0:
                continue
            if count >= 8:
                strength = 5
            elif count >= 5:
                strength = 4
            elif count >= 3:
                strength = 3
            elif count >= 1:
                strength = 2
            else:
                strength = 1
            catalysts.append({
                "sector_name": sector,
                "catalyst_strength": strength,
                "catalyst_type": "other",
                "summary": f"规则分析：相关词汇出现{count}次",
                "related_codes": [],
            })
        return catalysts

    async def _persist(self, trade_date: date, catalysts: list[dict], llm_used: bool) -> None:
        if not catalysts:
            return
        async with self._session_factory() as session:
            for c in catalysts:
                # upsert：先尝试查已有记录
                existing = (
                    await session.execute(
                        select(SectorCatalyst).where(
                            SectorCatalyst.trade_date == trade_date,
                            SectorCatalyst.sector_name == c["sector_name"],
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.catalyst_strength = c["catalyst_strength"]
                    existing.catalyst_type = c.get("catalyst_type", "other")
                    existing.summary = c.get("summary", "")
                    existing.related_codes = c.get("related_codes", [])
                    existing.llm_used = llm_used
                else:
                    session.add(SectorCatalyst(
                        trade_date=trade_date,
                        sector_name=c["sector_name"],
                        catalyst_strength=c["catalyst_strength"],
                        catalyst_type=c.get("catalyst_type", "other"),
                        summary=c.get("summary", ""),
                        related_news_ids=[],
                        related_codes=c.get("related_codes", []),
                        llm_used=llm_used,
                    ))
            await session.commit()
