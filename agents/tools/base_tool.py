"""Tool 基类"""

from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    """工具执行结果"""

    success: bool = True
    data: Any = None
    error: str = ""

    model_config = {"arbitrary_types_allowed": True}


class BaseTool:
    """工具基类，提供安全执行包装"""

    tool_name: str = "base_tool"

    async def _safe_execute(self, coro) -> ToolResult:
        try:
            data = await coro
            return ToolResult(success=True, data=data)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
