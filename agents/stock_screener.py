"""选股 Agent：复用真实数据投研工作台评分并按产业链分层。"""

from typing import Any

from agents.base import BaseAgent


class StockScreenerAgent(BaseAgent):
    agent_id = "stock_screener"

    async def _run_impl(self, params: dict[str, Any]) -> dict[str, Any]:
        chain_ids = self._chain_ids(params)
        from api.routes.advisor import _build_picks

        async with self._session_factory() as session:
            picks = await _build_picks(session, limit=100)

        items = [
            item
            for item in picks.get("items", [])
            if self._is_supported(item) and (not chain_ids or set(item.get("chain_names") or []) & chain_ids)
        ]
        recommendations = {"core": [], "satellite": [], "watchlist": []}
        for item in items:
            bucket = self._bucket(item.get("score", 0))
            recommendations[bucket].append(self._payload(item))

        gaps = []
        if not items:
            gaps.append("没有找到同时具备图谱或信号支撑的候选标的")
        if picks.get("universe", {}).get("kline_stock_coverage", 0) < 100:
            gaps.append("K线覆盖不足，动量评分只覆盖少量股票")
        if picks.get("universe", {}).get("financial_stock_coverage", 0) < 100:
            gaps.append("财报覆盖不足，基本面评分置信度偏低")

        return {
            "status": "completed",
            "chain_ids": sorted(chain_ids),
            "recommendations": {key: value[:10] for key, value in recommendations.items()},
            "universe": picks.get("universe", {}),
            "methodology": picks.get("methodology"),
            "data_gaps": gaps,
            "input": params,
            "confidence": "medium" if items else "low",
        }

    @staticmethod
    def _chain_ids(params: dict[str, Any]) -> set[str]:
        ids = {str(params["chain_id"])} if params.get("chain_id") else set()
        for item in params.get("chains") or []:
            chain_id = item.get("chain_id") or item.get("chain_name") or item.get("name")
            if chain_id:
                ids.add(str(chain_id))
        return ids

    @staticmethod
    def _is_supported(item: dict[str, Any]) -> bool:
        quality = item.get("data_quality") or {}
        return bool(quality.get("has_graph") or item.get("signal_count"))

    @staticmethod
    def _bucket(score: float) -> str:
        if score >= 75:
            return "core"
        if score >= 60:
            return "satellite"
        return "watchlist"

    @staticmethod
    def _payload(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": item.get("code"),
            "name": item.get("name"),
            "score": item.get("score"),
            "tier": item.get("tier"),
            "chain_names": item.get("chain_names") or [],
            "segments": item.get("segments") or [],
            "signal_count": item.get("signal_count", 0),
            "logic": item.get("logic"),
            "risk_flags": item.get("risk_flags") or [],
            "metrics": item.get("metrics") or {},
            "financial": item.get("financial"),
            "data_quality": item.get("data_quality") or {},
        }
