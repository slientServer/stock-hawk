"""风险监控 Agent：基于真实候选池和行情风险字段生成预警。"""

from typing import Any

from agents.base import BaseAgent


class RiskMonitorAgent(BaseAgent):
    agent_id = "risk_monitor"

    async def _run_impl(self, params: dict[str, Any]) -> dict[str, Any]:
        from api.routes.advisor import _build_picks, _watch_alert_from_pick

        watch_codes = {str(code).zfill(6) for code in params.get("watch_codes") or [] if str(code).strip()}
        chain_id = params.get("chain_id")
        async with self._session_factory() as session:
            picks = await _build_picks(session, limit=100)

        alerts = []
        for item in picks.get("items", []):
            if watch_codes and item.get("code") not in watch_codes:
                continue
            if chain_id and chain_id not in (item.get("chain_names") or []):
                continue
            alert = _watch_alert_from_pick(item, score_threshold=75)
            if alert:
                alert["type"] = "stock_risk" if alert.get("level") == "warning" else "monitoring"
                alert["detail"] = "；".join(alert.get("reasons") or [])
                alert["affected_recommendations"] = [alert.get("code")]
                alerts.append(alert)

        data_gaps = []
        universe = picks.get("universe", {})
        candidate_count = universe.get("candidate_count") or 0
        if candidate_count and (universe.get("kline_coverage") or 0) < candidate_count:
            data_gaps.append("候选池K线覆盖不足，回撤和短期跌幅监控只覆盖部分候选股票")
        if watch_codes and not alerts:
            data_gaps.append("关注列表未触发已定义风险阈值，或关注标的不在当前候选池")

        return {
            "status": "completed",
            "risk_alerts": alerts,
            "data_gaps": data_gaps,
            "input": params,
            "confidence": "medium" if alerts else "low",
        }
