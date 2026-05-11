import asyncio
from datetime import date, datetime, timedelta
import json
from json import JSONDecodeError
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import akshare as ak
import httpx
import pandas as pd
from sqlalchemy import func, select

from common.config import get_settings
from common.logger import get_logger
from common.models import DailyKline, Stock
from data_collector.storage import DataStorage
from data_collector.cache.redis_cache import RedisCache
from data_collector.cache.incremental import IncrementalManager

logger = get_logger(__name__)


class KlineCollector:
    """日K线采集器 - AKShare/Tushare优先，直连行情源兜底。"""

    EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    EASTMONEY_CLIST_URL = "https://{host}.push2.eastmoney.com/api/qt/clist/get"
    SINA_KLINE_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/{callback}/CN_MarketDataService.getKLineData"
    TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    FULL_MARKET_COVERAGE_THRESHOLD = 95.0
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

    async def collect_full_market_daily(
        self,
        trade_date: date | None = None,
        *,
        lookback_days: int = 20,
        min_coverage_pct: float = FULL_MARKET_COVERAGE_THRESHOLD,
        mode: str = "auto",
    ) -> dict[str, Any]:
        """批量采集全市场日行情快照并写入 daily_klines。"""
        lookback_days = max(1, min(int(lookback_days or 1), 30))
        min_coverage_pct = max(0.0, min(float(min_coverage_pct), 100.0))
        mode = (mode or "auto").lower()
        if mode not in {"auto", "daily", "intraday"}:
            mode = "auto"
        universe = await self._load_a_share_universe()
        universe_codes = set(universe)
        source_errors: list[str] = []

        source = ""
        quote_time: datetime | None = None
        resolved_trade_date: date | None = None
        records: list[dict[str, Any]] = []
        stock_updates: list[dict[str, Any]] = []

        fetchers = {
            "daily": (
                (
                    "tushare_full_market",
                    lambda: self._fetch_tushare_full_market_daily(trade_date, lookback_days, universe_codes),
                ),
            ),
            "intraday": (
                (
                    "eastmoney_intraday",
                    lambda: self._fetch_eastmoney_full_market_spot(trade_date, universe_codes),
                ),
                (
                    "akshare_intraday",
                    lambda: self._fetch_akshare_full_market_spot(trade_date, universe_codes),
                ),
            ),
            "auto": (
                (
                    "tushare_full_market",
                    lambda: self._fetch_tushare_full_market_daily(trade_date, lookback_days, universe_codes),
                ),
                (
                    "eastmoney_intraday",
                    lambda: self._fetch_eastmoney_full_market_spot(trade_date, universe_codes),
                ),
                (
                    "akshare_intraday",
                    lambda: self._fetch_akshare_full_market_spot(trade_date, universe_codes),
                ),
            ),
        }[mode]

        for candidate_source, fetcher in fetchers:
            result = await fetcher()
            if result["records"]:
                source = candidate_source
                resolved_trade_date = result["trade_date"]
                quote_time = result.get("quote_time")
                records = result["records"]
                stock_updates = result["stock_updates"]
                break
            if result.get("error"):
                source_errors.append(result["error"])

        if not records or resolved_trade_date is None:
            return {
                "status": "failed",
                "trade_date": str(trade_date) if trade_date else None,
                "data_mode": mode,
                "quote_time": None,
                "source": None,
                "records_count": 0,
                "stock_updates_count": 0,
                "market_coverage": self._empty_coverage(len(universe), min_coverage_pct),
                "source_errors": source_errors,
                "message": "全市场行情采集失败，未获得可入库的真实行情数据",
            }

        enrichment_source, enrichment_updates = await self._enrich_full_market_fields(
            records,
            resolved_trade_date,
            universe_codes,
        )
        if enrichment_updates:
            stock_updates.extend(enrichment_updates)

        for record in records:
            record["source"] = source
        await self.storage.upsert_daily_klines(records)
        if stock_updates:
            await self.storage.update_stock_market_fields(stock_updates)
        history_records_count = await self._collect_tushare_recent_history(
            resolved_trade_date,
            lookback_days,
            universe_codes,
        )

        coverage = await self._coverage_for_date(resolved_trade_date, len(universe), min_coverage_pct)
        status = "completed" if coverage["is_full_market"] else "partial"
        logger.info(
            "全市场日行情采集完成: trade_date=%s, source=%s, records=%s, coverage=%.2f%%",
            resolved_trade_date,
            source,
            len(records),
            coverage["coverage_pct"],
        )
        return {
            "status": status,
            "trade_date": str(resolved_trade_date),
            "data_mode": mode,
            "source": source,
            "quote_time": quote_time.isoformat(timespec="seconds") if quote_time else None,
            "records_count": len(records),
            "history_records_count": history_records_count,
            "stock_updates_count": len(stock_updates),
            "market_coverage": coverage,
            "enrichment_source": enrichment_source,
            "source_errors": source_errors,
            "message": "全市场行情采集完成" if status == "completed" else "全市场行情采集完成但覆盖率不足",
        }

    async def _load_a_share_universe(self) -> list[str]:
        async with self.storage.session_factory() as session:
            rows = (await session.execute(select(Stock.code).order_by(Stock.code))).scalars().all()
        codes: list[str] = []
        for code in rows:
            clean = self._clean_stock_code(code)
            if clean.isdigit() and clean.startswith(("0", "3", "4", "6", "8", "9")):
                codes.append(clean)
        return codes

    async def _enrich_full_market_fields(
        self,
        records: list[dict[str, Any]],
        trade_date: date,
        universe_codes: set[str],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        if not records:
            return None, []
        turnover_count = sum(1 for item in records if item.get("turnover_rate") is not None)
        amount_count = sum(1 for item in records if item.get("amount") is not None)
        volume_count = sum(1 for item in records if item.get("volume") is not None)
        enough = len(records) * 0.9
        if turnover_count >= enough and amount_count >= enough and volume_count >= enough:
            return None, []

        for source_name, fetcher in (
            ("eastmoney_full", lambda: self._fetch_eastmoney_full_market_spot(trade_date, universe_codes)),
            ("akshare_full_market", lambda: self._fetch_akshare_full_market_spot(trade_date, universe_codes)),
        ):
            result = await fetcher()
            spot_records = result.get("records") or []
            if not spot_records:
                continue
            spot_by_code = {item["code"]: item for item in spot_records}
            for record in records:
                spot = spot_by_code.get(record["code"])
                if not spot:
                    continue
                for field in ("volume", "amount", "turnover_rate"):
                    if record.get(field) is None and spot.get(field) is not None:
                        record[field] = spot[field]
            return source_name, result.get("stock_updates") or []
        return None, []

    async def _fetch_tushare_full_market_daily(
        self,
        trade_date: date | None,
        lookback_days: int,
        universe_codes: set[str],
    ) -> dict[str, Any]:
        token = get_settings().data_source.tushare_token
        if not token:
            return self._empty_full_market_result("Tushare token 未配置")
        try:
            import tushare as ts
        except ImportError:
            return self._empty_full_market_result("Python package 'tushare' 未安装")

        def _fetch():
            ts.set_token(token)
            pro = ts.pro_api(token)
            days = [trade_date] if trade_date else [date.today() - timedelta(days=i) for i in range(lookback_days)]
            for current in days:
                day_str = current.strftime("%Y%m%d")
                daily = pro.daily(trade_date=day_str)
                if daily is None or daily.empty:
                    continue
                try:
                    basic = pro.daily_basic(
                        trade_date=day_str,
                        fields="ts_code,trade_date,turnover_rate,total_mv",
                    )
                except Exception:
                    basic = None
                try:
                    bak = pro.bak_daily(trade_date=day_str)
                except Exception:
                    bak = None
                try:
                    stock_basic = pro.stock_basic(
                        exchange="",
                        list_status="L",
                        fields="ts_code,symbol,name,market,list_date",
                    )
                except Exception:
                    stock_basic = None
                return current, daily, basic, bak, stock_basic
            return None, None, None, None, None

        try:
            resolved_date, daily, basic, bak, stock_basic = await asyncio.to_thread(_fetch)
        except Exception as e:
            return self._empty_full_market_result(f"Tushare全市场日行情采集失败: {e}")
        if daily is None or daily.empty or resolved_date is None:
            return self._empty_full_market_result("Tushare未返回可用交易日行情")

        daily = daily.copy()
        daily["code"] = daily["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
        if basic is not None and not basic.empty:
            basic = basic.copy()
            basic["code"] = basic["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
            daily = daily.merge(basic[["code", "turnover_rate", "total_mv"]], on="code", how="left")
        if bak is not None and not bak.empty:
            bak = bak.copy()
            bak["code"] = bak["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
            bak = bak.rename(
                columns={
                    "name": "bak_name",
                    "turn_over": "bak_turnover_rate",
                    "total_mv": "bak_total_mv",
                }
            )
            daily = daily.merge(
                bak[["code", "bak_name", "bak_turnover_rate", "bak_total_mv"]],
                on="code",
                how="left",
            )
        if stock_basic is not None and not stock_basic.empty:
            stock_basic = stock_basic.copy()
            stock_basic["code"] = stock_basic["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
            stock_basic = stock_basic.rename(
                columns={
                    "name": "basic_name",
                    "market": "basic_market",
                    "list_date": "basic_list_date",
                }
            )
            daily = daily.merge(
                stock_basic[["code", "basic_name", "basic_market", "basic_list_date"]],
                on="code",
                how="left",
            )

        records: list[dict[str, Any]] = []
        stock_updates: list[dict[str, Any]] = []
        for _, row in daily.iterrows():
            code = self._clean_stock_code(row.get("code"))
            if universe_codes and code not in universe_codes:
                continue
            open_price = self._to_float(row.get("open"))
            close_price = self._to_float(row.get("close"))
            high_price = self._to_float(row.get("high"))
            low_price = self._to_float(row.get("low"))
            if not code or None in (open_price, close_price, high_price, low_price) or close_price <= 0:
                continue
            records.append(
                {
                    "code": code,
                    "trade_date": resolved_date,
                    "open": open_price,
                    "close": close_price,
                    "high": high_price,
                    "low": low_price,
                    "volume": self._to_int(row.get("vol")),
                    "amount": self._money_wan_to_yuan(row.get("amount"), multiplier=1000),
                    "turnover_rate": self._first_float(row.get("turnover_rate"), row.get("bak_turnover_rate")),
                }
            )
            market_cap = self._money_wan_to_yuan(row.get("total_mv"), multiplier=10000)
            if market_cap is None:
                market_cap = self._money_wan_to_yuan(row.get("bak_total_mv"), multiplier=100000000)
            if market_cap is not None:
                stock_updates.append(
                    {
                        "code": code,
                        "name": self._clean_text(row.get("basic_name")) or self._clean_text(row.get("bak_name")),
                        "market": self._clean_text(row.get("basic_market")) or self._market_from_code(code),
                        "market_cap": market_cap,
                        "listed_date": self._to_date(row.get("basic_list_date")),
                        "is_st": None,
                    }
                )

        return {
            "trade_date": resolved_date,
            "quote_time": datetime.now(),
            "records": records,
            "stock_updates": stock_updates,
            "error": None,
        }

    async def _collect_tushare_recent_history(
        self,
        latest_trade_date: date,
        lookback_days: int,
        universe_codes: set[str],
    ) -> int:
        token = get_settings().data_source.tushare_token
        if not token or lookback_days <= 1:
            return 0
        try:
            import tushare as ts
        except ImportError:
            return 0

        def _fetch_history():
            ts.set_token(token)
            pro = ts.pro_api(token)
            batches = []
            for offset in range(1, lookback_days):
                current = latest_trade_date - timedelta(days=offset)
                day_str = current.strftime("%Y%m%d")
                daily = pro.daily(trade_date=day_str)
                if daily is None or daily.empty:
                    continue
                try:
                    bak = pro.bak_daily(trade_date=day_str)
                except Exception:
                    bak = None
                batches.append((current, daily, bak))
            return batches

        try:
            batches = await asyncio.to_thread(_fetch_history)
        except Exception as e:
            logger.info(f"Tushare全市场历史K线补齐失败: {e}")
            return 0

        records: list[dict[str, Any]] = []
        for trade_date_val, daily, bak in batches:
            daily = daily.copy()
            daily["code"] = daily["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
            if bak is not None and not bak.empty:
                bak = bak.copy()
                bak["code"] = bak["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
                bak = bak.rename(columns={"turn_over": "bak_turnover_rate"})
                daily = daily.merge(bak[["code", "bak_turnover_rate"]], on="code", how="left")
            for _, row in daily.iterrows():
                code = self._clean_stock_code(row.get("code"))
                if universe_codes and code not in universe_codes:
                    continue
                open_price = self._to_float(row.get("open"))
                close_price = self._to_float(row.get("close"))
                high_price = self._to_float(row.get("high"))
                low_price = self._to_float(row.get("low"))
                if not code or None in (open_price, close_price, high_price, low_price) or close_price <= 0:
                    continue
                records.append(
                    {
                        "code": code,
                        "trade_date": trade_date_val,
                        "open": open_price,
                        "close": close_price,
                        "high": high_price,
                        "low": low_price,
                        "volume": self._to_int(row.get("vol")),
                        "amount": self._money_wan_to_yuan(row.get("amount"), multiplier=1000),
                        "turnover_rate": self._first_float(row.get("turnover_rate"), row.get("bak_turnover_rate")),
                        "source": "tushare_full_market",
                    }
                )
        if records:
            await self.storage.upsert_daily_klines(records)
            logger.info(f"补齐全市场历史K线: days={len(batches)}, records={len(records)}")
        return len(records)

    async def _fetch_eastmoney_clist_records(self) -> list[dict[str, Any]]:
        params = {
            "pn": "1",
            "pz": "100",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "fields": "f2,f3,f5,f6,f8,f12,f14,f15,f16,f17,f18,f20,f124",
        }
        errors: list[str] = []
        for host in self._push2_hosts():
            records: list[dict[str, Any]] = []
            total = 0
            url = self.EASTMONEY_CLIST_URL.format(host=host)
            try:
                async with self._market_client(self._market_headers("https://quote.eastmoney.com")) as client:
                    for page in range(1, 100):
                        resp = await client.get(url, params={**params, "pn": str(page)})
                        resp.raise_for_status()
                        payload = resp.json()
                        data = payload.get("data") or {}
                        diff = data.get("diff") or []
                        if not isinstance(diff, list):
                            raise ValueError("Eastmoney response data.diff is not a list")
                        if page == 1 and not diff:
                            raise ValueError("Eastmoney response data.diff is empty")
                        records.extend(diff)
                        total = int(data.get("total") or len(records))
                        if len(records) >= total or not diff:
                            break
                if records:
                    return records
            except Exception as e:
                errors.append(f"{host}.push2: {e.__class__.__name__}: {e}")
        try:
            return await asyncio.to_thread(self._fetch_eastmoney_clist_records_with_browser, params)
        except Exception as e:
            errors.append(f"browser_fallback: {e.__class__.__name__}: {e}")
        visible_errors = errors[:8]
        browser_error = next((item for item in errors if item.startswith("browser_fallback:")), None)
        if browser_error and browser_error not in visible_errors:
            visible_errors.append(browser_error)
        raise RuntimeError("; ".join(visible_errors) or "所有东方财富push2分片均不可用")

    @classmethod
    def _fetch_eastmoney_clist_records_with_browser(cls, params: dict[str, Any]) -> list[dict[str, Any]]:
        node = cls._node_binary()
        if not node:
            raise RuntimeError("node executable not found")
        script_path = Path(__file__).resolve().parents[2] / "scripts" / "eastmoney_browser_fetch.js"
        if not script_path.exists():
            raise RuntimeError(f"browser fetch script not found: {script_path}")
        payload = {
            "hosts": cls._push2_hosts(),
            "params": params,
            "max_pages": 100,
            "page_timeout_ms": 15000,
        }
        proc = subprocess.run(
            [node, str(script_path)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=180,
        )
        stdout = proc.stdout.strip()
        if not stdout:
            raise RuntimeError(proc.stderr.strip() or f"browser fetch exited with code {proc.returncode}")
        result = json.loads(stdout)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or f"browser fetch failed with code {proc.returncode}")
        records = result.get("records") or []
        if not isinstance(records, list) or not records:
            raise RuntimeError("browser fetch returned no records")
        return records

    def _eastmoney_spot_records_to_daily(
        self,
        raw_records: list[dict[str, Any]],
        requested_trade_date: date | None,
        universe_codes: set[str],
    ) -> dict[str, Any]:
        quote_times = [self._to_timestamp_datetime(item.get("f124")) for item in raw_records]
        quote_times = [item for item in quote_times if item is not None]
        quote_dates = [item.date() for item in quote_times]
        quote_time = max(quote_times) if quote_times else datetime.now()
        resolved_date = requested_trade_date or (max(quote_dates) if quote_dates else date.today())
        records: list[dict[str, Any]] = []
        stock_updates: list[dict[str, Any]] = []

        for item in raw_records:
            code = self._clean_stock_code(item.get("f12"))
            if universe_codes and code not in universe_codes:
                continue
            item_date = self._to_timestamp_date(item.get("f124"))
            if requested_trade_date and item_date and item_date != requested_trade_date:
                continue
            open_price = self._to_float(item.get("f17"))
            close_price = self._to_float(item.get("f2"))
            high_price = self._to_float(item.get("f15"))
            low_price = self._to_float(item.get("f16"))
            if not code or None in (open_price, close_price, high_price, low_price) or close_price <= 0:
                continue
            records.append(
                {
                    "code": code,
                    "trade_date": resolved_date,
                    "open": open_price,
                    "close": close_price,
                    "high": high_price,
                    "low": low_price,
                    "volume": self._to_int(item.get("f5")),
                    "amount": self._to_float(item.get("f6")),
                    "turnover_rate": self._to_float(item.get("f8")),
                }
            )
            stock_updates.append(
                {
                    "code": code,
                    "name": self._clean_text(item.get("f14")),
                    "market": self._market_from_code(code),
                    "market_cap": self._to_float(item.get("f20")),
                    "is_st": self._is_st_name(item.get("f14")),
                }
            )

        if not records:
            return self._empty_full_market_result("东方财富全市场快照没有匹配股票基础库的有效行情")
        return {
            "trade_date": resolved_date,
            "quote_time": quote_time,
            "records": records,
            "stock_updates": stock_updates,
            "error": None,
        }

    async def _coverage_for_date(
        self,
        trade_date: date,
        total_stock_count: int,
        min_coverage_pct: float,
    ) -> dict[str, Any]:
        async with self.storage.session_factory() as session:
            kline_stock_count = (
                await session.execute(
                    select(func.count(func.distinct(DailyKline.code))).where(DailyKline.trade_date == trade_date)
                )
            ).scalar_one()
            amount_count = (
                await session.execute(
                    select(func.count(func.distinct(DailyKline.code))).where(
                        DailyKline.trade_date == trade_date,
                        DailyKline.amount.isnot(None),
                    )
                )
            ).scalar_one()
            volume_count = (
                await session.execute(
                    select(func.count(func.distinct(DailyKline.code))).where(
                        DailyKline.trade_date == trade_date,
                        DailyKline.volume.isnot(None),
                    )
                )
            ).scalar_one()
            turnover_count = (
                await session.execute(
                    select(func.count(func.distinct(DailyKline.code))).where(
                        DailyKline.trade_date == trade_date,
                        DailyKline.turnover_rate.isnot(None),
                    )
                )
            ).scalar_one()
        coverage_pct = kline_stock_count / total_stock_count * 100 if total_stock_count else 0.0
        volume_pct = volume_count / total_stock_count * 100 if total_stock_count else 0.0
        amount_pct = amount_count / total_stock_count * 100 if total_stock_count else 0.0
        turnover_pct = turnover_count / total_stock_count * 100 if total_stock_count else 0.0
        field_coverage = {
            "volume_count": int(volume_count or 0),
            "volume_pct": round(volume_pct, 2),
            "amount_count": int(amount_count or 0),
            "amount_pct": round(amount_pct, 2),
            "turnover_rate_count": int(turnover_count or 0),
            "turnover_rate_pct": round(turnover_pct, 2),
        }
        return {
            "total_stock_count": int(total_stock_count or 0),
            "kline_stock_count": int(kline_stock_count or 0),
            "coverage_pct": round(coverage_pct, 2),
            "min_coverage_pct": round(min_coverage_pct, 2),
            "is_full_market": all(
                pct >= min_coverage_pct for pct in (coverage_pct, volume_pct, amount_pct, turnover_pct)
            ),
            "field_coverage": field_coverage,
        }

    @staticmethod
    def _empty_coverage(total_stock_count: int, min_coverage_pct: float) -> dict[str, Any]:
        return {
            "total_stock_count": int(total_stock_count or 0),
            "kline_stock_count": 0,
            "coverage_pct": 0.0,
            "min_coverage_pct": round(min_coverage_pct, 2),
            "is_full_market": False,
            "field_coverage": {
                "volume_count": 0,
                "volume_pct": 0.0,
                "amount_count": 0,
                "amount_pct": 0.0,
                "turnover_rate_count": 0,
                "turnover_rate_pct": 0.0,
            },
        }

    def _empty_full_market_result(self, error: str) -> dict[str, Any]:
        return {"trade_date": None, "records": [], "stock_updates": [], "error": error}

    @classmethod
    def _push2_hosts(cls) -> list[str]:
        return ["17", "79", "69", "70", "80", "82", "29", "1", "64"]

    @staticmethod
    def _node_binary() -> str | None:
        nvm_dir = Path.home() / ".nvm/versions/node"
        candidates: list[Path | str | None] = []
        if nvm_dir.exists():
            candidates.extend(sorted(nvm_dir.glob("v*/bin/node"), reverse=True))
        candidates.append(shutil.which("node"))
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                return str(path)
        return None

    @classmethod
    def _market_from_code(cls, code: str) -> str | None:
        clean = cls._clean_stock_code(code)
        if clean.startswith(("6", "9")):
            return "SH"
        if clean.startswith(("0", "3")):
            return "SZ"
        if clean.startswith(("4", "8")):
            return "BJ"
        return None

    @staticmethod
    def _clean_text(value) -> str | None:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null", "-"}:
            return None
        return text

    @classmethod
    def _is_st_name(cls, value) -> bool | None:
        text = cls._clean_text(value)
        if text is None:
            return None
        return "ST" in text.upper()

    def _money_wan_to_yuan(self, value, *, multiplier: int) -> float | None:
        number = self._to_float(value)
        return number * multiplier if number is not None else None

    @staticmethod
    def _to_timestamp_date(value) -> date | None:
        parsed = KlineCollector._to_timestamp_datetime(value)
        return parsed.date() if parsed else None

    @staticmethod
    def _to_timestamp_datetime(value) -> datetime | None:
        if value is None or pd.isna(value):
            return None
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        if number <= 0:
            return None
        try:
            return datetime.fromtimestamp(number)
        except (OSError, OverflowError, ValueError):
            return None

    async def _fetch_eastmoney_full_market_spot(
        self,
        requested_trade_date: date | None,
        universe_codes: set[str],
    ) -> dict[str, Any]:
        try:
            raw_records = await self._fetch_eastmoney_clist_records()
        except Exception as e:
            return self._empty_full_market_result(f"东方财富全市场快照采集失败: {e}")
        return self._eastmoney_spot_records_to_daily(raw_records, requested_trade_date, universe_codes)

    async def _fetch_akshare_full_market_spot(
        self,
        requested_trade_date: date | None,
        universe_codes: set[str],
    ) -> dict[str, Any]:
        try:
            df = await asyncio.to_thread(ak.stock_zh_a_spot_em)
        except Exception as e:
            return self._empty_full_market_result(f"AKShare全市场快照采集失败: {e}")
        if df is None or df.empty:
            return self._empty_full_market_result("AKShare全市场快照为空")

        resolved_date = requested_trade_date or date.today()
        records: list[dict[str, Any]] = []
        stock_updates: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            code = self._clean_stock_code(row.get("代码"))
            if universe_codes and code not in universe_codes:
                continue
            open_price = self._to_float(row.get("今开"))
            close_price = self._to_float(row.get("最新价"))
            high_price = self._to_float(row.get("最高"))
            low_price = self._to_float(row.get("最低"))
            if not code or None in (open_price, close_price, high_price, low_price) or close_price <= 0:
                continue
            records.append(
                {
                    "code": code,
                    "trade_date": resolved_date,
                    "open": open_price,
                    "close": close_price,
                    "high": high_price,
                    "low": low_price,
                    "volume": self._to_int(row.get("成交量")),
                    "amount": self._to_float(row.get("成交额")),
                    "turnover_rate": self._to_float(row.get("换手率")),
                }
            )
            stock_updates.append(
                {
                    "code": code,
                    "name": self._clean_text(row.get("名称")),
                    "market": self._market_from_code(code),
                    "market_cap": self._to_float(row.get("总市值")),
                    "is_st": self._is_st_name(row.get("名称")),
                }
            )
        return {"trade_date": resolved_date, "records": records, "stock_updates": stock_updates, "error": None}

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

    def _first_float(self, *values) -> float | None:
        for value in values:
            number = self._to_float(value)
            if number is not None:
                return number
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
        headers = {
            "User-Agent": settings.eastmoney_user_agent or self.DEFAULT_USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer,
        }
        if settings.eastmoney_cookie:
            headers["Cookie"] = settings.eastmoney_cookie
        return headers

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
