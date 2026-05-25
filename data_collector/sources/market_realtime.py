import httpx

from common.logger import get_logger
from data_collector.parsers.sina_parser import SinaParser
from data_collector.parsers.tencent_parser import TencentParser
from data_collector.cache.redis_cache import RedisCache

logger = get_logger(__name__)


class RealtimeCollector:
    """A股实时行情采集器 - 新浪/腾讯双源互备"""

    SINA_URL = "https://hq.sinajs.cn/list="
    TENCENT_URL = "https://qt.gtimg.cn/q="

    def __init__(self, cache: RedisCache):
        self.cache = cache
        self.primary_source = "sina"
        self._client = httpx.AsyncClient(
            timeout=5.0,
            headers={
                "Referer": "https://finance.sina.com.cn",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        )

    async def fetch_realtime(self, codes: list[str]) -> list[dict]:
        """获取实时行情，主源失败自动切换备源"""
        try:
            if self.primary_source == "sina":
                return await self._fetch_from_sina(codes)
            else:
                return await self._fetch_from_tencent(codes)
        except Exception as e:
            logger.warning(f"主源{self.primary_source}失败: {e}, 切换备源")
            try:
                if self.primary_source == "sina":
                    return await self._fetch_from_tencent(codes)
                else:
                    return await self._fetch_from_sina(codes)
            except Exception as e2:
                logger.error(f"双源均失败: {e2}")
                return []

    async def _fetch_from_sina(self, codes: list[str]) -> list[dict]:
        """从新浪获取实时行情"""
        param = SinaParser.build_codes_param(codes)
        resp = await self._client.get(f"{self.SINA_URL}{param}")
        resp.raise_for_status()
        return SinaParser.parse_realtime_response(resp.text)

    async def _fetch_from_tencent(self, codes: list[str]) -> list[dict]:
        """从腾讯获取实时行情"""
        param = TencentParser.build_codes_param(codes)
        resp = await self._client.get(f"{self.TENCENT_URL}{param}")
        resp.raise_for_status()
        return TencentParser.parse_realtime_response(resp.text)

    async def collect_and_cache(self, codes: list[str]) -> list[dict]:
        """采集并写入Redis缓存（全量刷新，适合定时推送）。"""
        quotes = await self.fetch_realtime(codes)
        if quotes:
            quote_dict = {q["code"]: q for q in quotes}
            await self.cache.batch_set_realtime_quotes(quote_dict)
            logger.info(f"缓存了 {len(quotes)} 只股票实时行情")
        return quotes

    async def get_quotes_with_cache(self, codes: list[str]) -> list[dict]:
        """Read-through 缓存：优先从 Redis 返回，仅对未命中的股票触发外部请求。

        适合 Agent / API 在交易时段按需查询，避免每次全量抓取。
        """
        cached: dict[str, dict] = {}
        missing: list[str] = []
        for code in codes:
            hit = await self.cache.get_realtime_quote(code)
            if hit:
                cached[code] = hit
            else:
                missing.append(code)

        if missing:
            fetched = await self.fetch_realtime(missing)
            if fetched:
                fetch_dict = {q["code"]: q for q in fetched}
                await self.cache.batch_set_realtime_quotes(fetch_dict)
                cached.update(fetch_dict)
                logger.debug(f"补充抓取并缓存了 {len(fetched)} 只股票实时行情")

        # 保持与输入 codes 相同的顺序
        return [cached[code] for code in codes if code in cached]

    async def close(self):
        await self._client.aclose()
