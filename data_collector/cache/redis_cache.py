import json

import redis.asyncio as aioredis

from common.config import get_settings


class RedisCache:
    def __init__(self):
        settings = get_settings()
        self._url = settings.redis.url
        self._redis: aioredis.Redis | None = None

    async def connect(self):
        self._redis = aioredis.from_url(self._url, decode_responses=True)

    async def close(self):
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("RedisCache not connected. Call connect() first.")
        return self._redis

    async def set_realtime_quote(self, code: str, data: dict):
        key = f"stock:{code}"
        await self.redis.set(key, json.dumps(data, ensure_ascii=False), ex=3)

    async def get_realtime_quote(self, code: str) -> dict | None:
        key = f"stock:{code}"
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def batch_set_realtime_quotes(self, quotes: dict[str, dict]):
        async with self.redis.pipeline(transaction=False) as pipe:
            for code, data in quotes.items():
                key = f"stock:{code}"
                pipe.set(key, json.dumps(data, ensure_ascii=False), ex=3)
            await pipe.execute()

    # 增量标记保留 90 天（7776000 秒），防止历史标记无限堆积
    _INCR_MARKER_TTL = 7776000

    async def set_incremental_marker(self, source: str, date: str):
        key = f"incr_marker:{source}:{date}"
        await self.redis.set(key, "1", ex=self._INCR_MARKER_TTL)

    async def is_collected(self, source: str, date: str) -> bool:
        key = f"incr_marker:{source}:{date}"
        return await self.redis.exists(key) > 0

    async def acquire_task_lock(self, task_name: str, ttl: int = 60) -> bool:
        key = f"task_lock:{task_name}"
        return await self.redis.set(key, "1", nx=True, ex=ttl)

    async def release_task_lock(self, task_name: str):
        key = f"task_lock:{task_name}"
        await self.redis.delete(key)

    async def set_fund_flow_cache(self, data: list[dict]):
        key = "fund_flow:north_recent"
        await self.redis.set(key, json.dumps(data, ensure_ascii=False), ex=300)

    async def get_fund_flow_cache(self) -> list[dict]:
        key = "fund_flow:north_recent"
        raw = await self.redis.get(key)
        if raw is None:
            return []
        return json.loads(raw)
