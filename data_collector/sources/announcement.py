import httpx
from datetime import date

from common.logger import get_logger

logger = get_logger(__name__)


class AnnouncementCollector:
    """公告采集器

    ⚠️ 当前状态: 等待用户确认巨潮资讯接口方式
    数据源: 巨潮资讯 cninfo.com.cn
    """

    CNINFO_BASE_URL = "http://www.cninfo.com.cn/new/disclosure"

    def __init__(self, storage):
        self.storage = storage
        self._client = httpx.AsyncClient(timeout=10.0)
        self._enabled = False  # 等待用户配置

    async def collect_announcements(self, code: str = None, start_date: date = None) -> int:
        """采集公告

        当前未启用，需要用户确认巨潮资讯接口方式后方可使用。
        """
        if not self._enabled:
            logger.warning("公告采集器未启用: 需要用户确认巨潮资讯接口方式")
            return 0
        # TODO: 实现具体采集逻辑
        return 0

    async def close(self):
        await self._client.aclose()
