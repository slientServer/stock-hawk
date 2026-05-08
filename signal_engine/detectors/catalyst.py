"""Catalyst detector - 催化剂信号检测

基于 news_events 表中的新闻事件数据，检测产业链相关的重大催化事件。
触发条件：近7天内出现政策/订单/技术突破类正面事件。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.dialects.postgresql import JSON

from common.models import NewsEvent
from signal_engine.base_detector import BaseDetector
from signal_engine.models import DetectionContext, SignalResult, SignalType

# 事件类型权重：政策 > 订单 > 技术突破 > 资本 > 业绩
EVENT_WEIGHTS: dict[str, float] = {
    "policy": 1.0,
    "order": 0.9,
    "tech_breakthrough": 0.8,
    "capital": 0.5,
    "earnings": 0.6,
    "personnel": 0.3,
}


class CatalystDetector(BaseDetector):
    signal_type = SignalType.CATALYST

    LOOKBACK_DAYS = 7
    MIN_EVENT_COUNT = 1

    async def _detect_impl(self, context: DetectionContext) -> list[SignalResult]:
        if not context.company_codes:
            return []

        signals: list[SignalResult] = []
        chain_id = context.chain_id
        cutoff = datetime.now() - timedelta(days=self.LOOKBACK_DAYS)

        async with self._session_factory() as session:
            # 查询与本产业链公司相关的近期正面新闻事件
            # news_events.related_codes 是 JSON 数组，需要匹配 company_codes
            events = await self._query_chain_events(
                session, context.company_codes, cutoff
            )

            if not events:
                return []

            # 按事件类型分组分析
            signal = self._analyze_events(events, chain_id, context)
            if signal:
                signals.append(signal)

        return signals

    async def _query_chain_events(
        self, session, codes: list[str], cutoff: datetime
    ) -> list:
        """查询产业链相关的新闻事件"""
        # 查找 related_codes 包含任意目标代码的新闻
        # 同时查找正面/中性情绪的重要事件类型
        conditions = [
            NewsEvent.publish_time >= cutoff,
            or_(
                NewsEvent.sentiment == "positive",
                NewsEvent.sentiment.is_(None),
            ),
            NewsEvent.event_type.in_(list(EVENT_WEIGHTS.keys())),
        ]

        result = await session.execute(
            select(NewsEvent)
            .where(and_(*conditions))
            .order_by(desc(NewsEvent.publish_time))
            .limit(200)
        )
        all_events = result.scalars().all()

        # 过滤：related_codes 中包含目标代码
        code_set = set(codes)
        matched = []
        for event in all_events:
            if event.related_codes:
                related = event.related_codes
                if isinstance(related, str):
                    import json
                    try:
                        related = json.loads(related)
                    except (json.JSONDecodeError, TypeError):
                        related = []
                if isinstance(related, list) and code_set.intersection(related):
                    matched.append(event)

        return matched

    def _analyze_events(
        self, events: list, chain_id: str, context: DetectionContext
    ) -> SignalResult | None:
        """分析事件集合，生成催化信号"""
        if len(events) < self.MIN_EVENT_COUNT:
            return None

        # 计算加权事件分数
        total_weight = 0.0
        event_details = []
        affected_codes: set[str] = set()

        for event in events[:20]:  # 最多分析20条
            event_type = event.event_type or "other"
            weight = EVENT_WEIGHTS.get(event_type, 0.2)
            total_weight += weight
            event_details.append(f"[{event_type}]{event.title[:50]}")

            if event.related_codes:
                related = event.related_codes
                if isinstance(related, str):
                    import json
                    try:
                        related = json.loads(related)
                    except (json.JSONDecodeError, TypeError):
                        related = []
                if isinstance(related, list):
                    affected_codes.update(related)

        # 信号强度：事件越多越重要越强
        strength = min(1.0, total_weight / 5.0)
        strength = max(0.3, strength)

        # 置信度：多事件交叉验证
        confidence = min(0.9, 0.4 + len(events) * 0.1)

        # 取最显著的事件作为 detail
        top_events = event_details[:5]
        detail = f"产业链催化事件({len(events)}条): " + "; ".join(top_events)

        target_codes = list(affected_codes.intersection(context.company_codes))[:10]
        if not target_codes:
            target_codes = context.company_codes[:5]

        return self._make_signal(
            chain_id=chain_id,
            source_entity=events[0].title[:100] if events else None,
            target_codes=target_codes,
            strength=strength,
            confidence=confidence,
            detail=detail[:500],
            raw_data_ref=f"catalyst:{chain_id}:{date.today()}",
            trigger_date=events[0].publish_time if events[0].publish_time else datetime.now(),
            expire_days=7,
            source="signal_engine:catalyst",
        )
