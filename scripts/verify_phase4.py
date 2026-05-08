"""Phase 4 验证脚本：Agent Framework (Supervisor+Worker)"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = 0
FAIL = 0


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def check(condition: bool, msg: str):
    if condition:
        ok(msg)
    else:
        fail(msg)


# ─── TEST 1: Module imports ───────────────────────────────────
def test_imports():
    print("=" * 60)
    print("TEST 1: Module imports")
    print("=" * 60)

    try:
        from agents.base import AgentResult, BaseAgent
        check(True, "agents.base (AgentResult, BaseAgent)")
    except Exception as e:
        fail(f"agents.base: {e}")

    try:
        from agents.llm_client import LLMClient
        check(True, "agents.llm_client (LLMClient)")
    except Exception as e:
        fail(f"agents.llm_client: {e}")

    try:
        from agents.tools.base_tool import BaseTool, ToolResult
        from agents.tools.signal_tools import SignalTools
        from agents.tools.graph_tools import GraphTools
        from agents.tools.market_tools import MarketTools
        from agents.tools.stock_data_tools import StockDataTools
        from agents.tools.notification_tools import NotificationTools
        check(True, "agents.tools (tool classes importable)")
    except Exception as e:
        fail(f"agents.tools: {e}")

    try:
        from agents.signal_scanner import SignalScannerAgent
        from agents.chain_analyst import ChainAnalystAgent
        from agents.stock_analysis import StockAnalysisAgent
        from agents.stock_screener import StockScreenerAgent
        from agents.report_writer import ReportWriterAgent
        from agents.risk_monitor import RiskMonitorAgent
        check(True, "All worker agents importable")
    except Exception as e:
        fail(f"Worker agents: {e}")

    try:
        from agents.orchestrator import Orchestrator
        check(True, "agents.orchestrator (Orchestrator)")
    except Exception as e:
        fail(f"agents.orchestrator: {e}")

    try:
        from agents.scheduler import AgentScheduler
        check(True, "agents.scheduler (AgentScheduler)")
    except Exception as e:
        fail(f"agents.scheduler: {e}")

    try:
        from agents import (
            AgentResult, BaseAgent, LLMClient, Orchestrator,
            AgentScheduler, SignalScannerAgent, ChainAnalystAgent, ChainDiscoveryAgent,
            StockAnalysisAgent, StockScreenerAgent, ReportWriterAgent, RiskMonitorAgent,
        )
        check(True, "agents.__init__ top-level re-exports")
    except Exception as e:
        fail(f"agents.__init__: {e}")

    print()


# ─── TEST 2: AgentResult model ────────────────────────────────
def test_agent_result():
    print("=" * 60)
    print("TEST 2: AgentResult Pydantic model")
    print("=" * 60)

    from agents.base import AgentResult

    r = AgentResult(
        agent_id="test_agent",
        task_id="task_001",
        result={"key": "value"},
        metadata={"execution_time_ms": 100},
    )
    check(r.agent_id == "test_agent", "agent_id field")
    check(r.task_id == "task_001", "task_id field")
    check(r.status == "completed", "default status='completed'")
    check(r.result == {"key": "value"}, "result dict")
    check(r.error_message == "", "default error_message=''")
    check(isinstance(r.created_at, datetime), "created_at is datetime")

    # Serialize
    d = r.model_dump()
    check("agent_id" in d and "metadata" in d, "model_dump() works")
    print()


# ─── TEST 3: LLMClient ────────────────────────────────────────
def test_llm_client():
    print("=" * 60)
    print("TEST 3: LLMClient configuration")
    print("=" * 60)

    from agents.llm_client import LLMClient

    client = LLMClient()
    avail = client.is_available()
    print(f"  LLM available: {avail}")
    print(f"  Providers configured: {len(client._providers)}")
    for p in client._providers:
        print(f"    - {p['name']}: model={p['model']}")

    check(isinstance(avail, bool), "is_available() returns bool")
    check(hasattr(client, "chat"), "has chat() method")
    check(hasattr(client, "chat_json"), "has chat_json() method")
    check(hasattr(client, "last_call_count"), "has last_call_count")
    check(hasattr(client, "last_tokens_used"), "has last_tokens_used")
    print()


# ─── TEST 4: ToolResult model ─────────────────────────────────
def test_tool_result():
    print("=" * 60)
    print("TEST 4: ToolResult & BaseTool")
    print("=" * 60)

    from agents.tools.base_tool import BaseTool, ToolResult

    r = ToolResult(success=True, data={"x": 1})
    check(r.success is True, "ToolResult success")
    check(r.data == {"x": 1}, "ToolResult data")

    r2 = ToolResult(success=False, error="boom")
    check(r2.success is False, "ToolResult failure")
    check(r2.error == "boom", "ToolResult error msg")

    check(hasattr(BaseTool, "_safe_execute"), "BaseTool has _safe_execute")
    print()


# ─── TEST 5: Worker agent instantiation (mock DB) ─────────────
def test_worker_agents():
    print("=" * 60)
    print("TEST 5: Worker agent instantiation (mocked session)")
    print("=" * 60)

    from agents.signal_scanner import SignalScannerAgent
    from agents.chain_analyst import ChainAnalystAgent
    from agents.stock_analysis import StockAnalysisAgent
    from agents.stock_screener import StockScreenerAgent
    from agents.report_writer import ReportWriterAgent
    from agents.risk_monitor import RiskMonitorAgent

    mock_sf = MagicMock()

    agents_map = {
        "signal_scanner": SignalScannerAgent,
        "chain_analyst": ChainAnalystAgent,
        "stock_analysis": StockAnalysisAgent,
        "stock_screener": StockScreenerAgent,
        "report_writer": ReportWriterAgent,
        "risk_monitor": RiskMonitorAgent,
    }

    for agent_id, cls in agents_map.items():
        try:
            agent = cls(mock_sf, llm_client=None)
            check(agent.agent_id == agent_id, f"{cls.__name__}.agent_id = '{agent_id}'")
            check(hasattr(agent, "run"), f"{cls.__name__} has run()")
            check(hasattr(agent, "_run_impl"), f"{cls.__name__} has _run_impl()")
            check(hasattr(agent, "_run_fallback"), f"{cls.__name__} has _run_fallback()")
        except Exception as e:
            fail(f"{cls.__name__} instantiation: {e}")

    print()


# ─── TEST 6: BaseAgent.run() template method (mock) ───────────
async def test_base_agent_run():
    print("=" * 60)
    print("TEST 6: BaseAgent.run() template method")
    print("=" * 60)

    from agents.base import BaseAgent, AgentResult

    class MockAgent(BaseAgent):
        agent_id = "mock_agent"

        async def _run_impl(self, params):
            return {"processed": True, "input": params}

        async def _run_fallback(self, params):
            return {"fallback": True, "input": params}

    # Mock session factory to avoid DB
    mock_sf = MagicMock()
    mock_session = AsyncMock()
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

    agent = MockAgent(mock_sf, llm_client=None)

    # Should call _run_fallback (no LLM)
    result = await agent.run({"test": "data"}, task_id="test_123")
    check(isinstance(result, AgentResult), "Returns AgentResult")
    check(result.status == "degraded", "Status = degraded (no LLM)")
    check(result.result.get("fallback") is True, "Used fallback path")
    check(result.task_id == "test_123", "task_id preserved")
    check("execution_time_ms" in result.metadata, "Has execution_time_ms")
    check(result.metadata.get("used_llm") is False, "used_llm=False")

    # With mock LLM
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    mock_llm.last_call_count = 1
    mock_llm.last_tokens_used = 500

    agent2 = MockAgent(mock_sf, llm_client=mock_llm)
    result2 = await agent2.run({"test": "data"})
    check(result2.status == "completed", "Status = completed (with LLM)")
    check(result2.result.get("processed") is True, "Used _run_impl path")
    check(result2.metadata.get("used_llm") is True, "used_llm=True")

    print()


# ─── TEST 7: Orchestrator instantiation ───────────────────────
def test_orchestrator():
    print("=" * 60)
    print("TEST 7: Orchestrator instantiation")
    print("=" * 60)

    from agents.orchestrator import Orchestrator

    mock_sf = MagicMock()
    orch = Orchestrator(mock_sf)

    check(hasattr(orch, "run_daily_scan"), "has run_daily_scan()")
    check(hasattr(orch, "run_weekly_analysis"), "has run_weekly_analysis()")
    check(hasattr(orch, "run_deep_research"), "has run_deep_research()")
    check(hasattr(orch, "run_risk_check"), "has run_risk_check()")
    check(orch._scanner is not None, "Scanner agent initialized")
    check(orch._analyst is not None, "Analyst agent initialized")
    check(orch._stock_analysis is not None, "Stock analysis agent initialized")
    check(orch._screener is not None, "Screener agent initialized")
    check(orch._writer is not None, "Writer agent initialized")
    check(orch._risk is not None, "Risk monitor agent initialized")
    print()


# ─── TEST 8: AgentScheduler ───────────────────────────────────
def test_scheduler():
    print("=" * 60)
    print("TEST 8: AgentScheduler jobs")
    print("=" * 60)

    from agents.scheduler import AgentScheduler

    mock_sf = MagicMock()
    scheduler = AgentScheduler(mock_sf)

    check(hasattr(scheduler, "start"), "has start()")
    check(hasattr(scheduler, "stop"), "has stop()")
    check(hasattr(scheduler, "trigger_manual"), "has trigger_manual()")
    check(hasattr(scheduler, "get_jobs"), "has get_jobs()")

    # Check registered jobs (scheduler not started, so get_jobs from internal scheduler)
    jobs = scheduler._scheduler.get_jobs()
    job_ids = {j.id for j in jobs}
    check("daily_scan" in job_ids, "daily_scan job registered")
    check("weekly_analysis" in job_ids, "weekly_analysis job registered")
    check("chain_discovery" in job_ids, "chain_discovery job registered")
    check(len(jobs) == 3, f"Exactly 3 jobs registered (got {len(jobs)})")

    for j in jobs:
        print(f"    Job: {j.id} - {j.name}")

    print()


# ─── TEST 9: NotificationTools ────────────────────────────────
def test_notification():
    print("=" * 60)
    print("TEST 9: NotificationTools")
    print("=" * 60)

    from agents.tools.notification_tools import NotificationTools

    nt = NotificationTools()
    avail = nt.is_available()
    print(f"  Feishu webhook configured: {avail}")
    check(isinstance(avail, bool), "is_available() returns bool")
    check(hasattr(nt, "send_feishu"), "has send_feishu()")
    print()


# ─── TEST 10: AgentLog model compatibility ────────────────────
def test_agent_log_model():
    print("=" * 60)
    print("TEST 10: AgentLog ORM model")
    print("=" * 60)

    from common.models import AgentLog

    check(AgentLog.__tablename__ == "agent_logs", "Table name = agent_logs")
    cols = {c.name for c in AgentLog.__table__.columns}
    required = {"id", "agent_id", "task_id", "workflow_type", "input_data",
                "output_data", "tokens_used", "duration_ms", "status", "error_message", "created_at"}
    missing = required - cols
    check(len(missing) == 0, f"All required columns present (missing: {missing or 'none'})")
    print()


# ─── TEST 11: Integration with DB (optional) ──────────────────
async def test_integration():
    print("=" * 60)
    print("TEST 11: Integration test (requires DB)")
    print("=" * 60)

    try:
        from common.database import async_session_factory
        from agents.signal_scanner import SignalScannerAgent

        # Test 1: Instantiate with real session factory
        agent = SignalScannerAgent(async_session_factory, llm_client=None)
        ok("SignalScannerAgent with real session_factory")

        # Test 2: Quick DB connectivity check
        async with async_session_factory() as session:
            result = await session.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
            val = result.scalar()
            check(val == 1, "PostgreSQL connectivity OK")

    except Exception as e:
        print(f"  [SKIP] Integration test: {e}")

    print()


def main():
    print("\n" + "=" * 60)
    print(" Phase 4: Agent Framework - Verification")
    print("=" * 60 + "\n")

    test_imports()
    test_agent_result()
    test_llm_client()
    test_tool_result()
    test_worker_agents()
    asyncio.run(test_base_agent_run())
    test_orchestrator()
    test_scheduler()
    test_notification()
    test_agent_log_model()
    asyncio.run(test_integration())

    print("=" * 60)
    print(f" Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)

    if FAIL > 0:
        sys.exit(1)
    print(" Phase 4 verification complete!")


if __name__ == "__main__":
    main()
