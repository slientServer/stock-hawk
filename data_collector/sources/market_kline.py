import asyncio
from datetime import date, datetime, timedelta
import json
from json import JSONDecodeError
import re

import akshare as ak
import httpx
import pandas as pd

from common.config import get_settings
from common.logger import get_logger
from data_collector.storage import DataStorage
from data_collector.cache.redis_cache import RedisCache
from data_collector.cache.incremental import IncrementalManager

logger = get_logger(__name__)


class KlineCollector:
    """日K线采集器 - AKShare/Tushare优先，直连行情源兜底。"""

    EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    SINA_KLINE_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/{callback}/CN_MarketDataService.getKLineData"
    TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    DEFAULT_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    )

    def __init__(self, storage: DataStorage, cache: RedisCache, incremental: IncrementalManager | None = None):
        self.storage = storage
        self.cache = cache
        self.incremental = incremental

    async def collect_daily_kline(self, code: str, start_date: date = None, end_date: date = None) -> int:
        """采集单只股票日K线数据

        Args:
            code: 股票代码如 "600519"
            start_date: 开始日期，默认为最近一年
            end_date: 结束日期，默认今天
        Returns:
            采集到的记录数
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=365)

        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        source = "akshare"
        try:
            df = await asyncio.to_thread(
                ak.stock_zh_a_hist,
                symbol=code,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq",
            )
        except Exception as e:
            logger.warning(f"AKShare采集K线失败，尝试Tushare兜底: code={code}, error={e}")
            df = None

        if self._is_stale(df, end_date):
            latest_date = self._latest_trade_date(df)
            if latest_date is not None:
                logger.warning(
                    f"AKShare K线数据过旧，尝试Tushare兜底: code={code}, latest={latest_date}, end={end_date}"
                )
            df = None

        if df is None or df.empty:
            df = await self._fetch_tushare_daily(code, start_str, end_str)
            if df is not None and not df.empty:
                source = "tushare"

        if self._is_stale(df, end_date):
            latest_date = self._latest_trade_date(df)
            if latest_date is not None:
                logger.warning(
                    f"Tushare K线数据过旧，尝试直连行情源兜底: code={code}, latest={latest_date}, end={end_date}"
                )
            df = None

        if df is not None and not df.empty and source == "tushare":
            current_latest = self._latest_trade_date(df)
            if current_latest is not None and current_latest < end_date:
                direct_source, direct_df, direct_latest = await self._fetch_best_direct_daily(
                    code, start_date, end_date
                )
                if direct_df is not None and direct_latest is not None and direct_latest > current_latest:
                    df = direct_df
                    source = direct_source
                    logger.info(
                        f"K线使用更新的直连数据: code={code}, source={source}, latest={direct_latest}, "
                        f"previous_source=tushare, previous_latest={current_latest}"
                    )

        if df is None or df.empty:
            source, df, _ = await self._fetch_best_direct_daily(code, start_date, end_date)
            if df is not None and not df.empty:
                logger.info(f"K线使用兜底数据源: code={code}, source={source}, records={len(df)}")

        if df is None or df.empty:
            logger.info(f"K线数据为空: code={code}, {start_str}-{end_str}")
            return 0

        records = self._dataframe_to_records(code, df, source)

        if records:
            await self.storage.upsert_daily_klines(records)
            logger.info(f"写入K线: code={code}, records={len(records)}")

        return len(records)

    async def _fetch_tushare_daily(self, code: str, start_str: str, end_str: str) -> pd.DataFrame | None:
        token = get_settings().data_source.tushare_token
        if not token:
            return None
        try:
            import tushare as ts

            ts.set_token(token)
            pro = ts.pro_api(token)
            ts_code = self._to_ts_code(code)
            daily = await asyncio.to_thread(
                pro.daily,
                ts_code=ts_code,
                start_date=start_str,
                end_date=end_str,
            )
            if daily is None or daily.empty:
                return None
            daily = daily.sort_values("trade_date").copy()
            daily["trade_date"] = pd.to_datetime(daily["trade_date"], format="%Y%m%d").dt.date
            daily["amount"] = pd.to_numeric(daily.get("amount"), errors="coerce").fillna(0) * 1000

            try:
                basic = await asyncio.to_thread(
                    pro.daily_basic,
                    ts_code=ts_code,
                    start_date=start_str,
                    end_date=end_str,
                    fields="ts_code,trade_date,turnover_rate",
                )
                if basic is not None and not basic.empty:
                    basic = basic.copy()
                    basic["trade_date"] = pd.to_datetime(basic["trade_date"], format="%Y%m%d").dt.date
                    daily = daily.merge(
                        basic[["trade_date", "turnover_rate"]],
                        on="trade_date",
                        how="left",
                    )
            except Exception as e:
                logger.info(f"Tushare换手率采集失败: code={code}, error={e}")
            return daily
        except Exception as e:
            logger.error(f"Tushare采集K线失败: code={code}, error={e}")
            return None

    async def _fetch_best_direct_daily(
        self, code: str, start_date: date, end_date: date
    ) -> tuple[str, pd.DataFrame | None, date | None]:
        best_source = ""
        best_df: pd.DataFrame | None = None
        best_latest: date | None = None

        for fallback_source, fetcher in (
            ("eastmoney_direct", self._fetch_eastmoney_daily),
            ("sina_direct", self._fetch_sina_daily),
            ("tencent_direct", self._fetch_tencent_daily),
        ):
            candidate = await fetcher(code, start_date, end_date)
            candidate_latest = self._latest_trade_date(candidate)
            if candidate is None or candidate.empty or candidate_latest is None or self._is_stale(candidate, end_date):
                continue
            if best_latest is None or candidate_latest > best_latest:
                best_source = fallback_source
                best_df = candidate
                best_latest = candidate_latest
            if candidate_latest >= end_date:
                break

        return best_source, best_df, best_latest

    async def _fetch_eastmoney_daily(self, code: str, start_date: date, end_date: date) -> pd.DataFrame | None:
        secid = self._to_eastmoney_secid(code)
        if not secid:
            return None

        params = {
            "secid": secid,
            "klt": "101",
            "fqt": "1",
            "beg": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
            "lmt": str(self._fallback_limit(start_date, end_date, max_limit=10000)),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "wbp2u": "|0|0|0|web",
            "_": str(pd.Timestamp.now().value // 1_000_000),
        }
        headers = self._market_headers("https://quote.eastmoney.com")
        settings = get_settings().data_source
        if settings.eastmoney_cookie:
            headers["Cookie"] = settings.eastmoney_cookie

        try:
            async with self._market_client(headers) as client:
                resp = await client.get(self.EASTMONEY_KLINE_URL, params=params)
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, JSONDecodeError, ValueError) as e:
            logger.warning(f"东方财富直连K线失败: code={code}, error={e}")
            return None

        data = payload.get("data") or {}
        klines = data.get("klines") or []
        rows = []
        for item in klines:
            parts = str(item).split(",")
            if len(parts) < 11:
                continue
            trade_date = self._to_date(parts[0])
            if trade_date is None or trade_date < start_date or trade_date > end_date:
                continue
            rows.append(
                {
                    "trade_date": trade_date,
                    "open": self._to_float(parts[1]),
                    "close": self._to_float(parts[2]),
                    "high": self._to_float(parts[3]),
                    "low": self._to_float(parts[4]),
                    "volume": self._to_int(parts[5]),
                    "amount": self._to_float(parts[6]),
                    "turnover_rate": self._to_float(parts[10]),
                }
            )
        return pd.DataFrame(rows) if rows else None

    async def _fetch_sina_daily(self, code: str, start_date: date, end_date: date) -> pd.DataFrame | None:
        symbol = self._to_sina_symbol(code)
        if not symbol:
            return None

        callback = f"callback_{pd.Timestamp.now().value // 1_000_000}"
        params = {
            "symbol": symbol,
            "scale": "240",
            "ma": "no",
            "datalen": str(self._fallback_limit(start_date, end_date, max_limit=1023)),
        }
        try:
            async with self._market_client(self._market_headers("https://finance.sina.com.cn")) as client:
                resp = await client.get(self.SINA_KLINE_URL.format(callback=callback), params=params)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"新浪直连K线失败: code={code}, error={e}")
            return None

        payload_text = self._extract_json_array(resp.text)
        if not payload_text:
            logger.warning(f"新浪直连K线解析失败: code={code}")
            return None
        try:
            items = json.loads(payload_text)
        except JSONDecodeError as e:
            logger.warning(f"新浪直连K线JSON解析失败: code={code}, error={e}")
            return None

        rows = []
        for item in items:
            trade_date = self._to_date(item.get("day"))
            if trade_date is None or trade_date < start_date or trade_date > end_date:
                continue
            rows.append(
                {
                    "trade_date": trade_date,
                    "open": self._to_float(item.get("open")),
                    "close": self._to_float(item.get("close")),
                    "high": self._to_float(item.get("high")),
                    "low": self._to_float(item.get("low")),
                    "volume": self._to_int(item.get("volume")),
                    "amount": None,
                    "turnover_rate": None,
                }
            )
        return pd.DataFrame(rows) if rows else None

    async def _fetch_tencent_daily(self, code: str, start_date: date, end_date: date) -> pd.DataFrame | None:
        symbol = self._to_sina_symbol(code)
        if not symbol:
            return None

        params = {
            "_var": "kline_dayqfq",
            "param": f"{symbol},day,,,{self._fallback_limit(start_date, end_date, max_limit=800)},qfq",
        }
        try:
            async with self._market_client(self._market_headers("https://gu.qq.com")) as client:
                resp = await client.get(self.TENCENT_KLINE_URL, params=params)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"腾讯直连K线失败: code={code}, error={e}")
            return None

        text = resp.text.strip()
        if text.startswith("kline_dayqfq="):
            text = text.removeprefix("kline_dayqfq=").rstrip(";")
        try:
            payload = json.loads(text)
        except JSONDecodeError as e:
            logger.warning(f"腾讯直连K线JSON解析失败: code={code}, error={e}")
            return None
        if payload.get("code") != 0:
            logger.warning(f"腾讯直连K线返回异常: code={code}, response_code={payload.get('code')}")
            return None

        rows = []
        for stock_data in (payload.get("data") or {}).values():
            raw_rows = stock_data.get("qfqday") or stock_data.get("day") or []
            for item in raw_rows:
                if len(item) < 6:
                    continue
                trade_date = self._to_date(item[0])
                if trade_date is None or trade_date < start_date or trade_date > end_date:
                    continue
                rows.append(
                    {
                        "trade_date": trade_date,
                        "open": self._to_float(item[1]),
                        "close": self._to_float(item[2]),
                        "high": self._to_float(item[3]),
                        "low": self._to_float(item[4]),
                        "volume": self._to_int(item[5]),
                        "amount": self._to_float(item[6]) if len(item) > 6 else None,
                        "turnover_rate": None,
                    }
                )
            break
        return pd.DataFrame(rows) if rows else None

    def _dataframe_to_records(self, code: str, df: pd.DataFrame, source: str) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            trade_date_val = self._row_value(row, "日期", "trade_date")
            trade_date_val = self._to_date(trade_date_val)
            if trade_date_val is None:
                continue

            open_price = self._to_float(self._row_value(row, "开盘", "open"))
            close_price = self._to_float(self._row_value(row, "收盘", "close"))
            high_price = self._to_float(self._row_value(row, "最高", "high"))
            low_price = self._to_float(self._row_value(row, "最低", "low"))
            if None in (open_price, close_price, high_price, low_price):
                continue

            records.append(
                {
                    "code": code,
                    "trade_date": trade_date_val,
                    "open": open_price,
                    "close": close_price,
                    "high": high_price,
                    "low": low_price,
                    "volume": self._to_int(self._row_value(row, "成交量", "vol", "volume")),
                    "amount": self._to_float(self._row_value(row, "成交额", "amount")),
                    "turnover_rate": self._to_float(self._row_value(row, "换手率", "turnover_rate")),
                    "source": source,
                }
            )
        return records

    @staticmethod
    def _row_value(row: pd.Series, *keys: str):
        for key in keys:
            if key in row.index:
                return row.get(key)
        return None

    def _is_stale(self, df: pd.DataFrame | None, end_date: date) -> bool:
        latest = self._latest_trade_date(df)
        return latest is not None and latest < end_date - timedelta(days=3)

    @staticmethod
    def _latest_trade_date(df: pd.DataFrame | None) -> date | None:
        if df is None or df.empty:
            return None
        date_col = "日期" if "日期" in df.columns else "trade_date" if "trade_date" in df.columns else None
        if date_col is None:
            return None
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if dates.empty:
            return None
        return dates.max().date()

    @staticmethod
    def _to_date(value) -> date | None:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.date()
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()

    @staticmethod
    def _to_float(value) -> float | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        if not text or text in {"-", "null", "None", "nan"}:
            return None
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return None

    def _to_int(self, value) -> int | None:
        number = self._to_float(value)
        return int(number) if number is not None else None

    @staticmethod
    def _clean_stock_code(code: str) -> str:
        clean = str(code).strip().upper()
        for suffix in (".SH", ".SZ", ".BJ"):
            clean = clean.replace(suffix, "")
        for prefix in ("SH", "SZ", "BJ"):
            if clean.startswith(prefix):
                clean = clean[2:]
        return clean

    @classmethod
    def _to_eastmoney_secid(cls, code: str) -> str:
        clean = cls._clean_stock_code(code)
        if not clean.isdigit():
            return ""
        if clean.startswith(("6", "9")):
            return f"1.{clean}"
        if clean.startswith(("0", "3", "4", "8")):
            return f"0.{clean}"
        return ""

    @classmethod
    def _to_sina_symbol(cls, code: str) -> str:
        clean = cls._clean_stock_code(code)
        if not clean.isdigit():
            return ""
        if clean.startswith(("6", "9")):
            return f"sh{clean}"
        if clean.startswith(("0", "3")):
            return f"sz{clean}"
        if clean.startswith(("4", "8")):
            return f"bj{clean}"
        return ""

    @staticmethod
    def _fallback_limit(start_date: date, end_date: date, max_limit: int) -> int:
        days = max((end_date - start_date).days + 1, 1)
        return min(max(days * 2, 120), max_limit)

    def _market_headers(self, referer: str) -> dict[str, str]:
        settings = get_settings().data_source
        return {
            "User-Agent": settings.eastmoney_user_agent or self.DEFAULT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer,
        }

    @staticmethod
    def _market_client(headers: dict[str, str]) -> httpx.AsyncClient:
        settings = get_settings().data_source
        timeout = max(settings.market_request_timeout or 15, 3)
        kwargs = {
            "headers": headers,
            "timeout": httpx.Timeout(timeout),
            "follow_redirects": True,
        }
        if settings.market_proxy_url:
            kwargs["proxy"] = settings.market_proxy_url
        return httpx.AsyncClient(**kwargs)

    @staticmethod
    def _extract_json_array(text: str) -> str | None:
        match = re.search(r"\[\s*\{.*\}\s*\]", text, flags=re.S)
        return match.group(0) if match else None

    @staticmethod
    def _to_ts_code(code: str) -> str:
        clean = code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if clean.startswith(("4", "8")):
            return f"{clean}.BJ"
        if clean.startswith(("6", "9")):
            return f"{clean}.SH"
        return f"{clean}.SZ"

    async def collect_batch(self, codes: list[str], start_date: date = None):
        """批量采集多只股票K线"""
        total = 0
        for i, code in enumerate(codes):
            try:
                count = await self.collect_daily_kline(code, start_date=start_date)
                total += count
            except Exception as e:
                logger.error(f"批量采集K线异常: code={code}, error={e}")
            # 每只之间间隔200ms避免频率限制
            if i < len(codes) - 1:
                await asyncio.sleep(0.2)
        logger.info(f"批量采集完成: {len(codes)} 只股票, 共 {total} 条记录")
        return total

    async def collect_incremental(self, codes: list[str]):
        """增量采集 - 只采集新增交易日的数据"""
        today = date.today()
        for code in codes:
            # 检查Redis增量标记
            date_str = today.isoformat()
            already_collected = await self.cache.is_collected(f"kline:{code}", date_str)
            if already_collected:
                continue

            # 只采集最近5天的数据（覆盖可能的假期gap）
            start = today - timedelta(days=5)
            try:
                count = await self.collect_daily_kline(code, start_date=start, end_date=today)
                if count > 0:
                    await self.cache.set_incremental_marker(f"kline:{code}", date_str)
            except Exception as e:
                logger.error(f"增量采集失败: code={code}, error={e}")
            await asyncio.sleep(0.2)

    async def check_and_fill_missing_data(self, codes: list[str], lookback_days: int = 30):
        """启动时检查并补齐缺失数据"""
        if not self.incremental:
            logger.warning("IncrementalManager未设置，跳过补数据检查")
            return

        today = date.today()
        start = today - timedelta(days=lookback_days)

        for code in codes:
            try:
                missing_dates = await self.incremental.get_missing_trade_dates(code, start, today)
                if missing_dates:
                    logger.info(f"发现缺失数据: code={code}, missing_days={len(missing_dates)}")
                    earliest = min(missing_dates)
                    latest = max(missing_dates)
                    await self.collect_daily_kline(code, start_date=earliest, end_date=latest)
            except Exception as e:
                logger.error(f"补数据失败: code={code}, error={e}")
            await asyncio.sleep(0.2)
