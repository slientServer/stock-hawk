import asyncio
from datetime import date

import akshare as ak
import pandas as pd

from common.config import get_settings
from common.logger import get_logger
from data_collector.storage import DataStorage

logger = get_logger(__name__)


class StockBasicCollector:
    """A股基本信息采集器"""

    def __init__(self, storage: DataStorage):
        self.storage = storage

    async def collect_stock_list(self) -> int:
        """采集全市场股票列表，优先用 Tushare 补齐行业字段。"""
        records = await self._collect_stock_list_tushare()
        source = "tushare"
        if not records:
            records = await self._collect_stock_list_akshare()
            source = "akshare"

        if not records:
            return 0

        await self.storage.upsert_stock_basic(records)
        logger.info(f"写入股票基本信息: {len(records)} 条, source={source}")
        return len(records)

    async def _collect_stock_list_tushare(self) -> list[dict]:
        """使用 Tushare stock_basic 获取上市股票及行业。"""
        token = get_settings().data_source.tushare_token
        if not token:
            logger.info("TUSHARE_TOKEN 未配置，股票基础信息降级到 AKShare")
            return []

        try:
            import tushare as ts
        except ImportError:
            logger.warning("Python package 'tushare' 未安装，股票基础信息降级到 AKShare")
            return []

        def _fetch():
            ts.set_token(token)
            pro = ts.pro_api(token)
            return pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,symbol,name,industry,market,list_date",
            )

        try:
            df = await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.warning(f"Tushare采集股票基础信息失败，降级到 AKShare: {e}")
            return []

        if df is None or df.empty:
            logger.warning("Tushare股票基础信息为空，降级到 AKShare")
            return []

        records = []
        for _, row in df.iterrows():
            ts_code = self._clean_text(row.get("ts_code"))
            code = self._clean_text(row.get("symbol"))
            if not code and ts_code:
                code = ts_code.split(".")[0]
            if not code:
                continue
            code = code.zfill(6) if code.isdigit() else code
            name = self._clean_text(row.get("name")) or ""
            exchange = ts_code.split(".")[-1] if ts_code and "." in ts_code else ""
            listed_date = self._parse_date(row.get("list_date"))
            records.append({
                "code": code,
                "name": name,
                "industry": self._clean_text(row.get("industry")),
                "market": exchange or self._market_from_code(code),
                "market_cap": None,
                "listed_date": listed_date,
                "is_st": "ST" in name.upper() if name else False,
            })

        return records

    async def _collect_stock_list_akshare(self) -> list[dict]:
        """使用 AKShare 获取股票代码和名称；行业字段保持缺失。"""
        try:
            df = await asyncio.to_thread(ak.stock_info_a_code_name)
        except Exception as e:
            logger.error(f"AKShare采集股票列表失败: {e}")
            return []

        if df is None or df.empty:
            logger.warning("股票列表数据为空")
            return []

        records = []
        for _, row in df.iterrows():
            code = str(row["code"]).strip()
            name = str(row["name"]).strip() if "name" in row.index else ""
            records.append({
                "code": code,
                "name": name,
                "industry": None,
                "market": self._market_from_code(code),
                "market_cap": None,
                "is_st": "ST" in name.upper() if name else False,
            })

        return records

    @staticmethod
    def _clean_text(value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() == "nan":
            return None
        return text

    @staticmethod
    def _market_from_code(code: str) -> str:
        if code.startswith(("6", "9")):
            return "SH"
        if code.startswith(("0", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return "OTHER"

    async def is_st(self, code: str) -> bool:
        """判断是否ST（通过名称判断）"""
        try:
            df = await asyncio.to_thread(ak.stock_info_a_code_name)
            if df is None or df.empty:
                return False
            row = df[df["code"] == code]
            if row.empty:
                return False
            name = str(row.iloc[0]["name"])
            return "ST" in name.upper()
        except Exception as e:
            logger.error(f"判断ST失败: code={code}, error={e}")
            return False

    async def collect_stock_detail(self, codes: list[str] | None = None) -> int:
        """采集个股详情（市值+上市日期+名称），用于补充 stock_list 缺失的字段。
        
        优先使用 Tushare 批量补全名称，再用 akshare 逐只补充市值和上市日期。
        如果 codes 为空，从 stocks 表选取 market_cap 或 name 为空的股票补充。
        """
        if not codes:
            codes = await self._get_codes_missing_detail(limit=200)
            if not codes:
                logger.info("所有股票已有市值和名称数据，无需补充")
                return 0

        # 先用 Tushare 批量补全名称（快速、不触发反爬）
        name_fixed = await self._batch_fix_names_via_tushare(codes)

        # 再用 akshare 逐只补充市值和上市日期
        total = name_fixed
        # 重新获取仍缺市值的
        codes_need_detail = await self._get_codes_missing_market_cap(limit=200)
        for code in codes_need_detail:
            try:
                record = await self._fetch_individual_info(code)
                if record:
                    await self.storage.upsert_stock_basic([record])
                    total += 1
            except Exception as e:
                logger.debug(f"采集个股详情 {code} 失败: {e}")
            await asyncio.sleep(0.5)

        logger.info(f"个股详情采集完成: {total} 只更新")
        return total

    async def _batch_fix_names_via_tushare(self, codes: list[str]) -> int:
        """使用 Tushare 批量补全缺失的股票名称"""
        try:
            from common.config import get_settings
            token = get_settings().data_source.tushare_token
            if not token:
                return 0
            import tushare as ts
            ts.set_token(token)
            pro = ts.pro_api()
            df = await asyncio.to_thread(
                pro.stock_basic, exchange='', list_status='L', fields='ts_code,name'
            )
            if df is None or df.empty:
                return 0

            name_map = {}
            for _, row in df.iterrows():
                code = str(row['ts_code']).split('.')[0]
                name_map[code] = row['name']

            # 只更新缺名字的
            codes_missing_name = await self._get_codes_missing_name()
            if not codes_missing_name:
                return 0

            records = []
            for code in codes_missing_name:
                name = name_map.get(code)
                if name:
                    records.append({"code": code, "name": name, "market": self._market_from_code(code)})

            if records:
                await self.storage.upsert_stock_basic(records)
                logger.info(f"Tushare 批量补全名称: {len(records)} 只")
            return len(records)
        except Exception as e:
            logger.debug(f"Tushare 批量补名称失败: {e}")
            return 0

    async def _get_codes_missing_name(self) -> list[str]:
        """从数据库查询缺少名称的股票代码"""
        from sqlalchemy import text as sa_text
        async with self.storage.session_factory() as session:
            result = await session.execute(
                sa_text("SELECT code FROM stocks WHERE name IS NULL OR name = '' LIMIT 500"),
            )
            return [row[0] for row in result.fetchall()]

    async def _fetch_individual_info(self, code: str) -> dict | None:
        """通过 akshare 获取单只股票的市值和上市日期"""
        try:
            df = await asyncio.to_thread(ak.stock_individual_info_em, symbol=code)
        except Exception as e:
            logger.debug(f"akshare stock_individual_info_em {code} 失败: {e}")
            return None

        if df is None or df.empty:
            return None

        info = {}
        for _, row in df.iterrows():
            item = str(row.get("item") or row.get("指标") or "")
            value = row.get("value") or row.get("值")
            if "总市值" in item:
                info["market_cap"] = self._safe_float(value)
            elif "上市时间" in item or "上市日期" in item:
                info["listed_date"] = self._parse_date(value)
            elif "股票名称" in item or "名称" in item:
                info["name"] = str(value).strip() if value else None
            elif "行业" in item:
                info["industry"] = str(value).strip() if value else None

        if not info.get("market_cap") and not info.get("listed_date") and not info.get("name"):
            return None

        return {
            "code": code,
            "name": info.get("name"),
            "industry": info.get("industry"),
            "market": self._market_from_code(code),
            "market_cap": info.get("market_cap"),
            "listed_date": info.get("listed_date"),
            "is_st": "ST" in (info.get("name") or "").upper(),
        }

    async def _get_codes_missing_market_cap(self, limit: int = 200) -> list[str]:
        """从数据库查询缺少市值的股票代码"""
        from sqlalchemy import text as sa_text
        async with self.storage.session_factory() as session:
            result = await session.execute(
                sa_text("SELECT code FROM stocks WHERE market_cap IS NULL LIMIT :limit"),
                {"limit": limit},
            )
            return [row[0] for row in result.fetchall()]

    async def _get_codes_missing_detail(self, limit: int = 200) -> list[str]:
        """从数据库查询缺少市值或名称的股票代码"""
        from sqlalchemy import text as sa_text
        async with self.storage.session_factory() as session:
            result = await session.execute(
                sa_text("SELECT code FROM stocks WHERE market_cap IS NULL OR name IS NULL OR name = '' LIMIT :limit"),
                {"limit": limit},
            )
            return [row[0] for row in result.fetchall()]

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
