"""Agent Framework: 轻量级 Supervisor+Worker 多Agent协作框架"""

from agents.base import AgentResult, BaseAgent
from agents.automation import AutomationRunner
from agents.chain_analyst import ChainAnalystAgent
from agents.chain_discovery import ChainDiscoveryAgent
from agents.llm_client import LLMClient
from agents.orchestrator import Orchestrator
from agents.report_writer import ReportWriterAgent
from agents.risk_monitor import RiskMonitorAgent
from agents.scheduler import AgentScheduler
from agents.signal_scanner import SignalScannerAgent
from agents.stock_analysis import StockAnalysisAgent
from agents.stock_screener import StockScreenerAgent

__all__ = [
    "AgentResult",
    "AutomationRunner",
    "BaseAgent",
    "ChainAnalystAgent",
    "ChainDiscoveryAgent",
    "LLMClient",
    "Orchestrator",
    "ReportWriterAgent",
    "RiskMonitorAgent",
    "AgentScheduler",
    "SignalScannerAgent",
    "StockAnalysisAgent",
    "StockScreenerAgent",
]
