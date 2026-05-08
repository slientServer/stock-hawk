"""Agent 编排器：多 Agent 协作调度。"""

from typing import Any

from agents.chain_analyst import ChainAnalystAgent
from agents.report_writer import ReportWriterAgent
from agents.risk_monitor import RiskMonitorAgent
from agents.signal_scanner import SignalScannerAgent
from agents.stock_analysis import StockAnalysisAgent
from agents.stock_screener import StockScreenerAgent


class Orchestrator:
    def __init__(self, session_factory=None, llm_client=None):
        self.session_factory = session_factory
        self.llm_client = llm_client
        self._scanner = SignalScannerAgent(session_factory, llm_client)
        self._analyst = ChainAnalystAgent(session_factory, llm_client)
        self._stock_analysis = StockAnalysisAgent(session_factory, llm_client)
        self._screener = StockScreenerAgent(session_factory, llm_client)
        self._writer = ReportWriterAgent(session_factory, llm_client)
        self._risk = RiskMonitorAgent(session_factory, llm_client)

    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        workflow_type = params.get("workflow_type") or params.get("type")
        if workflow_type == "daily_scan":
            return await self.run_daily_scan()
        if workflow_type == "weekly_analysis":
            return await self.run_weekly_analysis()
        if workflow_type == "deep_research":
            return await self.run_deep_research(params.get("chain_id", ""))
        if workflow_type == "risk_check":
            return await self.run_risk_check(params.get("chain_id", ""), params.get("watch_codes"))
        if workflow_type == "stock_analysis":
            return await self.run_stock_analysis(params)
        return {"status": "failed", "error": f"Unknown workflow_type: {workflow_type}", "input": params}

    async def run_daily_scan(self) -> dict[str, Any]:
        scan = await self._scanner.run({"scope": "all_chains", "workflow_type": "daily_scan"})
        significant = [
            item
            for item in scan.result.get("results", [])
            if item.get("signal_count", 0) > 0 or item.get("score", 0) >= 30
        ]
        analyses = []
        for item in significant[:5]:
            result = await self._analyst.run(
                {
                    "chain_id": item.get("chain_id"),
                    "score": item.get("score"),
                    "workflow_type": "daily_scan",
                }
            )
            analyses.append(result.model_dump(mode="json"))
        report = await self._writer.run(
            {
                "type": "alert",
                "scan": scan.result,
                "analyses": analyses,
                "workflow_type": "daily_scan",
            }
        )
        return {
            "status": "completed",
            "workflow_type": "daily_scan",
            "scan": scan.model_dump(mode="json"),
            "significant_chains": significant,
            "analyses": analyses,
            "report": report.model_dump(mode="json"),
        }

    async def run_weekly_analysis(self) -> dict[str, Any]:
        scan = await self._scanner.run({"scope": "all_chains", "workflow_type": "weekly_analysis"})
        top_chains = sorted(scan.result.get("results", []), key=lambda item: item.get("score", 0), reverse=True)[:5]
        analyses = []
        for item in top_chains:
            result = await self._analyst.run(
                {
                    "chain_id": item.get("chain_id"),
                    "score": item.get("score"),
                    "workflow_type": "weekly_analysis",
                }
            )
            analyses.append(result.model_dump(mode="json"))
        picks = await self._screener.run({"chains": top_chains, "workflow_type": "weekly_analysis"})
        report = await self._writer.run(
            {
                "type": "weekly",
                "scan": scan.result,
                "analyses": analyses,
                "picks": picks.result,
                "workflow_type": "weekly_analysis",
            }
        )
        return {
            "status": "completed",
            "workflow_type": "weekly_analysis",
            "scan": scan.model_dump(mode="json"),
            "top_chains": top_chains,
            "analyses": analyses,
            "picks": picks.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
        }

    async def run_deep_research(self, chain_id: str) -> dict[str, Any]:
        if not chain_id:
            return {"status": "failed", "error": "chain_id required"}
        analysis = await self._analyst.run({"chain_id": chain_id, "workflow_type": "deep_research"})
        picks = await self._screener.run(
            {
                "chain_id": chain_id,
                "analysis": analysis.result,
                "workflow_type": "deep_research",
            }
        )
        report = await self._writer.run(
            {
                "type": "deep_research",
                "chain_id": chain_id,
                "analysis": analysis.result,
                "picks": picks.result,
                "workflow_type": "deep_research",
            }
        )
        return {
            "status": "completed",
            "workflow_type": "deep_research",
            "analysis": analysis.model_dump(mode="json"),
            "picks": picks.model_dump(mode="json"),
            "report": report.model_dump(mode="json"),
        }

    async def run_risk_check(
        self,
        chain_id: str = "",
        watch_codes: list[str] | None = None,
    ) -> dict[str, Any]:
        result = await self._risk.run(
            {
                "chain_id": chain_id,
                "watch_codes": watch_codes or [],
                "workflow_type": "risk_check",
            }
        )
        return {
            "status": "completed",
            "workflow_type": "risk_check",
            "risk": result.model_dump(mode="json"),
        }

    async def run_stock_analysis(self, params: dict[str, Any]) -> dict[str, Any]:
        result = await self._stock_analysis.run({**params, "workflow_type": "stock_analysis"})
        return {
            "status": "completed",
            "workflow_type": "stock_analysis",
            "analysis": result.model_dump(mode="json"),
        }

    async def run_chain_discovery(
        self,
        top_n: int = 20,
        min_change_pct: float = 0.0,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        from agents.chain_discovery import ChainDiscoveryAgent
        from agents.llm_client import LLMClient

        llm = LLMClient()
        try:
            agent = ChainDiscoveryAgent(self.session_factory, llm if llm.is_available() else None)
            result = await agent.run(
                {
                    "top_n": top_n,
                    "min_change_pct": min_change_pct,
                    "dry_run": dry_run,
                    "workflow_type": "chain_discovery",
                }
            )
            return result.model_dump(mode="json")
        finally:
            await llm.close()
