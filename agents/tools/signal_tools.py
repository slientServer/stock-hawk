"""信号工具：Agent 调用的信号检索工具。"""

from agents.tools.base_tool import BaseTool, ToolResult


class SignalTools(BaseTool):
    tool_name = "signal_tools"

    async def query(self, *_args, **_kwargs) -> ToolResult:
        return ToolResult(success=False, data=[], error="SignalTools is not implemented")
