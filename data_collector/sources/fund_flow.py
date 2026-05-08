import asyncio
from datetime import date, timedelta

import akshare as ak
import pandas as pd

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
        """采集北向资金数据

        使用 ak.stock_hsgt_hist_em("北向资金") 获取沪深港通历史数据。
        2024-08-19 起北向资金实时和盘后净买入披露口径调整，后续交易日
        可能只有日期和指数字段；缺失的净买入数据必须保留为 None，不能写 0。
        """
        try:
            df = await asyncio.to_thread(ak.stock_hsgt_hist_em, symbol="北向资金")
        except Exception as e:
            logger.error(f"AKShare采集北向资金失败: {e}")
            return 0

        if df is None or df.empty:
            logger.warning("北向资金数据为空")
            return 0

        if start_date is None:
            start_date = date.today() - timedelta(days=30)

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
                    [
                        "当日成交净买额",
                        "成交净买额",
                        "北向资金",
                        "当日净流入",
                        "净流入",
                    ],
                )
                if north_net_val is None:
                    north_net_val = self._first_matching_value(df, row, ["净", "流入"])

                north_net = float(north_net_val) if north_net_val is not None and pd.notna(north_net_val) else None

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

        # 更新缓存
        if cache_records:
            serializable = []
            for r in cache_records[-10:]:  # 最近10条
                serializable.append({
                    "trade_date": r["trade_date"].isoformat(),
                    "north_net": r["north_net"],
                    "source": r["source"],
                })
            await self.cache.set_fund_flow_cache(serializable)

        logger.info(f"采集北向资金完成: {count} 条新记录")
        return count

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
