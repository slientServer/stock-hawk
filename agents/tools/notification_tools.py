"""通知工具：飞书/微信等消息推送。"""

import httpx

from common.config import get_settings
from agents.tools.base_tool import BaseTool, ToolResult


class NotificationTools(BaseTool):
    tool_name = "notification_tools"

    def is_available(self) -> bool:
        return bool(get_settings().feishu.webhook_url)

    async def send_feishu(self, content: str) -> ToolResult:
        webhook = get_settings().feishu.webhook_url
        if not webhook:
            return ToolResult(success=False, data=None, error="FEISHU_WEBHOOK_URL is not configured")
        payload = {"msg_type": "text", "content": {"text": content}}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook, json=payload)
                response.raise_for_status()
            return ToolResult(success=True, data={"status_code": response.status_code})
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))

    async def send(self, content: str, channel: str = "feishu", **_kwargs) -> ToolResult:
        if channel == "feishu":
            return await self.send_feishu(content)
        return ToolResult(success=False, data=None, error=f"Unsupported channel: {channel}")
