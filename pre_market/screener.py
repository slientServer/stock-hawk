"""盘前选股核心引擎：激进标（个股）+ 稳健标（ETF）"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.llm_client import LLMClient
from common.models import (
    DailyKline,
    EtfDailyKline,
    PreMarketResult,
    SectorCatalyst,
    Stock,
    StockMainFlow,
)
from pre_market.advisor import PreMarketAdvisor
from pre_market.config import PreMarketConfig
from pre_market.scorer import PreMarketScorer

logger = logging.getLogger(__name__)

_ETF_POOL_PATH = Path("data/etf_rotation_pool.json")

# ── 申万二级行业缓存（模块级，24小时有效）────────────────────────────────────
_SW2_CACHE: dict[str, Any] = {"data": {}, "fetched_at": None}


async def _load_sw2_map() -> dict[str, str]:
    """返回 {stock_code: sw2_industry_name}，每日缓存，失败时降级为空字典"""
    cached_at: datetime | None = _SW2_CACHE.get("fetched_at")
    now = datetime.now()
    if cached_at and (now - cached_at).total_seconds() < 86400 and _SW2_CACHE["data"]:
        return _SW2_CACHE["data"]

    try:
        import tushare as ts
        from common.config import get_settings
        token = get_settings().data_source.tushare_token
        if not token:
            return {}

        def _fetch() -> dict[str, str]:
            ts.set_token(token)
            pro = ts.pro_api(token)
            df_l2 = pro.index_classify(level="L2", src="SW2021")
            name_map: dict[str, str] = dict(zip(df_l2["index_code"], df_l2["industry_name"]))
            result: dict[str, str] = {}
            for idx_code in df_l2["index_code"].tolist():
                try:
                    members = pro.index_member(index_code=idx_code, fields="con_code,is_new")
                    if members is not None and not members.empty:
                        for _, row in members[members["is_new"] == "Y"].iterrows():
                            code = str(row["con_code"]).split(".")[0]
                            result[code] = name_map[idx_code]
                    time.sleep(0.12)
                except Exception:
                    pass
            return result

        data = await asyncio.to_thread(_fetch)
        if data:
            _SW2_CACHE["data"] = data
            _SW2_CACHE["fetched_at"] = now
            logger.info("[SW2Cache] 申万二级行业加载完成: %d 只股票", len(data))
        return data
    except Exception as e:
        logger.warning("[SW2Cache] 加载失败（降级忽略）: %s", e)
        return _SW2_CACHE.get("data", {})


def _load_rotation_pool() -> list[dict]:
    if _ETF_POOL_PATH.exists():
        return json.loads(_ETF_POOL_PATH.read_text(encoding="utf-8"))
    return []


def _to_float(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# 板块 → 可能匹配的 industry 关键词（规则降级用）
SECTOR_INDUSTRY_MAP: dict[str, list[str]] = {
    "AI/算力": ["电子", "计算机", "通信", "半导体", "互联网", "软件"],
    "半导体/芯片": ["半导体", "电子", "芯片"],
    "光通信": ["通信", "电子", "光纤"],
    "新能源车": ["汽车", "电气设备", "新能源"],
    "光伏/储能": ["电气设备", "新能源", "光伏"],
    "军工": ["国防军工", "航空航天"],
    "医药/生物": ["医药生物", "生物科技", "医疗器械"],
    "机器人": ["机械设备", "电气设备", "自动化"],
    "消费": ["食品饮料", "纺织服装", "商业贸易", "休闲服务", "轻工制造"],
    "有色金属": ["有色金属", "采掘"],
    "煤炭/能源": ["采掘", "公用事业", "煤炭"],
    "证券/金融": ["非银金融", "银行", "证券"],
    "房地产": ["房地产"],
    "商业航天": ["国防军工", "通信", "电子"],
}


class AggressiveScreener:
    """个股激进标筛选器"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: PreMarketConfig,
        llm_client: LLMClient | None = None,
    ):
        self._session_factory = session_factory
        self.config = config
        self._llm = llm_client or LLMClient()

    async def run(self, trade_date: date, catalysts: list[dict]) -> list[dict]:
        """
        执行激进标筛选。
        catalysts: [{sector_name, catalyst_strength, ...}]
        返回通过LLM催化匹配后的候选列表，含评分字段。
        """
        if not catalysts:
            logger.info("[AggressiveScreener] 无催化板块数据，跳过激进标筛选")
            return []

        # Step 1: 硬性过滤
        candidates = await self._hard_filter(trade_date)
        logger.info(f"[AggressiveScreener] 硬性过滤后候选: {len(candidates)}")
        if not candidates:
            return []

        # Step 2: 批量获取5日涨幅、量比
        codes = [c["code"] for c in candidates]
        history_map = await self._load_7d_history(codes, trade_date)
        main_flow_map = await self._load_main_flow(codes, trade_date)

        enriched = []
        for cand in candidates:
            code = cand["code"]
            hist = history_map.get(code, [])
            metrics = self._calc_metrics(cand, trade_date, hist, main_flow_map.get(code, {}))
            enriched.append({**cand, **metrics})

        # 再次过滤需要历史数据的条件
        filtered = [c for c in enriched if self._pass_secondary_filter(c)]
        logger.info(f"[AggressiveScreener] 二次过滤后候选: {len(filtered)}")
        if not filtered:
            return []

        # 限制最多发给LLM的候选数
        top_candidates = filtered[: self.config.agg_max_candidates]

        # Step 3: LLM催化匹配
        matched = await self._match_catalysts(top_candidates, catalysts)
        logger.info(f"[AggressiveScreener] LLM催化匹配后: {len(matched)}")

        # Step 4: 催化后过热保护（10-15%涨幅需高催化强度）
        matched = self._post_catalyst_filter(matched)
        logger.info(f"[AggressiveScreener] 催化后过热过滤后: {len(matched)}")
        return matched

    async def _hard_filter(self, trade_date: date) -> list[dict]:
        c = self.config
        cap_min = Decimal(str(c.agg_market_cap_min * 1_0000_0000))
        cap_max = Decimal(str(c.agg_market_cap_max * 1_0000_0000))
        earliest_listed = trade_date - timedelta(days=60)

        async with self._session_factory() as session:
            stmt = (
                select(
                    DailyKline.code,
                    DailyKline.close,
                    DailyKline.volume,
                    DailyKline.amount,
                    DailyKline.turnover_rate,
                    Stock.name,
                    Stock.market_cap,
                    Stock.is_st,
                    Stock.listed_date,
                    Stock.industry,
                )
                .join(Stock, DailyKline.code == Stock.code)
                .where(
                    DailyKline.trade_date == trade_date,
                    Stock.is_st != True,  # noqa: E712
                    Stock.market_cap >= cap_min,
                    Stock.market_cap <= cap_max,
                )
            )
            rows = (await session.execute(stmt)).all()

        candidates = []
        for row in rows:
            close = _to_float(row.close)
            if close <= 0:
                continue
            turnover = _to_float(row.turnover_rate)
            if not (c.agg_turnover_min <= turnover <= c.agg_turnover_max):
                continue
            if row.listed_date and row.listed_date > earliest_listed:
                continue
            candidates.append({
                "code": row.code,
                "name": row.name or row.code,
                "industry": row.industry or "",
                "close_price": close,
                "volume": int(row.volume or 0),
                "amount": _to_float(row.amount),
                "turnover_rate": turnover,
                "market_cap": _to_float(row.market_cap),
            })
        return candidates

    async def _load_7d_history(self, codes: list[str], trade_date: date) -> dict[str, list[dict]]:
        """批量获取最近20日K线（含当日），含 high/low 用于振幅和过热判断"""
        history_by_code: dict[str, list[dict]] = {}
        async with self._session_factory() as session:
            for chunk in _chunks(codes):
                rn = func.row_number().over(
                    partition_by=DailyKline.code,
                    order_by=DailyKline.trade_date.desc(),
                ).label("rn")
                ranked = (
                    select(
                        DailyKline.code,
                        DailyKline.trade_date,
                        DailyKline.close,
                        DailyKline.high,
                        DailyKline.low,
                        DailyKline.volume,
                        rn,
                    )
                    .where(DailyKline.code.in_(chunk), DailyKline.trade_date <= trade_date)
                    .subquery()
                )
                stmt = (
                    select(
                        ranked.c.code, ranked.c.trade_date, ranked.c.close,
                        ranked.c.high, ranked.c.low, ranked.c.volume, ranked.c.rn,
                    )
                    .where(ranked.c.rn <= 20)
                    .order_by(ranked.c.code, ranked.c.rn)
                )
                rows = (await session.execute(stmt)).all()
                for row in rows:
                    history_by_code.setdefault(row.code, []).append({
                        "trade_date": row.trade_date,
                        "close": _to_float(row.close),
                        "high": _to_float(row.high),
                        "low": _to_float(row.low),
                        "volume": int(row.volume or 0),
                    })
        return history_by_code

    async def _load_main_flow(self, codes: list[str], trade_date: date) -> dict[str, dict]:
        result: dict[str, dict] = {}
        start = trade_date - timedelta(days=5)
        async with self._session_factory() as session:
            for chunk in _chunks(codes):
                rows = (
                    await session.execute(
                        select(
                            StockMainFlow.code,
                            StockMainFlow.trade_date,
                            StockMainFlow.main_net,
                        ).where(
                            StockMainFlow.code.in_(chunk),
                            StockMainFlow.trade_date >= start,
                            StockMainFlow.trade_date <= trade_date,
                        )
                    )
                ).all()
                for row in rows:
                    if row.code not in result:
                        result[row.code] = {"_dates": []}
                    result[row.code]["_dates"].append((row.trade_date, _to_float(row.main_net)))

        for code, data in result.items():
            dates_sorted = sorted(data["_dates"], key=lambda x: x[0], reverse=True)
            data["main_net_1d"] = dates_sorted[0][1] if dates_sorted else 0.0
            data["main_net_3d"] = sum(v for _, v in dates_sorted[:3])
        return result

    def _calc_metrics(self, cand: dict, trade_date: date, history: list[dict], flow: dict) -> dict:
        close = cand["close_price"]
        # 前一日涨幅
        prev_closes = [h for h in history if h["trade_date"] < trade_date]
        change_1d = 0.0
        if prev_closes:
            prev = prev_closes[0]["close"]
            change_1d = (close - prev) / prev * 100 if prev > 0 else 0.0

        # 近5日涨幅
        closes_5d = [h["close"] for h in history if h["trade_date"] < trade_date][:5]
        change_5d = 0.0
        if closes_5d:
            base = closes_5d[-1]
            change_5d = (close - base) / base * 100 if base > 0 else 0.0

        # 量比（当日量 / 5日均量）
        vols = [h["volume"] for h in prev_closes[:5] if h["volume"] > 0]
        avg_vol = sum(vols) / len(vols) if vols else 0.0
        volume_ratio = cand["volume"] / avg_vol if avg_vol > 0 else 0.0

        # MA5
        all_closes = [h["close"] for h in history if h["close"] > 0][:5]
        ma5 = sum(all_closes) / len(all_closes) if all_closes else close
        above_ma5 = close >= ma5

        # ── 新增：连续涨停天数 ──
        consecutive_limit_ups = 0
        if len(prev_closes) >= 2:
            chg_y = (prev_closes[0]["close"] - prev_closes[1]["close"]) / prev_closes[1]["close"] * 100 if prev_closes[1]["close"] > 0 else 0.0
            if chg_y >= 9.8:
                consecutive_limit_ups = 1
                if len(prev_closes) >= 3:
                    chg_2d = (prev_closes[1]["close"] - prev_closes[2]["close"]) / prev_closes[2]["close"] * 100 if prev_closes[2]["close"] > 0 else 0.0
                    if chg_2d >= 9.8:
                        consecutive_limit_ups = 2

        # ── 新增：高位放量阴线判断 ──
        # 条件：前1日阴线(跌幅>3%) + 前1日量比>2 + 前1日收盘价位于近20日高位区间(>20日高点90%)
        prev_bearish_high_vol = False
        if len(prev_closes) >= 2:
            prev_close_price = prev_closes[0]["close"]
            prev_prev_close = prev_closes[1]["close"]
            prev_day_chg = (prev_close_price - prev_prev_close) / prev_prev_close * 100 if prev_prev_close > 0 else 0.0
            # 前1日量 vs 前2-6日均量
            prev_vol = prev_closes[0]["volume"]
            bg_vols = [h["volume"] for h in prev_closes[1:6] if h["volume"] > 0]
            bg_avg_vol = sum(bg_vols) / len(bg_vols) if bg_vols else 0.0
            prev_vol_ratio = prev_vol / bg_avg_vol if bg_avg_vol > 0 else 0.0
            # 近20日最高价
            high_20d = max((h.get("high", 0) for h in history[:20] if h.get("high", 0) > 0), default=0.0)
            if (
                prev_day_chg <= -3.0
                and prev_vol_ratio >= 2.0
                and high_20d > 0
                and prev_close_price >= high_20d * 0.90
            ):
                prev_bearish_high_vol = True

        return {
            "change_1d": round(change_1d, 4),
            "change_pct_1d": round(change_1d, 4),
            "change_5d": round(change_5d, 4),
            "change_pct_5d": round(change_5d, 4),
            "volume_ratio": round(volume_ratio, 4),
            "above_ma5": above_ma5,
            "main_net_1d": flow.get("main_net_1d", cand.get("main_net_1d", 0.0)),
            "main_net_3d": flow.get("main_net_3d", cand.get("main_net_3d", 0.0)),
            "consecutive_limit_ups": consecutive_limit_ups,
            "prev_bearish_high_vol": prev_bearish_high_vol,
        }

    def _pass_secondary_filter(self, cand: dict) -> bool:
        c = self.config
        change_5d = cand.get("change_pct_5d", 0)
        change_1d = cand.get("change_pct_1d", 0)
        vr = cand.get("volume_ratio", 0)
        main_net_1d = cand.get("main_net_1d", 0)
        main_3d = cand.get("main_net_3d", 0)
        main_net_1d_min_yuan = c.agg_main_net_1d_min * 10000

        # ── 硬排除：涨幅过热（>15% 直接排除，赔率差）──
        if change_5d > c.agg_5d_hot_exclude:
            return False
        # ── 硬排除：连续涨停 ≥ 2 天（接力风险高）──
        if cand.get("consecutive_limit_ups", 0) >= 2:
            return False
        # ── 硬排除：高位放量阴线（前1日放量跌超3% + 位于近20日高位）──
        if cand.get("prev_bearish_high_vol", False):
            return False

        return (
            c.agg_5d_min <= change_5d <= c.agg_5d_max
            and c.agg_1d_min <= change_1d <= c.agg_1d_max
            and vr >= c.agg_volume_ratio_min
            and cand.get("above_ma5", False)
            and main_net_1d >= main_net_1d_min_yuan
            and main_3d >= 0
        )

    def _post_catalyst_filter(self, candidates: list[dict]) -> list[dict]:
        """催化匹配后的过热保护：5日涨幅 10-15% 区间需要催化强度达标"""
        result = []
        c = self.config
        for item in candidates:
            change_5d = item.get("change_pct_5d", 0)
            strength = item.get("catalyst_strength", 0)
            if change_5d > c.agg_5d_hot_need_catalyst:
                if strength < c.agg_hot_catalyst_min:
                    logger.info(
                        "[AggressiveScreener] 过热降级排除: %s 5d=%.1f%% strength=%d (需>=%d)",
                        item["code"], change_5d, strength, c.agg_hot_catalyst_min,
                    )
                    continue
            result.append(item)
        return result

    async def _match_catalysts(self, candidates: list[dict], catalysts: list[dict]) -> list[dict]:
        """LLM一次批量判断每只候选股是否属于有催化的板块，降级用关键词匹配"""
        if self._llm.is_available():
            try:
                return await self._match_with_llm(candidates, catalysts)
            except Exception as e:
                logger.warning(f"[AggressiveScreener] LLM催化匹配失败，降级规则匹配: {e}")
        return self._match_with_rules(candidates, catalysts)

    async def _match_with_llm(self, candidates: list[dict], catalysts: list[dict]) -> list[dict]:
        # 加载申万二级行业（缓存，失败降级为空）
        sw2_map = await _load_sw2_map()

        catalyst_list = [{"sector": c["sector_name"], "strength": c["catalyst_strength"]} for c in catalysts]
        stock_list = []
        for c in candidates:
            code = c["code"]
            # 申万二级行业优先，其次 stock_basic 中的行业
            industry = sw2_map.get(code) or c.get("industry") or ""
            stock_list.append({
                "code": code,
                "name": c["name"],
                "industry": industry,
                "change_5d": round(c.get("change_pct_5d", 0), 2),
                "change_1d": round(c.get("change_pct_1d", 0), 2),
                "volume_ratio": round(c.get("volume_ratio", 0), 2),
                "main_net_3d_wan": round(c.get("main_net_3d", 0) / 10000, 0),
            })
        messages = [
            {
                "role": "system",
                "content": (
                    "你是A股行业专家。根据候选股票的申万二级行业及量化指标，"
                    "判断其是否属于以下催化板块之一。只输出JSON，不要解释。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"催化板块：{json.dumps(catalyst_list, ensure_ascii=False)}\n"
                    f"候选股票：{json.dumps(stock_list, ensure_ascii=False)}\n\n"
                    "字段说明：industry=申万二级行业, change_5d=近5日涨幅%, "
                    "volume_ratio=量比, main_net_3d_wan=近3日主力净流入(万元)\n"
                    '输出格式：{"matches": [{"code": "代码", "catalyst_sector": "板块名", "catalyst_strength": 强度数字}]}\n'
                    "只列出匹配成功的股票，未匹配的不要出现在列表中。"
                ),
            },
        ]
        result = await self._llm.chat_json(messages, temperature=0.1, max_tokens=2048)
        matches_map = {
            m["code"]: m for m in result.get("matches", []) if "code" in m
        }
        matched = []
        for cand in candidates:
            if cand["code"] in matches_map:
                m = matches_map[cand["code"]]
                matched.append({
                    **cand,
                    "catalyst_sector": m.get("catalyst_sector", ""),
                    "catalyst_strength": int(m.get("catalyst_strength", 3)),
                })
        return matched

    def _match_with_rules(self, candidates: list[dict], catalysts: list[dict]) -> list[dict]:
        matched = []
        catalyst_industries: dict[str, int] = {}
        for cat in catalysts:
            sector = cat["sector_name"]
            strength = cat["catalyst_strength"]
            for kw in SECTOR_INDUSTRY_MAP.get(sector, []):
                catalyst_industries[kw.lower()] = max(catalyst_industries.get(kw.lower(), 0), strength)

        for cand in candidates:
            industry = (cand.get("industry") or "").lower()
            best_strength = 0
            best_sector = ""
            for kw, strength in catalyst_industries.items():
                if kw in industry and strength > best_strength:
                    best_strength = strength
                    # find sector name
                    for cat in catalysts:
                        if kw in [k.lower() for k in SECTOR_INDUSTRY_MAP.get(cat["sector_name"], [])]:
                            best_sector = cat["sector_name"]
            if best_strength >= self.config.agg_catalyst_strength_min:
                matched.append({
                    **cand,
                    "catalyst_sector": best_sector,
                    "catalyst_strength": best_strength,
                })
        return matched


class StableScreener:
    """ETF稳健标筛选器"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: PreMarketConfig,
    ):
        self._session_factory = session_factory
        self.config = config

    async def run(self, trade_date: date) -> list[dict]:
        pool = _load_rotation_pool()
        if not pool:
            logger.warning("[StableScreener] ETF轮动池为空")
            return []

        codes = [e["code"] for e in pool]
        etf_meta = {e["code"]: e for e in pool}

        history_map = await self._load_25d_history(codes, trade_date)
        candidates = []
        for code in codes:
            hist = history_map.get(code, [])
            if len(hist) < 6:
                continue
            metrics = self._calc_etf_metrics(hist, trade_date)
            if metrics is None:
                continue
            if not self._pass_filter(metrics):
                continue
            meta = etf_meta[code]
            candidates.append({
                "code": code,
                "name": meta.get("name", code),
                "close_price": metrics["close"],
                "change_pct_3d": metrics["change_3d"],
                "ma5_direction": metrics["ma5_direction"],
                "ma5_deviation": metrics["ma5_deviation"],
                "amount_ratio": metrics["amount_ratio"],
                "amount_ratio_source": metrics.get("amount_ratio_source"),
                "avg_amplitude": metrics["avg_amplitude"],
                "score_detail": {
                    "liquidity_ratio_source": metrics.get("amount_ratio_source"),
                },
                "group": meta.get("group", ""),
                "alias": meta.get("alias", ""),
            })

        # 按近3日涨幅排序，取前N
        candidates.sort(key=lambda x: x["change_pct_3d"], reverse=True)
        return candidates[: self.config.etf_top_n]

    async def _load_25d_history(self, codes: list[str], trade_date: date) -> dict[str, list[dict]]:
        history_by_code: dict[str, list[dict]] = {}
        async with self._session_factory() as session:
            for chunk in _chunks(codes, size=50):
                rn = func.row_number().over(
                    partition_by=EtfDailyKline.code,
                    order_by=EtfDailyKline.trade_date.desc(),
                ).label("rn")
                ranked = (
                    select(
                        EtfDailyKline.code,
                        EtfDailyKline.trade_date,
                        EtfDailyKline.close,
                        EtfDailyKline.volume,
                        EtfDailyKline.amount,
                        EtfDailyKline.high,
                        EtfDailyKline.low,
                        rn,
                    )
                    .where(EtfDailyKline.code.in_(chunk), EtfDailyKline.trade_date <= trade_date)
                    .subquery()
                )
                stmt = (
                    select(
                        ranked.c.code, ranked.c.trade_date, ranked.c.close,
                        ranked.c.volume, ranked.c.amount, ranked.c.high, ranked.c.low, ranked.c.rn,
                    )
                    .where(ranked.c.rn <= 25)
                    .order_by(ranked.c.code, ranked.c.rn)
                )
                rows = (await session.execute(stmt)).all()
                for row in rows:
                    history_by_code.setdefault(row.code, []).append({
                        "trade_date": row.trade_date,
                        "close": _to_float(row.close),
                        "volume": int(row.volume or 0),
                        "amount": _to_float(row.amount),
                        "high": _to_float(row.high),
                        "low": _to_float(row.low),
                    })
        return history_by_code

    def _calc_etf_metrics(self, history: list[dict], trade_date: date) -> dict | None:
        # history 已按 rn 排序（rn=1 是最新）
        current = history[0]
        close = current["close"]
        if close <= 0:
            return None

        # MA5（最新5日含当日）
        closes = [h["close"] for h in history[:5] if h["close"] > 0]
        if len(closes) < 5:
            return None
        ma5_now = sum(closes) / len(closes)

        # 5日前MA5
        closes_5_ago = [h["close"] for h in history[5:10] if h["close"] > 0]
        if len(closes_5_ago) >= 5:
            ma5_5ago = sum(closes_5_ago) / len(closes_5_ago)
        else:
            ma5_5ago = ma5_now

        if ma5_now > ma5_5ago * 1.001:
            ma5_direction = "up"
        elif ma5_now < ma5_5ago * 0.999:
            ma5_direction = "down"
        else:
            ma5_direction = "flat"

        # MA5偏离度（%）
        ma5_deviation = (close - ma5_now) / ma5_now * 100 if ma5_now > 0 else 0.0

        # 近3日涨幅
        close_3d_ago = history[3]["close"] if len(history) > 3 else close
        change_3d = (close - close_3d_ago) / close_3d_ago * 100 if close_3d_ago > 0 else 0.0

        # 成交额比（当日 / 20日均额）。部分 ETF 源缺 amount，降级使用真实成交量比。
        amounts = [h["amount"] for h in history[:20] if h["amount"] > 0]
        avg_amount_20d = sum(amounts) / len(amounts) if amounts else 0.0
        amount_ratio = current["amount"] / avg_amount_20d if current["amount"] > 0 and avg_amount_20d > 0 else 0.0
        amount_ratio_source = "amount"
        if amount_ratio <= 0:
            volumes = [h["volume"] for h in history[:20] if h["volume"] > 0]
            avg_volume_20d = sum(volumes) / len(volumes) if volumes else 0.0
            amount_ratio = current["volume"] / avg_volume_20d if current["volume"] > 0 and avg_volume_20d > 0 else 0.0
            amount_ratio_source = "volume"

        # 近20日日均振幅
        amplitudes = []
        for h in history[:20]:
            if h["high"] > 0 and h["low"] > 0 and h["close"] > 0:
                prev_close = h["close"]  # 用自身收盘近似（已是当日收盘）
                amp = (h["high"] - h["low"]) / h["close"] * 100
                amplitudes.append(amp)
        avg_amplitude = sum(amplitudes) / len(amplitudes) if amplitudes else 0.0

        return {
            "close": close,
            "ma5_direction": ma5_direction,
            "ma5_deviation": round(ma5_deviation, 4),
            "change_3d": round(change_3d, 4),
            "amount_ratio": round(amount_ratio, 4),
            "amount_ratio_source": amount_ratio_source,
            "avg_amplitude": round(avg_amplitude, 4),
        }

    def _pass_filter(self, metrics: dict) -> bool:
        c = self.config
        return (
            metrics["ma5_direction"] == "up"
            and 0 < metrics["ma5_deviation"] <= c.etf_ma5_deviation_max
            and metrics["amount_ratio"] >= c.etf_amount_ratio_min
            and c.etf_avg_amplitude_min <= metrics["avg_amplitude"] <= c.etf_avg_amplitude_max
        )


class FallbackAggressiveScreener:
    """无催化数据时的纯技术面激进标筛选（降级方案）"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: PreMarketConfig,
        llm_client: LLMClient | None = None,
    ):
        self._agg = AggressiveScreener(session_factory, config, llm_client)

    async def run(self, trade_date: date) -> list[dict]:
        candidates = await self._agg._hard_filter(trade_date)
        logger.info(f"[FallbackAggressiveScreener] 硬性过滤后候选: {len(candidates)}")
        if not candidates:
            return []

        codes = [c["code"] for c in candidates]
        history_map = await self._agg._load_7d_history(codes, trade_date)
        main_flow_map = await self._agg._load_main_flow(codes, trade_date)

        enriched = []
        for cand in candidates:
            code = cand["code"]
            hist = history_map.get(code, [])
            metrics = self._agg._calc_metrics(cand, trade_date, hist, main_flow_map.get(code, {}))
            enriched.append({**cand, **metrics})

        filtered = [c for c in enriched if self._agg._pass_secondary_filter(c)]
        logger.info(f"[FallbackAggressiveScreener] 二次过滤后候选: {len(filtered)}")

        for c in filtered:
            c["catalyst_sector"] = "纯技术面"
            c["catalyst_strength"] = 0
        return filtered


class StableStockScreener:
    """个股稳健标筛选器（低波动、持续主力流入）"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: PreMarketConfig,
    ):
        self._session_factory = session_factory
        self.config = config

    async def run(self, trade_date: date) -> list[dict]:
        candidates = await self._hard_filter(trade_date)
        logger.info(f"[StableStockScreener] 硬性过滤后候选: {len(candidates)}")
        if not candidates:
            return []

        codes = [c["code"] for c in candidates]
        history_map = await self._load_20d_history(codes, trade_date)
        main_flow_map = await self._load_main_flow(codes, trade_date)

        enriched = []
        for cand in candidates:
            code = cand["code"]
            hist = history_map.get(code, [])
            metrics = self._calc_metrics(cand, trade_date, hist, main_flow_map.get(code, {}))
            enriched.append({**cand, **metrics})

        filtered = [c for c in enriched if self._pass_stable_filter(c)]
        logger.info(f"[StableStockScreener] 二次过滤后候选: {len(filtered)}")
        return filtered

    async def _hard_filter(self, trade_date: date) -> list[dict]:
        c = self.config
        cap_min = Decimal(str(c.stable_stock_market_cap_min * 1_0000_0000))
        cap_max = Decimal(str(c.stable_stock_market_cap_max * 1_0000_0000))
        earliest_listed = trade_date - timedelta(days=60)

        async with self._session_factory() as session:
            stmt = (
                select(
                    DailyKline.code,
                    DailyKline.close,
                    DailyKline.volume,
                    DailyKline.amount,
                    DailyKline.turnover_rate,
                    Stock.name,
                    Stock.market_cap,
                    Stock.is_st,
                    Stock.listed_date,
                    Stock.industry,
                )
                .join(Stock, DailyKline.code == Stock.code)
                .where(
                    DailyKline.trade_date == trade_date,
                    Stock.is_st != True,  # noqa: E712
                    Stock.market_cap >= cap_min,
                    Stock.market_cap <= cap_max,
                )
            )
            rows = (await session.execute(stmt)).all()

        candidates = []
        for row in rows:
            close = _to_float(row.close)
            if close <= 0:
                continue
            turnover = _to_float(row.turnover_rate)
            if not (c.stable_stock_turnover_min <= turnover <= c.stable_stock_turnover_max):
                continue
            if row.listed_date and row.listed_date > earliest_listed:
                continue
            candidates.append({
                "code": row.code,
                "name": row.name or row.code,
                "industry": row.industry or "",
                "close_price": close,
                "volume": int(row.volume or 0),
                "amount": _to_float(row.amount),
                "turnover_rate": turnover,
                "market_cap": _to_float(row.market_cap),
            })
        return candidates

    async def _load_20d_history(self, codes: list[str], trade_date: date) -> dict[str, list[dict]]:
        """批量获取最近20日K线（含当日，用于振幅计算）"""
        history_by_code: dict[str, list[dict]] = {}
        async with self._session_factory() as session:
            for chunk in _chunks(codes):
                rn = func.row_number().over(
                    partition_by=DailyKline.code,
                    order_by=DailyKline.trade_date.desc(),
                ).label("rn")
                ranked = (
                    select(
                        DailyKline.code,
                        DailyKline.trade_date,
                        DailyKline.close,
                        DailyKline.high,
                        DailyKline.low,
                        DailyKline.volume,
                        rn,
                    )
                    .where(DailyKline.code.in_(chunk), DailyKline.trade_date <= trade_date)
                    .subquery()
                )
                stmt = (
                    select(
                        ranked.c.code,
                        ranked.c.trade_date,
                        ranked.c.close,
                        ranked.c.high,
                        ranked.c.low,
                        ranked.c.volume,
                        ranked.c.rn,
                    )
                    .where(ranked.c.rn <= 20)
                    .order_by(ranked.c.code, ranked.c.rn)
                )
                rows = (await session.execute(stmt)).all()
                for row in rows:
                    history_by_code.setdefault(row.code, []).append({
                        "trade_date": row.trade_date,
                        "close": _to_float(row.close),
                        "high": _to_float(row.high),
                        "low": _to_float(row.low),
                        "volume": int(row.volume or 0),
                    })
        return history_by_code

    async def _load_main_flow(self, codes: list[str], trade_date: date) -> dict[str, dict]:
        result: dict[str, dict] = {}
        start = trade_date - timedelta(days=5)
        async with self._session_factory() as session:
            for chunk in _chunks(codes):
                rows = (
                    await session.execute(
                        select(
                            StockMainFlow.code,
                            StockMainFlow.trade_date,
                            StockMainFlow.main_net,
                        ).where(
                            StockMainFlow.code.in_(chunk),
                            StockMainFlow.trade_date >= start,
                            StockMainFlow.trade_date <= trade_date,
                        )
                    )
                ).all()
                for row in rows:
                    if row.code not in result:
                        result[row.code] = {"_dates": []}
                    result[row.code]["_dates"].append((row.trade_date, _to_float(row.main_net)))

        for code, data in result.items():
            dates_sorted = sorted(data["_dates"], key=lambda x: x[0], reverse=True)
            data["main_net_1d"] = dates_sorted[0][1] if dates_sorted else 0.0
            data["main_net_3d"] = sum(v for _, v in dates_sorted[:3])
        return result

    def _calc_metrics(self, cand: dict, trade_date: date, history: list[dict], flow: dict) -> dict:
        close = cand["close_price"]

        # 历史数据（rn=1 是当日，rn=2 起是前N日）
        prev_history = [h for h in history if h["trade_date"] < trade_date]

        # 前1日涨幅
        change_1d = 0.0
        if prev_history:
            prev = prev_history[0]["close"]
            change_1d = (close - prev) / prev * 100 if prev > 0 else 0.0

        # 近5日涨幅
        closes_5d = [h["close"] for h in prev_history[:5]]
        change_5d = 0.0
        if closes_5d:
            base = closes_5d[-1]
            change_5d = (close - base) / base * 100 if base > 0 else 0.0

        # 量比（当日量 / 5日均量）
        vols = [h["volume"] for h in prev_history[:5] if h["volume"] > 0]
        avg_vol = sum(vols) / len(vols) if vols else 0.0
        volume_ratio = cand["volume"] / avg_vol if avg_vol > 0 else 0.0

        # MA5（含当日）
        all_closes = [h["close"] for h in history[:5] if h["close"] > 0]
        ma5 = sum(all_closes) / len(all_closes) if all_closes else close
        above_ma5 = close >= ma5
        ma5_deviation = (close - ma5) / ma5 * 100 if ma5 > 0 else 0.0

        # 近20日日均振幅
        amplitudes = []
        for h in history[:20]:
            if h["high"] > 0 and h["low"] > 0 and h["close"] > 0:
                amplitudes.append((h["high"] - h["low"]) / h["close"] * 100)
        avg_amplitude = sum(amplitudes) / len(amplitudes) if amplitudes else 0.0

        return {
            "change_1d": round(change_1d, 4),
            "change_pct_1d": round(change_1d, 4),
            "change_5d": round(change_5d, 4),
            "change_pct_5d": round(change_5d, 4),
            "volume_ratio": round(volume_ratio, 4),
            "above_ma5": above_ma5,
            "ma5_deviation": round(ma5_deviation, 4),
            "avg_amplitude": round(avg_amplitude, 4),
            "main_net_1d": flow.get("main_net_1d", 0.0),
            "main_net_3d": flow.get("main_net_3d", 0.0),
        }

    def _pass_stable_filter(self, cand: dict) -> bool:
        c = self.config
        return (
            c.stable_stock_5d_min <= cand.get("change_5d", 0) <= c.stable_stock_5d_max
            and c.stable_stock_1d_min <= cand.get("change_1d", 0) <= c.stable_stock_1d_max
            and c.stable_stock_volume_ratio_min <= cand.get("volume_ratio", 0) <= c.stable_stock_volume_ratio_max
            and cand.get("above_ma5", False)
            and cand.get("avg_amplitude", 99.0) <= c.stable_stock_amplitude_max
            and cand.get("main_net_3d", 0) >= c.stable_stock_main_net_3d_min
        )


class PreMarketScreener:
    """统一入口：执行激进标 + 稳健标筛选并持久化结果"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: PreMarketConfig | None = None,
        llm_client: LLMClient | None = None,
    ):
        self._session_factory = session_factory
        self.config = config or PreMarketConfig.load()
        self._llm = llm_client or LLMClient()
        self._scorer = PreMarketScorer(self.config)
        self._advisor = PreMarketAdvisor(self.config)
        self._agg = AggressiveScreener(session_factory, self.config, self._llm)
        self._fallback_agg = FallbackAggressiveScreener(session_factory, self.config, self._llm)
        self._stable = StableScreener(session_factory, self.config)
        self._stable_stock = StableStockScreener(session_factory, self.config)

    async def run(
        self,
        trade_date: date,
        catalysts: list[dict],
        *,
        persist: bool = True,
    ) -> dict:
        """
        执行完整筛选流程。
        返回 {"aggressive": [...], "fallback_main": [...], "fallback_backup": [...], "stable": [...]}
        """
        # --- 激进标（正常流程）---
        agg_raw = await self._agg.run(trade_date, catalysts)
        agg_scored = self._scorer.score_aggressive(agg_raw)

        # 行业集中度去重：同一催化板块最多 agg_max_per_sector 只
        if self.config.agg_max_per_sector > 0 and agg_scored:
            sector_count: dict[str, int] = {}
            deduped: list[dict] = []
            for item in agg_scored:  # 已按评分降序排列，优先保留高分
                sector = item.get("catalyst_sector", "") or ""
                cnt = sector_count.get(sector, 0)
                if cnt < self.config.agg_max_per_sector:
                    deduped.append(item)
                    sector_count[sector] = cnt + 1
            if len(deduped) < len(agg_scored):
                logger.info(
                    "[PreMarketScreener] 行业集中度去重: %d→%d (max_per_sector=%d)",
                    len(agg_scored), len(deduped), self.config.agg_max_per_sector,
                )
                agg_scored = deduped
                for i, item in enumerate(agg_scored, 1):
                    item["rank"] = i

        for item in agg_scored:
            item.update(self._advisor.generate_aggressive(item))

        # 最低入选分过滤：信号不足则不推荐（宁可触发降级也不推低质量标）
        before = len(agg_scored)
        agg_scored = [x for x in agg_scored if x.get("score", 0) >= self.config.agg_score_min]
        if len(agg_scored) < before:
            logger.info(
                "[PreMarketScreener] 激进标分数过滤: %d→%d (min_score=%.0f)",
                before, len(agg_scored), self.config.agg_score_min,
            )

        # --- 激进标降级：正常流程无结果时启用纯技术面筛选 ---
        fallback_main: list[dict] = []
        fallback_backup: list[dict] = []
        if not agg_scored:
            logger.info("[PreMarketScreener] 激进标为空，启动纯技术面降级筛选")
            fallback_raw = await self._fallback_agg.run(trade_date)
            fallback_scored = self._scorer.score_aggressive(fallback_raw)
            for item in fallback_scored:
                item.update(self._advisor.generate_aggressive(item))
            if fallback_scored:
                fallback_main = [fallback_scored[0]]
                fallback_backup = fallback_scored[1:3]
                # 重新标记 rank
                fallback_main[0]["rank"] = 1
                for i, item in enumerate(fallback_backup, 2):
                    item["rank"] = i
            logger.info(f"[PreMarketScreener] 降级结果: 主推{len(fallback_main)}只, 备用{len(fallback_backup)}只")

        # --- 稳健标（ETF + 个股并行）---
        stable_etf_raw = await self._stable.run(trade_date)
        stable_etf_scored = self._scorer.score_stable(stable_etf_raw)
        for item in stable_etf_scored:
            item.update(self._advisor.generate_stable(item))
            item["result_type_hint"] = "stable"

        stable_stock_raw = await self._stable_stock.run(trade_date)
        stable_stock_scored = self._scorer.score_stable_stock(stable_stock_raw)
        for item in stable_stock_scored:
            item.update(self._advisor.generate_stable_stock(item))
            item["result_type_hint"] = "stable_stock"

        # 合并稳健标，按评分排序取 Top N
        all_stable = stable_etf_scored + stable_stock_scored
        all_stable.sort(key=lambda x: x.get("score", 0), reverse=True)
        # 最低入选分过滤
        all_stable = [x for x in all_stable if x.get("score", 0) >= self.config.stable_score_min]
        stable_final = all_stable[: self.config.etf_top_n]
        for i, item in enumerate(stable_final, 1):
            item["rank"] = i

        if persist:
            await self._persist(trade_date, agg_scored, fallback_main, fallback_backup, stable_final)

        return {
            "aggressive": agg_scored,
            "fallback_main": fallback_main,
            "fallback_backup": fallback_backup,
            "stable": stable_final,
        }

    async def _persist(
        self,
        trade_date: date,
        aggressive: list[dict],
        fallback_main: list[dict],
        fallback_backup: list[dict],
        stable: list[dict],
    ) -> None:
        async with self._session_factory() as session:
            # 幂等：清除当日旧结果
            await session.execute(
                delete(PreMarketResult).where(PreMarketResult.trade_date == trade_date)
            )

            def _add_aggressive(item: dict, result_type: str) -> None:
                session.add(PreMarketResult(
                    trade_date=trade_date,
                    result_type=result_type,
                    code=item["code"],
                    name=item.get("name"),
                    close_price=Decimal(str(item["close_price"])),
                    change_pct_5d=Decimal(str(item.get("change_pct_5d", 0))),
                    change_pct_1d=Decimal(str(item.get("change_pct_1d", 0))),
                    turnover_rate=Decimal(str(item.get("turnover_rate", 0))),
                    volume_ratio=Decimal(str(item.get("volume_ratio", 0))),
                    market_cap=Decimal(str(item.get("market_cap", 0))),
                    main_net_1d=Decimal(str(item.get("main_net_1d", 0))),
                    main_net_3d=Decimal(str(item.get("main_net_3d", 0))),
                    above_ma5=item.get("above_ma5"),
                    catalyst_sector=item.get("catalyst_sector"),
                    catalyst_strength=item.get("catalyst_strength"),
                    score=Decimal(str(item.get("score", 0))),
                    score_detail=item.get("score_detail"),
                    rank=item.get("rank"),
                    target_price=Decimal(str(item.get("target_price", 0))),
                    stop_loss_price=Decimal(str(item.get("stop_loss_price", 0))),
                    suggestion=item.get("suggestion"),
                    exit_type="pending",
                ))

            for item in aggressive:
                _add_aggressive(item, "aggressive")
            for item in fallback_main:
                _add_aggressive(item, "aggressive_main")
            for item in fallback_backup:
                _add_aggressive(item, "aggressive_backup")

            for item in stable:
                rtype = item.get("result_type_hint", "stable")
                if rtype == "stable_stock":
                    session.add(PreMarketResult(
                        trade_date=trade_date,
                        result_type="stable_stock",
                        code=item["code"],
                        name=item.get("name"),
                        close_price=Decimal(str(item["close_price"])),
                        change_pct_5d=Decimal(str(item.get("change_pct_5d", 0))),
                        change_pct_1d=Decimal(str(item.get("change_pct_1d", 0))),
                        turnover_rate=Decimal(str(item.get("turnover_rate", 0))),
                        volume_ratio=Decimal(str(item.get("volume_ratio", 0))),
                        market_cap=Decimal(str(item.get("market_cap", 0))),
                        main_net_1d=Decimal(str(item.get("main_net_1d", 0))),
                        main_net_3d=Decimal(str(item.get("main_net_3d", 0))),
                        above_ma5=item.get("above_ma5"),
                        ma5_deviation=Decimal(str(item.get("ma5_deviation", 0))),
                        avg_amplitude=Decimal(str(item.get("avg_amplitude", 0))),
                        score=Decimal(str(item.get("score", 0))),
                        score_detail=item.get("score_detail"),
                        rank=item.get("rank"),
                        target_price=Decimal(str(item.get("target_price", 0))),
                        stop_loss_price=Decimal(str(item.get("stop_loss_price", 0))),
                        suggestion=item.get("suggestion"),
                        exit_type="pending",
                    ))
                else:
                    session.add(PreMarketResult(
                        trade_date=trade_date,
                        result_type="stable",
                        code=item["code"],
                        name=item.get("name"),
                        close_price=Decimal(str(item["close_price"])),
                        change_pct_3d=Decimal(str(item.get("change_pct_3d", 0))),
                        ma5_direction=item.get("ma5_direction"),
                        ma5_deviation=Decimal(str(item.get("ma5_deviation", 0))),
                        amount_ratio=Decimal(str(item.get("amount_ratio", 0))),
                        avg_amplitude=Decimal(str(item.get("avg_amplitude", 0))),
                        score=Decimal(str(item.get("score", 0))),
                        score_detail=item.get("score_detail"),
                        rank=item.get("rank"),
                        target_price=Decimal(str(item.get("target_price", 0))),
                        stop_loss_price=Decimal(str(item.get("stop_loss_price", 0))),
                        suggestion=item.get("suggestion"),
                        exit_type="pending",
                    ))
            await session.commit()


def _chunks(items: list, size: int = 800):
    for i in range(0, len(items), size):
        yield items[i:i + size]
