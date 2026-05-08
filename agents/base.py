"""Agent 基础设施: 抽象基类、结果模型、日志持久化"""

import abc
import time
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.logger import get_logger
from common.models import AgentLog


class AgentResult(BaseModel):
    """Agent 执行结果"""

    agent_id: str
    task_id: str
    status: str = "completed"  # completed | failed | degraded
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class BaseAgent(abc.ABC):
    """Worker Agent 抽象基类

    子类必须定义 agent_id 并实现 _run_impl()。
    缺 LLM 时自动调用 _run_fallback() 降级。
    """

    agent_id: str

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        llm_client: Any = None,
    ):
        self._session_factory = session_factory
        self._llm = llm_client
        self._logger = get_logger(f"agent.{self.agent_id}")

    async def run(self, params: dict[str, Any], task_id: str | None = None) -> AgentResult:
        """模板方法: 执行 → 记录日志 → 返回结果"""
        task_id = task_id or f"{self.agent_id}_{uuid.uuid4().hex[:8]}"
        start = time.time()

        try:
            if self._llm and self._llm.is_available():
                result_data = await self._run_impl(params)
                used_llm = True
            else:
                self._logger.info(f"LLM unavailable, using fallback")
                result_data = await self._run_fallback(params)
                used_llm = False

            elapsed = int((time.time() - start) * 1000)
            agent_result = AgentResult(
                agent_id=self.agent_id,
                task_id=task_id,
                status="completed" if used_llm else "degraded",
                result=result_data,
                metadata={
                    "execution_time_ms": elapsed,
                    "llm_calls": getattr(self._llm, "last_call_count", 0) if used_llm else 0,
                    "tokens_used": getattr(self._llm, "last_tokens_used", 0) if used_llm else 0,
                    "used_llm": used_llm,
                },
            )
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            self._logger.error(f"Agent failed: {e}")
            agent_result = AgentResult(
                agent_id=self.agent_id,
                task_id=task_id,
                status="failed",
                error_message=str(e),
                metadata={"execution_time_ms": elapsed},
            )

        await self._save_log(agent_result, params)
        return agent_result

    @abc.abstractmethod
    async def _run_impl(self, params: dict[str, Any]) -> dict[str, Any]:
        """主逻辑（子类实现）"""
        ...

    async def _run_fallback(self, params: dict[str, Any]) -> dict[str, Any]:
        """Rule-based 降级（默认同 _run_impl）"""
        return await self._run_impl(params)

    async def _save_log(self, result: AgentResult, input_params: dict) -> None:
        try:
            async with self._session_factory() as session:
                log = AgentLog(
                    agent_id=result.agent_id,
                    task_id=result.task_id,
                    workflow_type=input_params.get("workflow_type", ""),
                    input_data=input_params,
                    output_data=result.result if result.status != "failed" else {"error": result.error_message},
                    tokens_used=result.metadata.get("tokens_used", 0),
                    duration_ms=result.metadata.get("execution_time_ms", 0),
                    status=result.status,
                    error_message=result.error_message or None,
                )
                session.add(log)
                await session.commit()
        except Exception as e:
            self._logger.error(f"Failed to save agent log: {e}")
