"""机构持仓采集器 - 基金重仓股（akshare）"""

from __future__ import annotations

import asyncio
from datetime import date

import akshare as ak
import pandas as pd

from common.logger import get_logger
from data_collector.cache.redis_cache import RedisCache
from data_collector.storage import DataStorage

logger = get_logger(__name__)

# 最近4个报告期（季末）
def _recent_report_dates(count: int = 4) -> list[str]:
    """生成最近N个季度末日期字符串 YYYYMMDD"""
    today = date.today()
    quarters = []
    year, month = today.year, today.month
    # 找到当前或上一个季度末
    quarter_months = [3, 6, 9, 12]
    for _ in range(count + 4):  # 多算几个防止不够
        for qm in reversed(quarter_months):
            qdate = date(year, qm, 30 if qm in (6, 9) else 31)
            if qm == 3:
                qdate = date(year, 3, 31)
            if qdate < today and qdate.strftime("%Y%m%d") not in quarters:
                quarters.append(qdate.strftime("%Y%m%d"))
                if len(quarters) >= count:
                    return quarters
        year -= 1
    return quarters


class InstitutionalHoldingCollector:
    """机构持仓采集器：基金重仓股数据"""

    def __init__(self, storage: DataStorage, cache: RedisCache | None = None):
        self.storage = storage
        self.cache = cache

    async def collect_incremental(self) -> int:
        """增量采集：只采集最新一期尚未入库的持仓数据"""
        dates = _recent_report_dates(1)
        if not dates:
            return 0
        report_date = dates[0]
        marker_key = f"institutional:{report_date}"
        if self.cache and await self.cache.is_collected(marker_key, report_date):
            return 0

        count = await self._collect_for_date(report_date)
        if count > 0 and self.cache:
            await self.cache.set_incremental_marker(marker_key, report_date)
        return count

    async def collect_batch(self, periods: int = 4) -> int:
        """批量采集最近N期的基金重仓股数据"""
        dates = _recent_report_dates(periods)
        total = 0
        for report_date in dates:
            try:
                count = await self._collect_for_date(report_date)
                total += count
            except Exception as e:
                logger.error(f"采集机构持仓 {report_date} 失败: {e}")
            await asyncio.sleep(2.0)

        logger.info(f"机构持仓批量采集完成，共 {total} 条（{len(dates)} 期）")
        return total

    async def _collect_for_date(self, report_date: str) -> int:
        """采集指定报告期的基金重仓股"""
        try:
            df = await asyncio.to_thread(
                ak.stock_report_fund_hold, symbol="基金持仓", date=report_date
            )
        except Exception as e:
            logger.warning(f"akshare 基金重仓股 {report_date} 失败: {e}，尝试备选")
            df = await self._fallback_collect(report_date)

        if df is None or df.empty:
            logger.warning(f"机构持仓 {report_date} 无数据")
            return 0

        records = []
        parsed_date = self._parse_date(report_date)
        for _, row in df.iterrows():
            code = self._extract_code(row)
            if not code:
                continue

            # 基金持仓汇总模式：持有基金家数作为机构名称占位
            fund_count = row.get("持有基金家数")
            institution_name = f"基金汇总({fund_count}家)" if fund_count else "基金汇总"

            hold_amount = self._safe_float(
                row.get("持股总数") or row.get("持有数量") or row.get("hold_amount")
            )
            hold_change = self._safe_float(
                row.get("持股变动数值") or row.get("持股变动") or row.get("hold_change")
            )
            hold_ratio = self._safe_float(
                row.get("持股变动比例") or row.get("占流通股比") or row.get("hold_ratio")
            )

            records.append({
                "code": code,
                "report_date": parsed_date,
                "institution_name": institution_name[:200],
                "hold_amount": hold_amount,
                "hold_change": hold_change,
                "hold_ratio": hold_ratio,
                "source": "akshare_fund_hold",
            })

        if records:
            await self.storage.upsert_institutional_holdings(records)
        logger.info(f"机构持仓 {report_date} 采集: {len(records)} 条")
        return len(records)

    async def _fallback_collect(self, report_date: str) -> pd.DataFrame | None:
        """备选接口：stock_institute_hold（机构持仓汇总）"""
        try:
            # 转换日期格式: 20241231 -> 20244 (年份+季度)
            year = report_date[:4]
            month = int(report_date[4:6])
            quarter = {3: 1, 6: 2, 9: 3, 12: 4}.get(month, 4)
            symbol = f"{year}{quarter}"
            df = await asyncio.to_thread(
                ak.stock_institute_hold, symbol=symbol
            )
            return df
        except Exception as e:
            logger.warning(f"备选机构持仓接口也失败: {e}")
            return None

    @staticmethod
    def _extract_code(row) -> str | None:
        """从行数据提取股票代码"""
        for key in ("股票代码", "代码", "code", "symbol"):
            val = row.get(key)
            if val is not None:
                code = str(val).strip().replace(" ", "")
                # 去掉可能的交易所后缀
                if "." in code:
                    code = code.split(".")[0]
                if code and len(code) == 6 and code[0] in "0123456789":
                    return code
        return None

    @staticmethod
    def _parse_date(value) -> date | None:
        if value is None:
            return None
        try:
            return pd.to_datetime(str(value)).date()
        except Exception:
            return None

    @staticmethod
    def _safe_float(value) -> float | None:
        if value is None:
            return None
        try:
            v = float(value)
            return v if not pd.isna(v) else None
        except (ValueError, TypeError):
            return None
