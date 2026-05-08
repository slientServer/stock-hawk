"""海外映射数据采集：美股对标行情 + A股↔海外映射关系"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

from common.logger import get_logger
from data_collector.cache.redis_cache import RedisCache
from data_collector.storage import DataStorage

logger = get_logger(__name__)

_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "overseas_mapping_seed.json"


class OverseasMappingCollector:
    """海外映射采集器：美股行情 + A股↔海外对标关系"""

    def __init__(self, storage: DataStorage, cache: RedisCache | None = None):
        self.storage = storage
        self.cache = cache
        self._seed_mappings = self._load_seed()

    def _load_seed(self) -> list[dict]:
        try:
            with open(_SEED_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("mappings", [])
        except Exception as e:
            logger.warning(f"加载海外映射种子数据失败: {e}")
            return []

    def get_overseas_symbols(self) -> list[str]:
        """返回所有需要采集的海外股票代码（去重）"""
        symbols = list(dict.fromkeys(m["overseas_symbol"] for m in self._seed_mappings))
        return symbols

    async def sync_mappings(self) -> int:
        """将种子映射数据同步到数据库"""
        if not self._seed_mappings:
            logger.warning("海外映射种子数据为空，跳过同步")
            return 0

        records = []
        for m in self._seed_mappings:
            records.append({
                "a_code": m["a_code"],
                "overseas_symbol": m["overseas_symbol"],
                "a_name": m.get("a_name"),
                "overseas_name": m.get("overseas_name"),
                "relation_type": m.get("relation_type"),
                "chain_id": m.get("chain_id"),
                "confidence": m.get("confidence", 0.8),
            })

        await self.storage.upsert_overseas_mappings(records)
        logger.info(f"海外映射同步完成: {len(records)} 对")
        return len(records)

    async def collect_incremental(self) -> int:
        """增量采集：只采集今日尚未采集的海外股票"""
        today_str = date.today().isoformat()
        total = 0

        # 先同步映射关系
        await self.sync_mappings()

        for symbol in self.get_overseas_symbols():
            marker_key = f"overseas:{symbol}:{today_str}"
            if self.cache and await self.cache.is_collected(marker_key, today_str):
                continue
            count = await self._collect_single_symbol(symbol, days=5)
            total += count
            if count > 0 and self.cache:
                await self.cache.set_incremental_marker(marker_key, today_str)
            await asyncio.sleep(1.0)

        return total

    async def collect_batch(self, days: int = 60) -> int:
        """批量采集所有海外股票近N天行情"""
        # 先同步映射关系
        await self.sync_mappings()

        total = 0
        for symbol in self.get_overseas_symbols():
            try:
                count = await self._collect_single_symbol(symbol, days=days)
                total += count
            except Exception as e:
                logger.error(f"采集海外股票 {symbol} 失败: {e}")
            await asyncio.sleep(1.0)

        logger.info(f"海外股票批量采集完成，共 {total} 条")
        return total

    async def _collect_single_symbol(self, symbol: str, days: int = 10) -> int:
        """采集单只美股行情数据"""
        # 从映射中获取名称
        name = None
        for m in self._seed_mappings:
            if m["overseas_symbol"] == symbol:
                name = m.get("overseas_name")
                break

        # 尝试 akshare 美股日线
        try:
            df = await asyncio.to_thread(
                ak.stock_us_daily, symbol=symbol, adjust="qfq"
            )
        except Exception as e:
            logger.warning(f"akshare 采集美股 {symbol} 失败: {e}，尝试备选接口")
            df = await self._fallback_collect(symbol)

        if df is None or df.empty:
            logger.warning(f"海外股票 {symbol} 无数据返回")
            return 0

        cutoff = date.today() - timedelta(days=days)
        records = []
        for _, row in df.iterrows():
            trade_date = self._parse_date(row)
            if trade_date is None or trade_date < cutoff:
                continue

            close_val = self._safe_float(row.get("close") or row.get("收盘"))
            open_val = self._safe_float(row.get("open") or row.get("开盘"))
            high_val = self._safe_float(row.get("high") or row.get("最高"))
            low_val = self._safe_float(row.get("low") or row.get("最低"))
            volume = self._safe_int(row.get("volume") or row.get("成交量"))

            # 计算涨跌幅
            change_pct = None
            prev_close = self._safe_float(row.get("pre_close"))
            if close_val and prev_close and prev_close > 0:
                change_pct = round((close_val - prev_close) / prev_close * 100, 4)

            records.append({
                "symbol": symbol,
                "name": name,
                "trade_date": trade_date,
                "open": open_val,
                "close": close_val,
                "high": high_val,
                "low": low_val,
                "volume": volume,
                "change_pct": change_pct,
                "source": "akshare_us",
            })

        if records:
            await self.storage.upsert_overseas_stocks(records)
        return len(records)

    async def _fallback_collect(self, symbol: str) -> pd.DataFrame | None:
        """备选采集方式：使用 akshare 美股历史数据接口"""
        try:
            df = await asyncio.to_thread(
                ak.stock_us_hist, symbol=symbol, period="daily", adjust="qfq"
            )
            return df
        except Exception as e:
            logger.warning(f"备选接口 stock_us_hist {symbol} 也失败: {e}")
            return None

    @staticmethod
    def _parse_date(row) -> date | None:
        """从行数据中解析日期"""
        for key in ("date", "日期", "trade_date"):
            val = row.get(key)
            if val is not None:
                try:
                    return pd.to_datetime(val).date()
                except Exception:
                    continue
        return None

    @staticmethod
    def _safe_float(value) -> float | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_int(value) -> int | None:
        if value is None:
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
