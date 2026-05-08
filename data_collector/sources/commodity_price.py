"""商品价格采集器 - 期货/现货价格（akshare自动采集 + 手动录入兜底）"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

from common.logger import get_logger
from data_collector.cache.redis_cache import RedisCache
from data_collector.storage import DataStorage

logger = get_logger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "data" / "commodity_chain_mapping.json"


class CommodityPriceCollector:
    """商品价格采集器：期货现货价格 + 手动录入兜底"""

    def __init__(self, storage: DataStorage, cache: RedisCache | None = None):
        self.storage = storage
        self.cache = cache
        self._config = self._load_config()

    def _load_config(self) -> list[dict]:
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("products", [])
        except Exception as e:
            logger.warning(f"加载商品配置失败: {e}")
            return []

    def get_auto_products(self) -> list[dict]:
        """返回可自动采集的商品列表（有期货代码的）"""
        return [p for p in self._config if p.get("source_type") == "futures" and p.get("symbol")]

    def get_manual_products(self) -> list[dict]:
        """返回需要手动录入的商品列表"""
        return [p for p in self._config if p.get("source_type") == "manual"]

    async def collect_incremental(self) -> int:
        """增量采集：只采集今日尚未采集的品种"""
        today_str = date.today().isoformat()
        total = 0
        for product in self.get_auto_products():
            name = product["name"]
            marker_key = f"commodity:{name}:{today_str}"
            if self.cache and await self.cache.is_collected(marker_key, today_str):
                continue
            count = await self._collect_single_futures(product)
            total += count
            if count > 0 and self.cache:
                await self.cache.set_incremental_marker(marker_key, today_str)
            await asyncio.sleep(0.5)
        return total

    async def collect_batch(self, days: int = 30) -> int:
        """批量采集所有可自动采集的商品近N天数据"""
        total = 0
        for product in self.get_auto_products():
            try:
                count = await self._collect_single_futures(product, days=days)
                total += count
            except Exception as e:
                logger.error(f"采集商品 {product['name']} 失败: {e}")
            await asyncio.sleep(0.5)
        logger.info(f"商品价格批量采集完成，共 {total} 条")
        return total

    async def _collect_single_futures(self, product: dict, days: int = 10) -> int:
        """采集单个期货品种价格"""
        symbol = product.get("symbol")
        name = product["name"]
        chain_ids = product.get("chain_ids", [])
        chain_id = chain_ids[0] if chain_ids else None

        try:
            df = await asyncio.to_thread(
                ak.futures_zh_daily_sina, symbol=symbol
            )
        except Exception as e:
            logger.warning(f"akshare 采集 {name}({symbol}) 失败: {e}")
            return 0

        if df is None or df.empty:
            logger.warning(f"商品 {name} 无数据返回")
            return 0

        # 只取最近N天
        cutoff = date.today() - timedelta(days=days)
        records = []
        for _, row in df.iterrows():
            try:
                trade_date = pd.to_datetime(row.get("date") or row.get("日期")).date()
            except Exception:
                continue
            if trade_date < cutoff:
                continue

            close = self._safe_float(row.get("close") or row.get("收盘价"))
            prev_close = self._safe_float(row.get("open") or row.get("开盘价"))  # 近似
            change_pct = None
            if close and prev_close and prev_close > 0:
                change_pct = round((close - prev_close) / prev_close * 100, 4)

            records.append({
                "product_name": name,
                "price_date": trade_date,
                "price": close,
                "price_change_pct": change_pct,
                "chain_id": chain_id,
                "is_manual": False,
                "source": "akshare_futures",
            })

        if records:
            await self.storage.upsert_commodity_prices(records)
        return len(records)

    @staticmethod
    def _safe_float(value) -> float | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
