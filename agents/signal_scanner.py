"""信号扫描 Agent：自动扫描市场信号。"""

from typing import Any

from agents.base import BaseAgent


class SignalScannerAgent(BaseAgent):
    agent_id = "signal_scanner"

    async def _run_impl(self, params: dict[str, Any]) -> dict[str, Any]:
        from knowledge_graph.neo4j_client import Neo4jClient
        from knowledge_graph.query import KnowledgeGraphQuery
        from signal_engine import SignalEngine

        engine = SignalEngine(self._session_factory, self._llm)
        chain_id = params.get("chain_id")
        if chain_id:
            results = [await engine.scan_chain(chain_id)]
        else:
            kg_query = KnowledgeGraphQuery(await Neo4jClient.get_instance())
            chains = await kg_query.list_chains()
            results = []
            for chain in chains:
                chain_name = chain.get("name")
                if chain_name:
                    results.append(await engine.scan_chain(chain_name))

        return {
            "status": "completed",
            "scope": "specific_chain" if chain_id else "all_chains",
            "results": [
                {
                    "chain_id": item.chain_id,
                    "score": float(item.score),
                    "level": item.level.value,
                    "signal_count": item.signal_count,
                    "score_date": str(item.score_date),
                    "detector_errors": item.detector_errors,
                }
                for item in results
            ],
            "input": params,
            "confidence": "medium" if results else "low",
        }
