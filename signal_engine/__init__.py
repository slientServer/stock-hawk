"""信号检测引擎：产业链多维度信号检测与评分"""

from datetime import date
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.logger import get_logger
from common.models import DailyKline
from signal_engine.base_detector import BaseDetector
from signal_engine.detectors import create_all_detectors, create_detector
from signal_engine.history import SignalHistory
from signal_engine.models import (
    SIGNAL_WEIGHTS,
    DetectionContext,
    ScoreLevel,
    ScoreResult,
    SignalResult,
    SignalType,
)
from signal_engine.scoring import ScoringEngine

logger = get_logger(__name__)


class SignalEngine:
    """信号引擎门面类

    用法:
        engine = SignalEngine(session_factory, llm_client)
        result = await engine.scan_chain("光通信产业链")
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], llm_client: Any = None):
        self._session_factory = session_factory
        self._llm = llm_client
        self._detectors = create_all_detectors(session_factory, llm_client)
        self._scoring = ScoringEngine()
        self._history = SignalHistory(session_factory)

    async def scan_chain(self, chain_name: str, run_date: date | None = None) -> ScoreResult:
        """对单条产业链执行完整扫描: 检测 -> 评分 -> 持久化"""
        if run_date is None:
            run_date = date.today()

        context = await self._build_context(chain_name, run_date)

        all_signals: list[SignalResult] = []
        detector_errors: list[dict[str, str]] = []
        for detector in self._detectors:
            try:
                signals = await detector.detect(context)
                all_signals.extend(signals)
            except Exception as e:
                detector_errors.append(
                    {
                        "signal_type": detector.signal_type.value,
                        "error": str(e),
                    }
                )

        if all_signals:
            await self._history.save_signals(all_signals)

        # 动态权重：根据市场阶段调整
        market_stage = await self._detect_market_stage(run_date)
        score_result = self._scoring.calculate_score(
            chain_id=context.chain_id,
            signals=all_signals,
            score_date=run_date,
            market_stage=market_stage,
            detector_errors=detector_errors,
        )

        await self._history.save_score(score_result)

        logger.info(f"Scan completed: chain={chain_name} " f"signals={len(all_signals)} score={score_result.score}")
        return score_result

    async def scan_all_chains(self, run_date: date | None = None) -> list[ScoreResult]:
        """扫描所有产业链"""
        from knowledge_graph.neo4j_client import Neo4jClient
        from knowledge_graph.query import KnowledgeGraphQuery

        client = await Neo4jClient.get_instance()
        kg_query = KnowledgeGraphQuery(client)
        chains = await kg_query.list_chains()

        results: list[ScoreResult] = []
        for chain_info in chains:
            chain_name = chain_info.get("name", "")
            if not chain_name:
                continue
            try:
                result = await self.scan_chain(chain_name, run_date)
                results.append(result)
            except Exception as e:
                logger.error(f"Scan failed for chain={chain_name}: {e}")

        return results

    async def _detect_market_stage(self, run_date: date) -> str:
        """通过上证指数 MA20/MA60 判断市场阶段"""
        try:
            from datetime import timedelta

            start = run_date - timedelta(days=90)
            async with self._session_factory() as session:
                stmt = (
                    select(DailyKline.close)
                    .where(
                        and_(
                            DailyKline.code.in_(["000001", "sh000001", "000001.SH"]),
                            DailyKline.trade_date >= start,
                            DailyKline.trade_date <= run_date,
                        )
                    )
                    .order_by(DailyKline.trade_date)
                )
                result = await session.execute(stmt)
                closes = [float(r[0]) for r in result.all() if r[0]]

            if len(closes) < 60:
                return "neutral"

            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / 60

            if ma20 > ma60 * 1.02:
                return "bull"
            elif ma20 < ma60 * 0.98:
                return "bear"
            return "neutral"
        except Exception:
            return "neutral"

    async def _build_context(self, chain_name: str, run_date: date) -> DetectionContext:
        """从知识图谱构建检测上下文"""
        from knowledge_graph.neo4j_client import Neo4jClient
        from knowledge_graph.query import KnowledgeGraphQuery

        client = await Neo4jClient.get_instance()
        kg_query = KnowledgeGraphQuery(client)
        topology = await kg_query.query_chain_topology(chain_name)

        company_codes: list[str] = []
        segments: list[dict] = []
        for seg in topology.get("segments", []):
            segments.append(
                {
                    "name": seg.get("segment_name", ""),
                    "position": seg.get("position", ""),
                    "uid": seg.get("uid", ""),
                }
            )
            for comp in seg.get("companies", []):
                code = comp.get("code", "")
                if code and code not in company_codes:
                    company_codes.append(code)

        return DetectionContext(
            chain_id=chain_name,
            chain_name=chain_name,
            company_codes=company_codes,
            segments=segments,
            run_date=run_date,
        )


__all__ = [
    "SignalEngine",
    "SignalResult",
    "ScoreResult",
    "SignalType",
    "ScoreLevel",
    "DetectionContext",
    "BaseDetector",
    "ScoringEngine",
    "SignalHistory",
    "SIGNAL_WEIGHTS",
    "create_all_detectors",
    "create_detector",
]
