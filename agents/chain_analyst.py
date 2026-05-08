"""产业链分析 Agent：基于真实图谱、信号和财报做规则化归因。"""

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from agents.base import BaseAgent
from common.models import ChainScore, FinancialReport, Signal
from knowledge_graph.neo4j_client import Neo4jClient
from knowledge_graph.query import KnowledgeGraphQuery


class ChainAnalystAgent(BaseAgent):
    agent_id = "chain_analyst"

    async def _run_impl(self, params: dict[str, Any]) -> dict[str, Any]:
        chain_id = params.get("chain_id")
        if not chain_id:
            return {"status": "failed", "blocking_issues": ["chain_id is required"], "input": params, "confidence": "low"}

        kg_query = KnowledgeGraphQuery(await Neo4jClient.get_instance())
        topology = await kg_query.query_chain_topology(chain_id)
        segments = (topology or {}).get("segments", [])
        companies = (topology or {}).get("companies", [])
        code_segment = self._code_segment_map(segments)

        async with self._session_factory() as session:
            signals = (
                await session.execute(
                    select(Signal)
                    .where(Signal.chain_id == chain_id)
                    .order_by(desc(Signal.trigger_date), desc(Signal.created_at), desc(Signal.id))
                    .limit(50)
                )
            ).scalars().all()
            latest_score = (
                await session.execute(
                    select(ChainScore)
                    .where(ChainScore.chain_id == chain_id)
                    .order_by(desc(ChainScore.score_date), desc(ChainScore.created_at))
                    .limit(1)
                )
            ).scalar_one_or_none()
            financials = await self._latest_financials(session, set(code_segment))

        signal_types = Counter(signal.signal_type for signal in signals if signal.signal_type)
        segment_signal_count = self._segment_signal_count(signals, code_segment)
        transmission_path = self._transmission_path(segments, segment_signal_count)
        top_segment = max(transmission_path, key=lambda item: item["signal_count"], default=None)
        score = self._num(latest_score.score) if latest_score else self._num(params.get("score"))
        data_gaps = self._data_gaps(topology, signals, latest_score, set(code_segment), financials)

        return {
            "status": "completed",
            "chain_id": chain_id,
            "chain_name": chain_id,
            "score": score,
            "score_date": str(latest_score.score_date) if latest_score and latest_score.score_date else None,
            "driving_factors": self._driving_factors(signals, signal_types),
            "trend_type": self._trend_type(signal_types, score),
            "current_stage": self._stage(signal_types, score, len(signals)),
            "stage_evidence": self._stage_evidence(score, len(signals), signal_types),
            "transmission_path": transmission_path,
            "max_elasticity_segment": top_segment["segment"] if top_segment and top_segment["signal_count"] else None,
            "elasticity_reason": self._elasticity_reason(top_segment),
            "signal_summary": {
                "total": len(signals),
                "types": dict(signal_types),
                "latest": [self._signal_payload(signal) for signal in signals[:8]],
            },
            "graph_summary": {
                "segment_count": len(segments),
                "company_count": len(companies),
                "data_source": (topology or {}).get("data_source"),
            },
            "financial_summary": self._financial_summary(financials),
            "data_gaps": data_gaps,
            "input": params,
            "confidence": self._confidence(topology, signals, latest_score, data_gaps),
        }

    @staticmethod
    def _num(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _target_codes(signal: Signal) -> set[str]:
        values: list[Any] = []
        payload = signal.target_codes
        if isinstance(payload, list):
            values.extend(payload)
        elif isinstance(payload, dict):
            for item in payload.values():
                values.extend(item if isinstance(item, list) else [item])
        elif payload:
            values.append(payload)
        if signal.source_entity:
            values.append(signal.source_entity)

        codes = set()
        for value in values:
            text = str(value or "").strip().upper()
            if "." in text:
                text = text.split(".", 1)[0]
            if text.startswith(("SH", "SZ", "BJ")):
                text = text[2:]
            if text.isdigit():
                codes.add(text.zfill(6))
        return codes

    @staticmethod
    def _code_segment_map(segments: list[dict[str, Any]]) -> dict[str, str]:
        mapping = {}
        for segment in segments:
            name = segment.get("segment_name") or segment.get("name") or "未分组"
            for company in segment.get("companies", []):
                code = company.get("code")
                if code:
                    mapping[str(code)] = str(name)
        return mapping

    @classmethod
    def _segment_signal_count(cls, signals: list[Signal], code_segment: dict[str, str]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for signal in signals:
            for code in cls._target_codes(signal):
                segment = code_segment.get(code)
                if segment:
                    counts[segment] += 1
        return counts

    @staticmethod
    async def _latest_financials(session, codes: set[str]) -> dict[str, FinancialReport]:
        if not codes:
            return {}
        rows = (
            await session.execute(
                select(FinancialReport)
                .where(FinancialReport.code.in_(codes))
                .order_by(FinancialReport.code, desc(FinancialReport.report_date))
            )
        ).scalars().all()
        latest: dict[str, FinancialReport] = {}
        for row in rows:
            latest.setdefault(row.code, row)
        return latest

    @staticmethod
    def _transmission_path(
        segments: list[dict[str, Any]],
        segment_signal_count: dict[str, int],
    ) -> list[dict[str, Any]]:
        rows = []
        for segment in segments:
            name = segment.get("segment_name") or segment.get("name") or "未分组"
            signal_count = segment_signal_count.get(str(name), 0)
            rows.append(
                {
                    "position": segment.get("position"),
                    "segment": name,
                    "company_count": len(segment.get("companies", [])),
                    "signal_count": signal_count,
                    "status": "confirmed" if signal_count else "data_missing",
                }
            )
        return rows

    @staticmethod
    def _driving_factors(signals: list[Signal], signal_types: Counter) -> str:
        if not signals:
            return "暂无近期入库信号，无法给出真实驱动归因。"
        top_types = "、".join(name for name, _ in signal_types.most_common(3)) or "未分类信号"
        details = [str(signal.detail) for signal in signals[:3] if signal.detail]
        if details:
            return f"近期主要由 {top_types} 驱动；代表信号：" + "；".join(details)
        return f"近期主要由 {top_types} 驱动；信号明细缺失。"

    @staticmethod
    def _trend_type(signal_types: Counter, score: float | None) -> str:
        if signal_types.get("catalyst"):
            return "event_driven"
        if len(signal_types) >= 3 and (score or 0) >= 30:
            return "structural"
        if signal_types.get("sector_linkage"):
            return "market_momentum"
        return "data_insufficient"

    @staticmethod
    def _stage(signal_types: Counter, score: float | None, signal_count: int) -> str:
        value = score or 0
        if value >= 75:
            return "overheated"
        if value >= 60 or len(signal_types) >= 4:
            return "consensus"
        if signal_count:
            return "verification"
        return "watching"

    @staticmethod
    def _stage_evidence(score: float | None, signal_count: int, signal_types: Counter) -> str:
        type_text = "、".join(signal_types.keys()) or "无"
        score_text = "缺失" if score is None else f"{score:.2f}"
        return f"最新评分 {score_text}，近期信号 {signal_count} 个，覆盖类型：{type_text}。"

    @staticmethod
    def _elasticity_reason(top_segment: dict[str, Any] | None) -> str:
        if not top_segment or not top_segment.get("signal_count"):
            return "暂无足够信号定位弹性环节"
        return (
            f"{top_segment.get('segment')} 环节关联信号 {top_segment.get('signal_count')} 个，"
            f"覆盖公司 {top_segment.get('company_count')} 家。"
        )

    @classmethod
    def _signal_payload(cls, signal: Signal) -> dict[str, Any]:
        return {
            "signal_type": signal.signal_type,
            "strength": cls._num(signal.strength),
            "confidence": cls._num(signal.confidence),
            "detail": signal.detail,
            "target_codes": sorted(cls._target_codes(signal)),
            "trigger_date": cls._dt(signal.trigger_date),
            "source": signal.source,
        }

    @classmethod
    def _financial_summary(cls, financials: dict[str, FinancialReport]) -> dict[str, Any]:
        reports = list(financials.values())
        revenue_growth = [cls._num(row.revenue_yoy) for row in reports if cls._num(row.revenue_yoy) is not None]
        profit_growth = [cls._num(row.net_profit_yoy) for row in reports if cls._num(row.net_profit_yoy) is not None]
        return {
            "covered_companies": len(reports),
            "avg_revenue_yoy": round(sum(revenue_growth) / len(revenue_growth), 2) if revenue_growth else None,
            "avg_net_profit_yoy": round(sum(profit_growth) / len(profit_growth), 2) if profit_growth else None,
            "latest_report_date": max((str(row.report_date) for row in reports if row.report_date), default=None),
        }

    @staticmethod
    def _data_gaps(
        topology: dict[str, Any] | None,
        signals: list[Signal],
        latest_score: ChainScore | None,
        codes: set[str],
        financials: dict[str, FinancialReport],
    ) -> list[str]:
        gaps = []
        if not topology:
            gaps.append("知识图谱拓扑缺失")
        if not signals:
            gaps.append("近期信号缺失")
        if not latest_score:
            gaps.append("产业链评分缺失")
        if codes and len(financials) < len(codes):
            gaps.append(f"财报覆盖不足：{len(financials)}/{len(codes)}")
        if not codes:
            gaps.append("图谱公司代码缺失")
        return gaps

    @staticmethod
    def _confidence(
        topology: dict[str, Any] | None,
        signals: list[Signal],
        latest_score: ChainScore | None,
        data_gaps: list[str],
    ) -> str:
        if topology and signals and latest_score and len(data_gaps) <= 1:
            return "high"
        if topology and (signals or latest_score):
            return "medium"
        return "low"

    @staticmethod
    def _dt(value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        return str(value) if value else None
