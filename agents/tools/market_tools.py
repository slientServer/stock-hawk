"""行情工具：Agent 调用的市场数据查询工具。"""

from agents.tools.base_tool import BaseTool, ToolResult


class MarketTools(BaseTool):
    tool_name = "market_tools"

    async def query(self, *_args, **_kwargs) -> ToolResult:
        return ToolResult(success=False, data=None, error="MarketTools is not implemented")
