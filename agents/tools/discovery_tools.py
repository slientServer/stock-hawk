"""产业链发现工具：AKShare 板块数据获取、股票验证、Neo4j 写入"""

import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.tools.base_tool import BaseTool, ToolResult
from common.config import get_settings
from common.models import AgentLog, Stock
from data_collector.cache.redis_cache import RedisCache


class DiscoveryTools(BaseTool):
    """产业链发现工具集"""

    tool_name = "discovery_tools"
    _MARKET_BOARD_CACHE_TTL_SECONDS = 4 * 60 * 60

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    @staticmethod
    def _market_headers() -> dict[str, str]:
        data_source = get_settings().data_source
        headers = {
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "close",
            "Referer": "https://quote.eastmoney.com/center/boardlist.html",
            "User-Agent": data_source.eastmoney_user_agent
            or (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
        }
        if data_source.eastmoney_cookie:
            headers["Cookie"] = data_source.eastmoney_cookie
        return headers

    @staticmethod
    def _market_proxies() -> dict[str, str] | None:
        proxy_url = get_settings().data_source.market_proxy_url.strip()
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

    @staticmethod
    def _market_timeout() -> int:
        timeout = get_settings().data_source.market_request_timeout
        try:
            return max(3, min(int(timeout), 60))
        except (TypeError, ValueError):
            return 15

    @staticmethod
    def _push2_urls(preferred_hosts: list[str]) -> list[str]:
        default_hosts = ["17", "79", "69", "70", "80", "82", "29", "1", "64"]
        hosts: list[str] = []
        for host in [*preferred_hosts, *default_hosts]:
            host_text = str(host).strip()
            if host_text and host_text not in hosts:
                hosts.append(host_text)
        return [f"https://{host}.push2.eastmoney.com/api/qt/clist/get" for host in hosts]

    @classmethod
    def _fetch_eastmoney_pages(
        cls, urls: str | list[str], params: dict[str, Any], max_pages: int = 5
    ) -> list[dict[str, Any]]:
        candidates = [urls] if isinstance(urls, str) else urls
        retries = 2
        errors: list[str] = []
        for attempt in range(retries):
            attempt_errors: list[str] = []
            for url in candidates:
                try:
                    return cls._fetch_eastmoney_pages_from_url(url, params, max_pages=max_pages)
                except Exception as e:
                    attempt_errors.append(f"{url}: {e.__class__.__name__}: {e}")
            try:
                return cls._fetch_eastmoney_pages_with_browser(candidates, params, max_pages=max_pages)
            except Exception as e:
                attempt_errors.append(f"browser_fallback: {e.__class__.__name__}: {e}")
            errors = attempt_errors
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))

        visible_errors = errors[:8]
        if len(errors) > 8:
            visible_errors.append(f"... {len(errors) - 8} more endpoint errors")
            browser_error = next((item for item in errors if item.startswith("browser_fallback:")), None)
            if browser_error and browser_error not in visible_errors:
                visible_errors.append(browser_error)
        raise RuntimeError("; ".join(visible_errors))

    @classmethod
    def _fetch_eastmoney_pages_with_browser(
        cls, urls: list[str], params: dict[str, Any], max_pages: int = 5
    ) -> list[dict[str, Any]]:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node executable not found")
        script_path = Path(__file__).resolve().parents[2] / "scripts" / "eastmoney_browser_fetch.js"
        if not script_path.exists():
            raise RuntimeError(f"browser fetch script not found: {script_path}")
        hosts = [url.split("//", 1)[-1].split(".", 1)[0] for url in urls]
        payload = {
            "hosts": hosts,
            "params": params,
            "max_pages": max_pages,
            "page_timeout_ms": 15000,
        }
        env = None
        node_bin = Path(node)
        if "node" not in node_bin.name:
            node = sys.executable
        proc = subprocess.run(
            [node, str(script_path)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=max(30, cls._market_timeout() * max_pages + 20),
            env=env,
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

    @classmethod
    def _fetch_eastmoney_pages_from_url(
        cls, url: str, params: dict[str, Any], max_pages: int = 5
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        total = 0
        while page <= max_pages:
            request_params = {**params, "pn": str(page)}
            with requests.Session() as session:
                response = session.get(
                    url,
                    params=request_params,
                    headers=cls._market_headers(),
                    proxies=cls._market_proxies(),
                    timeout=cls._market_timeout(),
                )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or {}
            diff = data.get("diff") or []
            if not isinstance(diff, list):
                raise ValueError("Eastmoney response data.diff is not a list")
            records.extend(diff)
            total = int(data.get("total") or len(records))
            if len(records) >= total or not diff:
                break
            page += 1
        return records

    @staticmethod
    def _records_to_board_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for index, record in enumerate(records, start=1):
            rows.append(
                {
                    "排名": index,
                    "板块名称": record.get("f14"),
                    "板块代码": record.get("f12"),
                    "最新价": record.get("f2"),
                    "涨跌额": record.get("f4"),
                    "涨跌幅": record.get("f3"),
                    "总市值": record.get("f20"),
                    "换手率": record.get("f8"),
                    "上涨家数": record.get("f104"),
                    "下跌家数": record.get("f105"),
                    "领涨股票": record.get("f128"),
                    "领涨股票-涨跌幅": record.get("f136"),
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _records_to_constituent_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
        rows = []
        for index, record in enumerate(records, start=1):
            rows.append(
                {
                    "序号": index,
                    "代码": record.get("f12"),
                    "名称": record.get("f14"),
                    "最新价": record.get("f2"),
                    "涨跌幅": record.get("f3"),
                    "涨跌额": record.get("f4"),
                    "成交量": record.get("f5"),
                    "成交额": record.get("f6"),
                    "振幅": record.get("f7"),
                    "最高": record.get("f15"),
                    "最低": record.get("f16"),
                    "今开": record.get("f17"),
                    "昨收": record.get("f18"),
                    "换手率": record.get("f8"),
                    "市盈率-动态": record.get("f9"),
                    "市净率": record.get("f23"),
                }
            )
        return pd.DataFrame(rows)

    @classmethod
    def _fetch_eastmoney_board_names(cls, source_type: str) -> pd.DataFrame:
        if source_type == "concept":
            urls = cls._push2_urls(["17", "70", "80", "82", "79"])
            params = {
                "pz": "100",
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f12",
                "fs": "m:90 t:3 f:!50",
                "fields": "f2,f3,f4,f8,f12,f14,f20,f104,f105,f128,f136",
            }
        else:
            urls = cls._push2_urls(["79", "17", "70", "80", "82"])
            params = {
                "pz": "100",
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": "m:90 t:2 f:!50",
                "fields": "f2,f3,f4,f8,f12,f14,f20,f104,f105,f128,f136",
            }
        records = cls._fetch_eastmoney_pages(urls, params)
        return cls._records_to_board_frame(records)

    @classmethod
    def _fetch_eastmoney_constituents(cls, board_code: str, fid: str) -> pd.DataFrame:
        urls = cls._push2_urls(["69", "29", "17", "79", "70", "80", "82"])
        params = {
            "pz": "100",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": fid,
            "fs": f"b:{board_code} f:!50",
            "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f12,f14,f15,f16,f17,f18,f23",
        }
        records = cls._fetch_eastmoney_pages(urls, params)
        return cls._records_to_constituent_frame(records)

    @staticmethod
    def _normalize_hot_boards(
        df: pd.DataFrame | None,
        top_n: int,
        min_change_pct: float,
        source_type: str,
        source_name: str,
    ) -> dict[str, Any]:
        """标准化东方财富板块列表，保留筛选诊断信息。"""
        if df is None or df.empty:
            return {
                "boards": [],
                "top_boards": [],
                "total_count": 0,
                "qualified_count": 0,
                "min_change_pct": min_change_pct,
                "max_change_pct": None,
                "source_type": source_type,
                "source_name": source_name,
            }
        if "涨跌幅" not in df.columns:
            raise ValueError(f"AKShare {source_name} data missing column: 涨跌幅")

        work = df.copy()
        work["涨跌幅"] = pd.to_numeric(work["涨跌幅"], errors="coerce")
        work = work.dropna(subset=["涨跌幅"]).sort_values("涨跌幅", ascending=False)
        top_boards = work.head(top_n).to_dict("records")
        qualified = work[work["涨跌幅"] >= min_change_pct].head(top_n)

        def _tag(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            tagged = []
            for record in records:
                item = dict(record)
                item["source_type"] = source_type
                item["source_name"] = source_name
                tagged.append(item)
            return tagged

        return {
            "boards": _tag(qualified.to_dict("records")),
            "top_boards": _tag(top_boards),
            "total_count": int(len(work)),
            "qualified_count": int(len(qualified)),
            "min_change_pct": min_change_pct,
            "max_change_pct": float(work.iloc[0]["涨跌幅"]) if not work.empty else None,
            "source_type": source_type,
            "source_name": source_name,
        }

    @staticmethod
    def _normalize_sina_sector_boards(
        df: pd.DataFrame | None,
        top_n: int,
        min_change_pct: float,
        source_type: str,
        source_name: str,
    ) -> dict[str, Any]:
        if df is None or df.empty:
            return DiscoveryTools._normalize_hot_boards(
                df,
                top_n=top_n,
                min_change_pct=min_change_pct,
                source_type=source_type,
                source_name=source_name,
            )

        work = df.copy()
        if "板块名称" not in work.columns and "板块" in work.columns:
            work["板块名称"] = work["板块"]
        if "板块代码" not in work.columns and "label" in work.columns:
            work["板块代码"] = work["label"]
        if "成交额" not in work.columns and "总成交额" in work.columns:
            work["成交额"] = work["总成交额"]
        if "领涨股票" not in work.columns and "股票名称" in work.columns:
            work["领涨股票"] = work["股票名称"]
        return DiscoveryTools._normalize_hot_boards(
            work,
            top_n=top_n,
            min_change_pct=min_change_pct,
            source_type=source_type,
            source_name=source_name,
        )

    async def _cache_market_board_payload(self, source_type: str, payload: dict[str, Any]) -> None:
        if not payload.get("boards") and not payload.get("top_boards"):
            return
        cache = RedisCache()
        try:
            await cache.connect()
            body = {
                "cached_at": time.time(),
                "source_type": source_type,
                "payload": json.loads(json.dumps(payload, ensure_ascii=False, default=str)),
            }
            await cache.redis.set(
                f"discovery:market_boards:{source_type}",
                json.dumps(body, ensure_ascii=False),
                ex=self._MARKET_BOARD_CACHE_TTL_SECONDS,
            )
        except Exception:
            return
        finally:
            try:
                await cache.close()
            except Exception:
                pass

    async def _get_redis_market_board_payload(self, source_type: str) -> dict[str, Any] | None:
        cache = RedisCache()
        try:
            await cache.connect()
            raw = await cache.redis.get(f"discovery:market_boards:{source_type}")
            if not raw:
                return None
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            return None
        finally:
            try:
                await cache.close()
            except Exception:
                pass
        return None

    async def _get_recent_logged_market_board_payload(self, source_type: str) -> dict[str, Any] | None:
        try:
            async with self._session_factory() as session:
                rows = (
                    await session.execute(
                        select(AgentLog)
                        .where(AgentLog.agent_id == "chain_discovery")
                        .order_by(desc(AgentLog.created_at))
                        .limit(25)
                    )
                ).scalars().all()
        except Exception:
            return None

        now = time.time()
        for row in rows:
            created_at = row.created_at
            if created_at and now - created_at.timestamp() > self._MARKET_BOARD_CACHE_TTL_SECONDS:
                continue
            output = row.output_data or {}
            source = ((output.get("diagnostics") or {}).get("sources") or {}).get(source_type) or {}
            if not source.get("success"):
                continue
            top_boards = source.get("top_boards") or []
            if not top_boards:
                continue
            payload = {
                "boards": top_boards,
                "top_boards": top_boards,
                "total_count": source.get("total_count") or len(top_boards),
                "qualified_count": source.get("qualified_count") or len(top_boards),
                "min_change_pct": source.get("min_change_pct"),
                "max_change_pct": source.get("max_change_pct"),
                "source_type": source_type,
                "source_name": source.get("source_name") or source_type,
            }
            return {"cached_at": created_at.timestamp() if created_at else None, "payload": payload}
        return None

    async def _get_cached_market_board_payload(
        self,
        source_type: str,
        top_n: int,
        min_change_pct: float,
        fallback_reason: str,
    ) -> dict[str, Any] | None:
        cached = await self._get_redis_market_board_payload(source_type)
        if cached:
            payload = self._cached_payload_for_request(
                source_type=source_type,
                raw_payload=cached.get("payload") or {},
                top_n=top_n,
                min_change_pct=min_change_pct,
                fallback_reason=fallback_reason,
                cache_source="redis",
                cached_at=cached.get("cached_at"),
            )
            if payload:
                return payload

        logged = await self._get_recent_logged_market_board_payload(source_type)
        if logged:
            payload = self._cached_payload_for_request(
                source_type=source_type,
                raw_payload=logged.get("payload") or {},
                top_n=top_n,
                min_change_pct=min_change_pct,
                fallback_reason=fallback_reason,
                cache_source="agent_log",
                cached_at=logged.get("cached_at"),
            )
            if payload:
                await self._cache_market_board_payload(source_type, payload)
                return payload
        return None

    def _cached_payload_for_request(
        self,
        source_type: str,
        raw_payload: dict[str, Any],
        top_n: int,
        min_change_pct: float,
        fallback_reason: str,
        cache_source: str,
        cached_at: Any,
    ) -> dict[str, Any] | None:
        records = raw_payload.get("boards") or raw_payload.get("top_boards") or []
        if not isinstance(records, list) or not records:
            return None

        work = pd.DataFrame(records)
        if "涨跌幅" not in work.columns:
            return None
        work["涨跌幅"] = pd.to_numeric(work["涨跌幅"], errors="coerce")
        work = work.dropna(subset=["涨跌幅"]).sort_values("涨跌幅", ascending=False)
        qualified = work[work["涨跌幅"] >= min_change_pct].head(top_n)
        top_boards = work.head(top_n)

        base_source_name = raw_payload.get("source_name") or source_type
        if "缓存" not in base_source_name:
            base_source_name = f"{base_source_name}(短期缓存)"
        record_source_type = raw_payload.get("source_type") or source_type

        def _tag(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            tagged = []
            for item in items:
                record = dict(item)
                record["source_type"] = record_source_type
                record["source_name"] = base_source_name
                record["market_cache_used"] = True
                tagged.append(record)
            return tagged

        cache_age_seconds = None
        try:
            cache_age_seconds = max(0, int(time.time() - float(cached_at)))
        except (TypeError, ValueError):
            pass

        return {
            "boards": _tag(qualified.to_dict("records")),
            "top_boards": _tag(top_boards.to_dict("records")),
            "total_count": int(raw_payload.get("total_count") or len(work)),
            "qualified_count": int(len(qualified)),
            "min_change_pct": min_change_pct,
            "max_change_pct": float(work.iloc[0]["涨跌幅"]) if not work.empty else None,
            "source_type": source_type,
            "source_name": base_source_name,
            "cache_info": {
                "used": True,
                "source": cache_source,
                "cached_at": cached_at,
                "age_seconds": cache_age_seconds,
                "ttl_seconds": self._MARKET_BOARD_CACHE_TTL_SECONDS,
                "fallback_reason": fallback_reason,
            },
        }

    async def fetch_hot_concept_boards(self, top_n: int = 20, min_change_pct: float = 0.0) -> ToolResult:
        """获取热门概念板块（按涨跌幅排序），并返回筛选诊断信息。"""

        async def _fetch():
            direct_error = ""
            fallback_error = ""
            try:
                df = await asyncio.to_thread(self._fetch_eastmoney_board_names, "concept")
                payload = self._normalize_hot_boards(
                    df,
                    top_n=top_n,
                    min_change_pct=min_change_pct,
                    source_type="concept",
                    source_name="东方财富概念板块(直连)",
                )
                await self._cache_market_board_payload("concept", payload)
                return payload
            except Exception as e:
                direct_error = str(e) or e.__class__.__name__

            import akshare as ak

            try:
                df = await asyncio.to_thread(ak.stock_board_concept_name_em)
            except Exception as e:
                akshare_error = str(e) or e.__class__.__name__
                try:
                    df = await asyncio.to_thread(ak.stock_sector_spot, indicator="概念")
                    payload = self._normalize_sina_sector_boards(
                        df,
                        top_n=top_n,
                        min_change_pct=min_change_pct,
                        source_type="sina_concept",
                        source_name="AKShare 新浪概念板块",
                    )
                    await self._cache_market_board_payload("concept", payload)
                    return payload
                except Exception as sina_error_raw:
                    sina_error = str(sina_error_raw) or sina_error_raw.__class__.__name__
                fallback_error = (
                    f"Eastmoney direct failed: {direct_error}; "
                    f"AKShare Eastmoney failed: {akshare_error}; "
                    f"AKShare Sina failed: {sina_error}"
                )
                cached = await self._get_cached_market_board_payload(
                    "concept",
                    top_n=top_n,
                    min_change_pct=min_change_pct,
                    fallback_reason=fallback_error,
                )
                if cached:
                    return cached
                raise RuntimeError(fallback_error) from e
            payload = self._normalize_hot_boards(
                df,
                top_n=top_n,
                min_change_pct=min_change_pct,
                source_type="concept",
                source_name="AKShare 东方财富概念板块",
            )
            await self._cache_market_board_payload("concept", payload)
            return payload

        return await self._safe_execute(_fetch())

    async def fetch_hot_industry_boards(self, top_n: int = 20, min_change_pct: float = 0.0) -> ToolResult:
        """获取热门行业板块（按涨跌幅排序），作为概念板块源的真实降级源。"""

        async def _fetch():
            direct_error = ""
            fallback_error = ""
            try:
                df = await asyncio.to_thread(self._fetch_eastmoney_board_names, "industry")
                payload = self._normalize_hot_boards(
                    df,
                    top_n=top_n,
                    min_change_pct=min_change_pct,
                    source_type="industry",
                    source_name="东方财富行业板块(直连)",
                )
                await self._cache_market_board_payload("industry", payload)
                return payload
            except Exception as e:
                direct_error = str(e) or e.__class__.__name__

            import akshare as ak

            try:
                df = await asyncio.to_thread(ak.stock_board_industry_name_em)
            except Exception as e:
                akshare_error = str(e) or e.__class__.__name__
                try:
                    df = await asyncio.to_thread(ak.stock_sector_spot, indicator="行业")
                    payload = self._normalize_sina_sector_boards(
                        df,
                        top_n=top_n,
                        min_change_pct=min_change_pct,
                        source_type="sina_industry",
                        source_name="AKShare 新浪行业板块",
                    )
                    await self._cache_market_board_payload("industry", payload)
                    return payload
                except Exception as sina_error_raw:
                    sina_error = str(sina_error_raw) or sina_error_raw.__class__.__name__
                fallback_error = (
                    f"Eastmoney direct failed: {direct_error}; "
                    f"AKShare Eastmoney failed: {akshare_error}; "
                    f"AKShare Sina failed: {sina_error}"
                )
                cached = await self._get_cached_market_board_payload(
                    "industry",
                    top_n=top_n,
                    min_change_pct=min_change_pct,
                    fallback_reason=fallback_error,
                )
                if cached:
                    return cached
                raise RuntimeError(fallback_error) from e
            payload = self._normalize_hot_boards(
                df,
                top_n=top_n,
                min_change_pct=min_change_pct,
                source_type="industry",
                source_name="AKShare 东方财富行业板块",
            )
            await self._cache_market_board_payload("industry", payload)
            return payload

        return await self._safe_execute(_fetch())

    async def fetch_concept_constituents(self, symbol: str) -> ToolResult:
        """获取概念板块成分股"""

        async def _fetch():
            import akshare as ak

            df = await asyncio.to_thread(ak.stock_board_concept_cons_em, symbol=symbol)
            return df.to_dict("records")

        return await self._safe_execute(_fetch())

    async def fetch_board_constituents(self, symbol: str, board_type: str = "concept") -> ToolResult:
        """按板块类型获取成分股。

        board_type: concept | industry | sina_concept | sina_industry | local_industry。
        """

        async def _fetch():
            if board_type == "local_industry":
                async with self._session_factory() as session:
                    stmt = select(Stock.code, Stock.name).where(Stock.industry == symbol).order_by(Stock.code)
                    rows = (await session.execute(stmt)).all()
                return [{"代码": code, "名称": name} for code, name in rows]

            if board_type in {"sina_concept", "sina_industry"}:
                import akshare as ak

                df = await asyncio.to_thread(ak.stock_sector_detail, sector=symbol)
                if df is None or df.empty:
                    return []
                return df.to_dict("records")

            board_code = symbol if str(symbol).startswith("BK") else ""
            direct_error = ""
            if board_code:
                try:
                    fid = "f3" if board_type == "industry" else "f12"
                    df = await asyncio.to_thread(self._fetch_eastmoney_constituents, board_code, fid)
                    if df is not None and not df.empty:
                        return df.to_dict("records")
                except Exception as e:
                    direct_error = str(e) or e.__class__.__name__

            import akshare as ak

            try:
                if board_type == "industry":
                    df = await asyncio.to_thread(ak.stock_board_industry_cons_em, symbol=symbol)
                else:
                    df = await asyncio.to_thread(ak.stock_board_concept_cons_em, symbol=symbol)
            except Exception as e:
                akshare_error = str(e) or e.__class__.__name__
                if direct_error:
                    raise RuntimeError(
                        f"Eastmoney direct failed: {direct_error}; AKShare failed: {akshare_error}"
                    ) from e
                raise
            if df is None or df.empty:
                return []
            return df.to_dict("records")

        return await self._safe_execute(_fetch())

    async def fetch_local_industry_groups(self, top_n: int = 20, min_stock_count: int = 3) -> ToolResult:
        """从本地 Stock.industry 构造低置信度候选源。

        该源只反映本地已采集/已标注行业，不代表实时热门程度。
        """

        async def _fetch():
            async with self._session_factory() as session:
                stmt = (
                    select(Stock.code, Stock.name, Stock.industry)
                    .where(Stock.industry.isnot(None))
                    .order_by(Stock.industry, Stock.code)
                )
                rows = (await session.execute(stmt)).all()

            groups: dict[str, list[dict[str, str | None]]] = {}
            for code, name, industry in rows:
                industry_name = (industry or "").strip()
                if not industry_name:
                    continue
                groups.setdefault(industry_name, []).append(
                    {
                        "code": code,
                        "name": name,
                    }
                )

            ordered = sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)
            boards = []
            for industry, stocks in ordered:
                if len(stocks) < min_stock_count:
                    continue
                boards.append(
                    {
                        "板块名称": industry,
                        "涨跌幅": None,
                        "成交额": None,
                        "source_type": "local_industry",
                        "source_name": "本地股票行业分组",
                        "stock_count": len(stocks),
                        "stocks": stocks[:30],
                    }
                )
                if len(boards) >= top_n:
                    break

            return {
                "boards": boards,
                "top_boards": boards,
                "total_count": len(groups),
                "qualified_count": len(boards),
                "min_stock_count": min_stock_count,
                "source_type": "local_industry",
                "source_name": "本地股票行业分组",
            }

        return await self._safe_execute(_fetch())

    async def validate_stock_codes(self, codes: list[str]) -> ToolResult:
        """验证股票代码是否存在于 Stock 表"""

        async def _validate():
            async with self._session_factory() as session:
                stmt = select(Stock.code, Stock.name).where(Stock.code.in_(codes))
                result = await session.execute(stmt)
                found = {row[0]: row[1] for row in result.all()}
            valid = [c for c in codes if c in found]
            invalid = [c for c in codes if c not in found]
            return {"valid": valid, "invalid": invalid, "valid_details": found}

        return await self._safe_execute(_validate())

    async def get_existing_chain_names(self) -> ToolResult:
        """获取已存在的所有产业链名称（去重用）"""

        async def _query():
            from knowledge_graph.neo4j_client import Neo4jClient
            from knowledge_graph.query import KnowledgeGraphQuery

            client = await Neo4jClient.get_instance()
            kgq = KnowledgeGraphQuery(client)
            chains = await kgq.list_chains()
            return [c["name"] for c in chains]

        return await self._safe_execute(_query())

    async def write_chain_to_neo4j(self, chain_data: dict[str, Any]) -> ToolResult:
        """将产业链结构写入 Neo4j（MERGE 幂等）

        chain_data 格式:
        {
            "chain": {"name": "...", "description": "...", "status": "active"},
            "segments": [{"uid": "...", "name": "...", "position": "...", "chain_name": "..."}],
            "companies": [{"code": "...", "name": "...", "industry": "..."}],
            "relationships": [{from_label, from_key_field, from_key_value, to_label, to_key_field, to_key_value, rel_type, properties}]
        }
        """

        async def _write():
            from knowledge_graph.neo4j_client import Neo4jClient

            client = await Neo4jClient.get_instance()

            # 写入 IndustryChain 节点
            chain_node = chain_data["chain"]
            await client.merge_nodes_batch("IndustryChain", [chain_node], ["name"])

            # 写入 Segment 节点
            segments = chain_data.get("segments", [])
            if segments:
                await client.merge_nodes_batch("Segment", segments, ["uid"])

            # 写入 Company 节点（MERGE 不覆盖已有）
            companies = chain_data.get("companies", [])
            if companies:
                await client.merge_nodes_batch("Company", companies, ["code"])

            # 写入关系
            rels = chain_data.get("relationships", [])
            rel_count = 0
            if rels:
                rel_count = await client.merge_relationships_batch(rels)

            return {
                "chain_name": chain_node["name"],
                "segments_count": len(segments),
                "companies_count": len(companies),
                "relationships_count": rel_count,
            }

        return await self._safe_execute(_write())

    async def get_chain_current_companies(self, chain_name: str) -> ToolResult:
        """获取产业链当前所有活跃公司及其 Segment"""

        async def _query():
            from knowledge_graph.neo4j_client import Neo4jClient
            from knowledge_graph.query import KnowledgeGraphQuery

            client = await Neo4jClient.get_instance()
            kgq = KnowledgeGraphQuery(client)
            return await kgq.get_chain_companies(chain_name)

        return await self._safe_execute(_query())

    async def update_chain_incrementally(
        self,
        chain_name: str,
        added_companies: list[dict[str, Any]],
        removed_codes: list[str],
        segment_uid_map: dict[str, str],
    ) -> ToolResult:
        """增量更新产业链：添加新公司，标记移除公司为 inactive"""

        async def _update():
            from datetime import datetime

            from knowledge_graph.neo4j_client import Neo4jClient

            client = await Neo4jClient.get_instance()
            added_count = 0
            deactivated_count = 0
            now_iso = datetime.now().isoformat()

            # 1. 添加新公司节点 + BELONGS_TO 关系
            if added_companies:
                company_nodes = [{"code": c["code"], "name": c.get("name", "")} for c in added_companies]
                await client.merge_nodes_batch("Company", company_nodes, ["code"])

                rels = []
                for comp in added_companies:
                    rels.append({
                        "from_label": "Company",
                        "from_key_field": "code",
                        "from_key_value": comp["code"],
                        "to_label": "Segment",
                        "to_key_field": "uid",
                        "to_key_value": comp["segment_uid"],
                        "rel_type": "BELONGS_TO",
                        "properties": {"_active": True, "_added_at": now_iso},
                    })
                await client.merge_relationships_batch(rels)
                added_count = len(added_companies)

            # 2. 标记移除公司为 inactive
            for code in removed_codes:
                seg_uid = segment_uid_map.get(code)
                if not seg_uid:
                    continue
                await client.set_relationship_properties(
                    "Company", "code", code,
                    "Segment", "uid", seg_uid,
                    "BELONGS_TO",
                    {"_active": False, "_deactivated_at": now_iso},
                )
                deactivated_count += 1

            # 3. 更新链元数据
            await client.merge_nodes_batch("IndustryChain", [{
                "name": chain_name,
                "_last_updated": now_iso,
                "_last_update_added": added_count,
                "_last_update_removed": deactivated_count,
            }], ["name"])

            return {
                "chain_name": chain_name,
                "added": added_count,
                "deactivated": deactivated_count,
            }

        return await self._safe_execute(_update())
