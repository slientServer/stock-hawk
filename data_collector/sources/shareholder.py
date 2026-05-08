import asyncio
from datetime import date
from typing import Any

import akshare as ak
import pandas as pd

from common.logger import get_logger
from data_collector.storage import DataStorage

logger = get_logger(__name__)


class ShareholderCollector:
    """股东户数采集器"""

    def __init__(
        self,
        storage: DataStorage,
        periods: int = 8,
        request_interval_seconds: float = 1.0,
    ):
        self.storage = storage
        self.periods = periods
        self.request_interval_seconds = request_interval_seconds

    async def collect_holder_count(self, code: str) -> int:
        """采集单只股票股东户数"""
        return await self.collect_batch([code])

    async def collect_batch(self, codes: list[str]) -> int:
        """批量采集多只股票的股东户数。

        当前 AKShare 的 stock_hold_num_cninfo 按报告期返回全市场数据，因此按季度拉取后过滤目标代码。
        """
        target_codes = {code for code in (self._normalize_code(item) for item in codes) if code}
        if not target_codes:
            return 0

        all_records: list[dict] = []
        periods = self._recent_report_periods(date.today(), self.periods)
        for i, period in enumerate(periods):
            df = await self._fetch_period(period)
            records = self._build_records(df, target_codes)
            if records:
                all_records.extend(records)

            if i < len(periods) - 1:
                await asyncio.sleep(self.request_interval_seconds)

        if not all_records:
            logger.info(f"批量采集股东户数完成: {len(target_codes)} 只股票, 共 0 条记录")
            return 0

        try:
            await self.storage.upsert_shareholder_counts(all_records)
        except Exception as e:
            logger.error(f"写入股东户数数据失败: {e}")
            return 0

        logger.info(f"批量采集股东户数完成: {len(target_codes)} 只股票, 共 {len(all_records)} 条记录")
        return len(all_records)

    async def _fetch_period(self, period: date) -> pd.DataFrame | None:
        period_text = period.strftime("%Y%m%d")
        try:
            return await asyncio.to_thread(ak.stock_hold_num_cninfo, date=period_text)
        except Exception as e:
            logger.error(f"AKShare采集股东户数失败 period={period_text}: {e}")
            return None

    def _build_records(self, df: pd.DataFrame | None, target_codes: set[str]) -> list[dict]:
        if df is None or df.empty:
            return []

        records: list[dict] = []
        for _, row in df.iterrows():
            try:
                code = self._normalize_code(self._first_value(row, ("证券代码", "code", "symbol")))
                if code is None or code not in target_codes:
                    continue

                end_date_val = self._parse_date(
                    self._first_value(row, ("变动日期", "截止日期", "end_date", "date"))
                )
                if end_date_val is None:
                    continue

                records.append({
                    "code": code,
                    "end_date": end_date_val,
                    "holder_count": self._parse_int(
                        self._first_value(row, ("本期股东人数", "股东户数", "holder_num"))
                    ),
                    "holder_count_change": self._parse_float(
                        self._first_value(row, ("股东人数增幅", "股东户数增减", "holder_num_change"))
                    ),
                    "avg_holding": self._parse_float(
                        self._first_value(row, ("本期人均持股数量", "户均持股市值", "avg_free_shares"))
                    ),
                    "source": "akshare",
                })
            except Exception as e:
                logger.warning(f"解析股东户数行失败: {e}")
                continue
        return records

    def _recent_report_periods(self, as_of: date, limit: int) -> list[date]:
        quarters = ((3, 31), (6, 30), (9, 30), (12, 31))
        periods: list[date] = []
        year = as_of.year
        while len(periods) < limit:
            for month, day in reversed(quarters):
                period = date(year, month, day)
                if period <= as_of:
                    periods.append(period)
                    if len(periods) >= limit:
                        break
            year -= 1
        return periods

    def _first_value(self, row: pd.Series, fields: tuple[str, ...]) -> Any:
        for field in fields:
            if field not in row.index:
                continue
            value = row.get(field)
            if value is None or pd.isna(value):
                continue
            return value
        return None

    def _normalize_code(self, code: Any) -> str | None:
        text = str(code or "").strip().upper()
        if not text:
            return None
        if "." in text:
            text = text.split(".", 1)[0]
        if text.startswith(("SH", "SZ", "BJ")):
            text = text[2:]
        if not text.isdigit():
            return None
        return text.zfill(6)

    def _parse_date(self, value: Any) -> date | None:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return pd.Timestamp(value).date()
        except Exception:
            return None

    def _parse_float(self, value: Any) -> float | None:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, str):
            value = value.strip().replace(",", "").replace("%", "")
            if value in {"", "-", "--", "None", "nan", "NaN", "null"}:
                return None
        parsed = pd.to_numeric(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return float(parsed)

    def _parse_int(self, value: Any) -> int | None:
        parsed = self._parse_float(value)
        return int(parsed) if parsed is not None else None
