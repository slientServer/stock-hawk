"""知识图谱工具：Agent 调用的图谱查询工具。"""

from agents.tools.base_tool import BaseTool, ToolResult


class GraphTools(BaseTool):
    tool_name = "graph_tools"

    async def query(self, *_args, **_kwargs) -> ToolResult:
        return ToolResult(success=False, data=None, error="GraphTools is not implemented")
