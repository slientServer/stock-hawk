"""个股主力资金流采集器

数据来源：AKShare stock_individual_fund_flow_type_rank (个股资金流排名)
采集每日主力（超大单+大单）净流入、散户（中单+小单）净流入等字段。
"""

import asyncio
from datetime import date, timedelta

import akshare as ak
import pandas as pd

from common.config import get_settings
from common.logger import get_logger
from data_collector.cache.redis_cache import RedisCache
from data_collector.storage import DataStorage

logger = get_logger(__name__)


class MainFlowCollector:
    """个股主力资金流采集器"""

    def __init__(self, storage: DataStorage, cache: RedisCache):
        self.storage = storage
        self.cache = cache

    async def collect_tushare_moneyflow(self, trade_date: date) -> int:
        """使用 Tushare moneyflow 按交易日补全全市场个股资金流。

        Tushare 金额字段单位为万元；本系统 stock_main_flows 使用元。
        主力口径 = 大单 + 超大单，散户口径 = 小单 + 中单。
        """
        token = get_settings().data_source.tushare_token
        if not token:
            logger.warning("Tushare token 未配置，跳过全市场主力资金补采")
            return 0
        try:
            import tushare as ts
        except ImportError:
            logger.warning("tushare 未安装，跳过全市场主力资金补采")
            return 0

        trade_date_str = trade_date.strftime("%Y%m%d")

        def _fetch():
            ts.set_token(token)
            pro = ts.pro_api(token)
            return pro.moneyflow(trade_date=trade_date_str)

        try:
            df = await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning(f"Tushare 全市场主力资金补采失败: trade_date={trade_date_str}, error={e}")
            return 0

        if df is None or df.empty:
            logger.warning(f"Tushare 全市场主力资金为空: trade_date={trade_date_str}")
            return 0

        records: list[dict] = []
        for _, row in df.iterrows():
            code = self._ts_code_to_code(row.get("ts_code"))
            if not code:
                continue

            buy_lg = self._to_yuan(row.get("buy_lg_amount"))
            buy_elg = self._to_yuan(row.get("buy_elg_amount"))
            sell_lg = self._to_yuan(row.get("sell_lg_amount"))
            sell_elg = self._to_yuan(row.get("sell_elg_amount"))
            buy_sm = self._to_yuan(row.get("buy_sm_amount"))
            buy_md = self._to_yuan(row.get("buy_md_amount"))
            sell_sm = self._to_yuan(row.get("sell_sm_amount"))
            sell_md = self._to_yuan(row.get("sell_md_amount"))

            main_buy = self._sum_present(buy_lg, buy_elg)
            main_sell = self._sum_present(sell_lg, sell_elg)
            retail_buy = self._sum_present(buy_sm, buy_md)
            retail_sell = self._sum_present(sell_sm, sell_md)
            main_net = (
                main_buy - main_sell
                if main_buy is not None and main_sell is not None
                else self._to_yuan(row.get("net_mf_amount"))
            )
            retail_net = (
                retail_buy - retail_sell
                if retail_buy is not None and retail_sell is not None
                else None
            )

            if main_net is None and main_buy is None:
                continue

            records.append(
                {
                    "code": code,
                    "trade_date": trade_date,
                    "main_net": main_net,
                    "main_buy": main_buy,
                    "main_sell": main_sell,
                    "retail_net": retail_net,
                    "main_net_pct": None,
                    "source": "tushare_moneyflow",
                }
            )

        await self.storage.upsert_stock_main_flows(records)
        logger.info(f"Tushare 全市场主力资金补采完成: trade_date={trade_date_str}, records={len(records)}")
        return len(records)

    async def collect_single(self, code: str, days: int = 5) -> int:
        """采集单只股票的主力资金流

        使用 ak.stock_individual_fund_flow(stock=code, market=market) 获取历史资金流。
        """
        market = self._infer_market(code)
        try:
            df = await asyncio.to_thread(
                ak.stock_individual_fund_flow, stock=code, market=market
            )
        except Exception as e:
            logger.warning(f"采集主力资金流失败: code={code}, error={e}")
            return 0

        if df is None or df.empty:
            return 0

        cutoff = date.today() - timedelta(days=days + 2)
        records = []

        for _, row in df.iterrows():
            try:
                trade_date_val = row.get("日期") or row.get("date")
                if trade_date_val is None:
                    continue

                if isinstance(trade_date_val, str):
                    trade_date_val = pd.to_datetime(trade_date_val).date()
                elif hasattr(trade_date_val, "date"):
                    trade_date_val = trade_date_val.date()

                if trade_date_val < cutoff:
                    continue

                # 解析主力资金字段（超大单+大单 = 主力）
                main_buy = self._parse_amount(row, ["主力流入净额", "主力净流入-净额", "超大单净流入-净额"])
                main_net = self._parse_amount(row, ["主力净流入-净额", "主力流入净额"])
                main_buy_val = self._parse_amount(row, ["主力流入", "超大单流入-流入", "主力买入"])
                main_sell_val = self._parse_amount(row, ["主力流出", "超大单流出-流出", "主力卖出"])

                # 如果没有直接的主力净流入，尝试用超大单+大单计算
                if main_net is None:
                    super_large_net = self._parse_amount(row, ["超大单净流入-净额", "超大单净额"])
                    large_net = self._parse_amount(row, ["大单净流入-净额", "大单净额"])
                    if super_large_net is not None and large_net is not None:
                        main_net = super_large_net + large_net

                # 散户 = 中单 + 小单
                mid_net = self._parse_amount(row, ["中单净流入-净额", "中单净额"])
                small_net = self._parse_amount(row, ["小单净流入-净额", "小单净额"])
                retail_net = None
                if mid_net is not None and small_net is not None:
                    retail_net = mid_net + small_net

                # 主力净流入占比
                main_net_pct = self._parse_float(row, ["主力净流入-净占比", "主力净占比"])

                if main_net is None and main_buy_val is None:
                    continue

                records.append({
                    "code": code,
                    "trade_date": trade_date_val,
                    "main_net": main_net,
                    "main_buy": main_buy_val,
                    "main_sell": main_sell_val,
                    "retail_net": retail_net,
                    "main_net_pct": main_net_pct,
                    "source": "akshare",
                })
            except Exception as e:
                logger.debug(f"解析主力资金行异常: code={code}, error={e}")
                continue

        if records:
            await self.storage.upsert_stock_main_flows(records)

        return len(records)

    async def collect_batch(self, codes: list[str], days: int = 5) -> int:
        """批量采集多只股票的主力资金流"""
        total = 0
        for i, code in enumerate(codes):
            try:
                count = await self.collect_single(code, days=days)
                total += count
                if count > 0:
                    logger.debug(f"主力资金流: {code} 采集 {count} 条")
            except Exception as e:
                logger.error(f"主力资金流批量采集异常: code={code}, error={e}")
            if i < len(codes) - 1:
                await asyncio.sleep(0.3)
        logger.info(f"主力资金流批量采集完成: {len(codes)} 只股票, 共 {total} 条记录")
        return total

    async def collect_incremental(self, codes: list[str]) -> int:
        """增量采集（当日未采集的才采）"""
        today_str = date.today().isoformat()
        to_collect = []
        for code in codes:
            already = await self.cache.is_collected(f"main_flow:{code}", today_str)
            if not already:
                to_collect.append(code)

        if not to_collect:
            logger.info("主力资金流: 今日已全部采集过")
            return 0

        total = 0
        for i, code in enumerate(to_collect):
            try:
                count = await self.collect_single(code, days=3)
                total += count
                if count > 0:
                    await self.cache.set_incremental_marker(f"main_flow:{code}", today_str)
            except Exception as e:
                logger.error(f"主力资金流增量采集失败: code={code}, error={e}")
            if i < len(to_collect) - 1:
                await asyncio.sleep(0.3)

        logger.info(f"主力资金流增量采集完成: {len(to_collect)} 只, 共 {total} 条")
        return total

    @staticmethod
    def _infer_market(code: str) -> str:
        """根据代码推断市场"""
        if code.startswith(("6",)):
            return "sh"
        if code.startswith(("0", "3")):
            return "sz"
        if code.startswith(("4", "8")):
            return "bj"
        return "sz"

    @staticmethod
    def _ts_code_to_code(value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text.split(".", 1)[0].zfill(6)

    @staticmethod
    def _sum_present(*values: float | None) -> float | None:
        present = [v for v in values if v is not None]
        return sum(present) if present else None

    @staticmethod
    def _to_yuan(value) -> float | None:
        """Tushare moneyflow amount: 万元 -> 元。"""
        if value is None:
            return None
        try:
            v = float(value)
            return None if pd.isna(v) else v * 10000
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_amount(row, candidates: list[str]) -> float | None:
        """尝试从多个可能的列名中解析金额"""
        for col in candidates:
            val = row.get(col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _parse_float(row, candidates: list[str]) -> float | None:
        """尝试解析浮点值"""
        for col in candidates:
            val = row.get(col)
            if val is not None and not (isinstance(val, float) and pd.isna(val)):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return None
