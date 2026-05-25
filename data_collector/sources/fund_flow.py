import asyncio
from datetime import date, timedelta

import akshare as ak
import pandas as pd

from common.config import get_settings
from common.logger import get_logger
from data_collector.storage import DataStorage
from data_collector.cache.redis_cache import RedisCache

logger = get_logger(__name__)


class FundFlowCollector:
    """资金流向采集器（北向资金）"""

    def __init__(self, storage: DataStorage, cache: RedisCache):
        self.storage = storage
        self.cache = cache

    async def collect_north_flow(self, start_date: date = None) -> int:
        """采集北向资金数据，Tushare 优先（buy/sell/net 完整），AKShare 降级。

        2024-08-19 起 AKShare 北向资金口径调整，净买入字段经常缺失；
        Tushare moneyflow_hsgt 提供结构化买卖双向数据，120 积分即可访问。
        """
        if start_date is None:
            start_date = date.today() - timedelta(days=30)

        count = await self._collect_north_flow_tushare(start_date)
        if count > 0:
            logger.info(f"北向资金采集完成（Tushare）: {count} 条")
            return count

        logger.info("Tushare 北向资金无数据，降级到 AKShare")
        return await self._collect_north_flow_akshare(start_date)

    async def _collect_north_flow_tushare(self, start_date: date) -> int:
        """使用 Tushare moneyflow_hsgt 采集北向资金（买入/卖出/净额均可得）。"""
        token = get_settings().data_source.tushare_token
        if not token:
            return 0
        try:
            import tushare as ts
        except ImportError:
            logger.warning("tushare 未安装，跳过北向资金 Tushare 采集")
            return 0

        end_date = date.today()

        def _fetch():
            ts.set_token(token)
            pro = ts.pro_api(token)
            return pro.moneyflow_hsgt(
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
            )

        try:
            df = await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning(f"Tushare 采集北向资金失败: {e}")
            return 0

        if df is None or df.empty:
            return 0

        # 只保留北向资金汇总行（name 含"北向"），没有 name 列时全量使用
        if "name" in df.columns:
            mask = df["name"].astype(str).str.contains("北向", na=False)
            north_df = df[mask] if mask.any() else df
        else:
            north_df = df

        count = 0
        cache_records: list[dict] = []
        for _, row in north_df.iterrows():
            try:
                raw_date = row.get("trade_date")
                if raw_date is None:
                    continue
                if isinstance(raw_date, str):
                    trade_date_val = pd.Timestamp(raw_date.strip()).date()
                else:
                    trade_date_val = pd.Timestamp(raw_date).date()

                if trade_date_val < start_date:
                    continue

                buy = self._to_float(row.get("buy_amount"))
                sell = self._to_float(row.get("sell_amount"))
                net = (buy - sell) if buy is not None and sell is not None else None

                record = {
                    "trade_date": trade_date_val,
                    "north_buy": buy,
                    "north_sell": sell,
                    "north_net": net,
                    "source": "tushare",
                }
                date_str = trade_date_val.isoformat()
                await self.storage.insert_fund_flow(record)
                await self.cache.set_incremental_marker("north_flow", date_str)
                count += 1
                cache_records.append({"trade_date": date_str, "north_net": net, "source": "tushare"})
            except Exception as e:
                logger.warning(f"解析 Tushare 北向资金行失败: {e}")

        if cache_records:
            await self.cache.set_fund_flow_cache(cache_records[-10:])

        return count

    async def _collect_north_flow_akshare(self, start_date: date) -> int:
        """AKShare 降级采集北向资金（2024-08-19 后净买入字段可能缺失）。"""
        try:
            df = await asyncio.to_thread(ak.stock_hsgt_hist_em, symbol="北向资金")
        except Exception as e:
            logger.error(f"AKShare 采集北向资金失败: {e}")
            return 0

        if df is None or df.empty:
            logger.warning("AKShare 北向资金数据为空")
            return 0

        count = 0
        cache_records = []

        for _, row in df.iterrows():
            try:
                trade_date_val = row.get("日期") or row.get("date")
                if trade_date_val is None:
                    continue

                if isinstance(trade_date_val, str):
                    trade_date_val = pd.Timestamp(trade_date_val).date()
                elif isinstance(trade_date_val, pd.Timestamp):
                    trade_date_val = trade_date_val.date()

                if trade_date_val < start_date:
                    continue

                date_str = trade_date_val.isoformat()

                north_net_val = self._first_present(
                    row,
                    ["当日成交净买额", "成交净买额", "北向资金", "当日净流入", "净流入"],
                )
                if north_net_val is None:
                    north_net_val = self._first_matching_value(df, row, ["净", "流入"])

                north_net = self._to_float(north_net_val)

                record = {
                    "trade_date": trade_date_val,
                    "north_buy": None,
                    "north_sell": None,
                    "north_net": north_net,
                    "source": "akshare",
                }

                try:
                    await self.storage.insert_fund_flow(record)
                    await self.cache.set_incremental_marker("north_flow", date_str)
                    count += 1
                    cache_records.append(record)
                except Exception as e:
                    logger.warning(f"写入北向资金记录失败: date={date_str}, error={e}")

            except Exception as e:
                logger.warning(f"解析北向资金行失败: {e}")
                continue

        if cache_records:
            serializable = [
                {"trade_date": r["trade_date"].isoformat(), "north_net": r["north_net"], "source": r["source"]}
                for r in cache_records[-10:]
            ]
            await self.cache.set_fund_flow_cache(serializable)

        logger.info(f"AKShare 北向资金采集完成: {count} 条新记录")
        return count

    @staticmethod
    def _to_float(value) -> float | None:
        if value is None:
            return None
        try:
            v = float(value)
            return None if pd.isna(v) else v
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first_present(row, columns: list[str]):
        for col in columns:
            if col in row and pd.notna(row[col]):
                return row[col]
        return None

    @staticmethod
    def _first_matching_value(df: pd.DataFrame, row, keywords: list[str]):
        for col in df.columns:
            text = str(col)
            if all(keyword in text for keyword in keywords) and pd.notna(row[col]):
                return row[col]
        return None

    async def collect_top_list(self, trade_date: date = None) -> int:
        """采集龙虎榜数据

        使用 ak.stock_lhb_detail_em() 获取龙虎榜明细数据
        写入 StockFundFlow 表
        """
        if trade_date is None:
            trade_date = date.today()

        date_str = trade_date.strftime("%Y%m%d")

        # 检查缓存是否已采集
        already = await self.cache.is_collected("top_list", date_str)
        if already:
            logger.info(f"龙虎榜 {date_str} 已采集，跳过")
            return 0

        try:
            df = await asyncio.to_thread(
                ak.stock_lhb_detail_em, start_date=date_str, end_date=date_str
            )
        except Exception as e:
            logger.error(f"AKShare采集龙虎榜失败: {e}")
            return 0

        if df is None or df.empty:
            logger.warning(f"龙虎榜数据为空: {date_str}")
            return 0

        records = []
        for _, row in df.iterrows():
            try:
                code = str(row.get("代码") or row.get("code") or "").strip()
                if not code:
                    continue

                reason = str(row.get("上榜原因") or row.get("解读") or "")
                buy_amount = row.get("买入额") or row.get("龙虎榜买入额")
                sell_amount = row.get("卖出额") or row.get("龙虎榜卖出额")
                net_amount = row.get("净额") or row.get("龙虎榜净买额")

                buy_val = float(buy_amount) if buy_amount is not None and pd.notna(buy_amount) else None
                sell_val = float(sell_amount) if sell_amount is not None and pd.notna(sell_amount) else None
                net_val = float(net_amount) if net_amount is not None and pd.notna(net_amount) else None

                # 如果net_amount为空但有买卖额，计算净额
                if net_val is None and buy_val is not None and sell_val is not None:
                    net_val = buy_val - sell_val

                records.append({
                    "code": code,
                    "trade_date": trade_date,
                    "reason": reason[:200] if reason else None,
                    "buy_amount": buy_val,
                    "sell_amount": sell_val,
                    "net_amount": net_val,
                    "source": "akshare",
                })
            except Exception as e:
                logger.warning(f"解析龙虎榜行失败: {e}")
                continue

        if records:
            try:
                await self.storage.insert_stock_fund_flows(records)
                await self.cache.set_incremental_marker("top_list", date_str)
            except Exception as e:
                logger.error(f"写入龙虎榜数据失败: {e}")
                return 0

        logger.info(f"采集龙虎榜完成: {len(records)} 条记录 ({date_str})")
        return len(records)
