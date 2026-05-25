"""新闻事件采集器 - 财经快讯 + 个股新闻（东方财富/akshare）"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import akshare as ak
import pandas as pd

from common.logger import get_logger
from data_collector.cache.redis_cache import RedisCache
from data_collector.storage import DataStorage

logger = get_logger(__name__)


# 基于关键词的事件分类规则
EVENT_TYPE_RULES: dict[str, list[str]] = {
    "policy": ["政策", "补贴", "监管", "规划", "指导", "意见", "方案", "试点", "批复", "国务院", "工信部", "发改委"],
    "order": ["订单", "合同", "中标", "签约", "交付", "采购", "供货", "框架协议"],
    "tech_breakthrough": ["专利", "研发", "突破", "量产", "首发", "发布", "通过验证", "流片成功", "认证"],
    "personnel": ["董事长", "总经理", "辞职", "任命", "变更", "离任", "选举"],
    "earnings": ["业绩", "预增", "预盈", "预减", "预亏", "快报", "年报", "季报", "净利润"],
    "capital": ["增持", "减持", "回购", "定增", "配股", "分红", "股权激励"],
    "ipo": ["IPO", "上市", "科创板", "创业板", "招股", "获受理", "已问询", "过会", "注册", "辅导"],
}

SENTIMENT_POSITIVE = ["利好", "增长", "突破", "创新高", "超预期", "加速", "放量", "景气"]
SENTIMENT_NEGATIVE = ["利空", "下滑", "下降", "暴跌", "亏损", "违规", "处罚", "退市", "ST"]

# 股票代码正则 (6位数字)
CODE_PATTERN = re.compile(r"\b([036]\d{5})\b")


class NewsEventCollector:
    """新闻事件采集器"""

    def __init__(self, storage: DataStorage, cache: RedisCache | None = None):
        self.storage = storage
        self.cache = cache

    async def collect_latest_news(self, limit: int = 100) -> int:
        """采集最新东方财富快讯"""
        try:
            df = await asyncio.to_thread(ak.stock_news_em, symbol="")
        except Exception as e:
            logger.warning(f"采集东方财富快讯失败: {e}，尝试备选接口")
            try:
                df = await asyncio.to_thread(ak.stock_info_global_em)
            except Exception as e2:
                logger.error(f"所有新闻接口失败: {e2}")
                return 0

        if df is None or df.empty:
            logger.warning("新闻数据为空")
            return 0

        records = []
        for _, row in df.head(limit).iterrows():
            title = str(row.get("新闻标题") or row.get("title") or "").strip()
            if not title or len(title) < 5:
                continue

            content = str(row.get("新闻内容") or row.get("content") or "").strip() or None
            publish_time = self._parse_time(row.get("发布时间") or row.get("publish_time") or row.get("datetime"))
            if not publish_time:
                publish_time = datetime.now()

            related_codes = self._extract_related_codes(title, content or "")
            event_type = self._classify_event(title, content or "")
            sentiment = self._classify_sentiment(title, content or "")

            records.append({
                "title": title[:500],
                "content": (content or "")[:5000] or None,
                "publish_time": publish_time,
                "source": "eastmoney",
                "related_codes": related_codes if related_codes else None,
                "event_type": event_type,
                "sentiment": sentiment,
            })

        if records:
            await self.storage.upsert_news_events(records)
            logger.info(f"新闻采集完成: {len(records)} 条")
        return len(records)

    async def collect_stock_news(self, codes: list[str], limit_per_stock: int = 10) -> int:
        """采集个股新闻"""
        total = 0
        for code in codes:
            try:
                df = await asyncio.to_thread(ak.stock_news_em, symbol=code)
            except Exception as e:
                logger.debug(f"个股新闻 {code} 采集失败: {e}")
                await asyncio.sleep(1.0)
                continue

            if df is None or df.empty:
                await asyncio.sleep(0.5)
                continue

            records = []
            for _, row in df.head(limit_per_stock).iterrows():
                title = str(row.get("新闻标题") or "").strip()
                if not title or len(title) < 5:
                    continue
                content = str(row.get("新闻内容") or "").strip() or None
                publish_time = self._parse_time(row.get("发布时间"))
                if not publish_time:
                    publish_time = datetime.now()

                related_codes = self._extract_related_codes(title, content or "")
                if code not in related_codes:
                    related_codes.append(code)

                records.append({
                    "title": title[:500],
                    "content": (content or "")[:5000] or None,
                    "publish_time": publish_time,
                    "source": "eastmoney_stock",
                    "related_codes": related_codes,
                    "event_type": self._classify_event(title, content or ""),
                    "sentiment": self._classify_sentiment(title, content or ""),
                })

            if records:
                await self.storage.upsert_news_events(records)
                total += len(records)
            await asyncio.sleep(1.0)

        logger.info(f"个股新闻采集完成: {total} 条 (覆盖 {len(codes)} 只)")
        return total

    async def collect_incremental(self, codes: list[str] | None = None) -> int:
        """增量采集：先采全局快讯，再采重点股票"""
        today_str = datetime.now().strftime("%Y%m%d%H")
        marker_key = f"news:{today_str}"
        if self.cache and await self.cache.is_collected(marker_key, today_str):
            return 0

        total = await self.collect_latest_news(limit=100)
        if codes:
            total += await self.collect_stock_news(codes[:30], limit_per_stock=5)

        if self.cache and total > 0:
            await self.cache.set_incremental_marker(marker_key, today_str)
        return total

    @staticmethod
    def _classify_event(title: str, content: str) -> str | None:
        text = title + " " + content
        for event_type, keywords in EVENT_TYPE_RULES.items():
            for kw in keywords:
                if kw in text:
                    return event_type
        return None

    @staticmethod
    def _classify_sentiment(title: str, content: str) -> str | None:
        text = title + " " + content
        pos = sum(1 for kw in SENTIMENT_POSITIVE if kw in text)
        neg = sum(1 for kw in SENTIMENT_NEGATIVE if kw in text)
        if pos > neg:
            return "positive"
        if neg > pos:
            return "negative"
        if pos > 0 or neg > 0:
            return "neutral"
        return None

    @staticmethod
    def _extract_related_codes(title: str, content: str) -> list[str]:
        text = title + " " + content
        codes = CODE_PATTERN.findall(text)
        return list(dict.fromkeys(codes))[:10]

    @staticmethod
    def _parse_time(value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return pd.to_datetime(value).to_pydatetime()
        except Exception:
            return None
