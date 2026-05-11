"""尾盘选股核心引擎"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.models import DailyKline, EodScreenResult, Stock, StockMainFlow
from eod_screener.advisor import OperationAdvisor
from eod_screener.config import EODScreenerConfig
from eod_screener.scorer import EODScorer

logger = logging.getLogger(__name__)


class EODScreener:
    """杨永兴尾盘选股法引擎"""

    FULL_MARKET_COVERAGE_PCT = 95.0

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        config: EODScreenerConfig | None = None,
    ):
        self._session_factory = session_factory
        self.config = config or EODScreenerConfig.load()
        self._scorer = EODScorer(self.config)
        self._advisor = OperationAdvisor(self.config)

    async def run(
        self,
        trade_date: date | None = None,
        *,
        persist: bool = True,
        include_backtest: bool = True,
        codes: list[str] | None = None,
        data_mode: str = "stored",
        quote_source: str | None = None,
        quote_time: datetime | str | None = None,
    ) -> list[dict]:
        """执行选股流程"""
        trade_date = await self._resolve_trade_date(trade_date)
        if trade_date is None:
            logger.info("尾盘选股跳过: 无可用K线交易日")
            return []
        logger.info(f"尾盘选股开始: {trade_date}")

        # Step 1: 获取当日有K线的候选股票
        candidates = await self._get_candidates(trade_date, codes=codes)
        if not candidates:
            logger.info("当日无候选股票数据")
            if persist:
                await self._clear_results(trade_date)
            return []

        # Step 2: 批量预取历史数据后检查选股条件
        passed, _, _ = await self._evaluate_candidates(candidates, trade_date)

        logger.info(f"通过筛选: {len(passed)}/{len(candidates)}")

        if not passed:
            if persist:
                await self._clear_results(trade_date)
            return []

        results = await self._finalize_results(
            passed,
            trade_date,
            persist=persist,
            include_backtest=include_backtest,
            data_mode=data_mode,
            quote_source=quote_source,
            quote_time=quote_time,
        )

        logger.info(f"尾盘选股完成: 选出 {len(results)} 只")
        return results

    async def run_with_diagnostics(
        self,
        trade_date: date | None = None,
        *,
        persist: bool = True,
        require_full_market: bool = True,
        include_backtest: bool = True,
        data_mode: str = "stored",
        quote_source: str | None = None,
        quote_time: datetime | str | None = None,
    ) -> dict:
        """执行选股并返回用户可读的过滤诊断。"""
        requested_date = trade_date
        resolved_date = await self._resolve_trade_date(trade_date)
        if resolved_date is None:
            return {
                "status": "blocked",
                "requested_trade_date": str(requested_date) if requested_date else None,
                "trade_date": None,
                "count": 0,
                "results": [],
                "diagnostics": {
                    "candidate_count": 0,
                    "passed_count": 0,
                    "filter_reasons": {},
                    "data_gaps": ["当前没有可用K线数据，无法执行尾盘选股"],
                    "sample_failures": [],
                },
            }

        diagnostics, passed = await self._diagnose_with_passed(resolved_date)
        if require_full_market and not diagnostics["market_coverage"]["is_full_market"]:
            diagnostics["action_required"] = "collect_full_market"
            diagnostics["data_gaps"].insert(0, "行情覆盖率不足，需先执行全市场日行情采集后再运行尾盘选股")
            return {
                "status": "blocked",
                "requested_trade_date": str(requested_date) if requested_date else None,
                "trade_date": str(resolved_date),
                "count": 0,
                "results": [],
                "diagnostics": diagnostics,
            }
        results = await self._finalize_results(
            passed,
            resolved_date,
            persist=persist,
            include_backtest=include_backtest,
            data_mode=data_mode,
            quote_source=quote_source,
            quote_time=quote_time,
        )
        diagnostics["passed_count"] = len(results)
        return {
            "status": "completed",
            "requested_trade_date": str(requested_date) if requested_date else None,
            "trade_date": str(resolved_date),
            "count": len(results),
            "results": results,
            "diagnostics": diagnostics,
        }

    async def diagnose(self, trade_date: date) -> dict:
        """统计候选池规模和各过滤条件失败次数，用于解释空结果。"""
        diagnostics, _ = await self._diagnose_with_passed(trade_date)
        return diagnostics

    async def _diagnose_with_passed(self, trade_date: date) -> tuple[dict, list[dict]]:
        """统计诊断信息，并返回已通过基础策略过滤的候选。"""
        market_coverage = await self._market_coverage(trade_date)
        candidates = await self._get_candidates(trade_date)
        passed, reasons, samples = await self._evaluate_candidates(candidates, trade_date)

        data_gaps: list[str] = []
        if not candidates:
            data_gaps.append(f"{trade_date} 无满足基础过滤条件的K线候选股票")
        elif not passed:
            data_gaps.append("当前配置过严或行情特征不匹配，全部候选被过滤")
        if not market_coverage["is_full_market"]:
            total = market_coverage["total_stock_count"]
            shortages = [f"K线 {market_coverage['kline_stock_count']}/{total}"]
            fields = market_coverage.get("field_coverage") or {}
            for key, label in (
                ("volume_count", "成交量"),
                ("amount_count", "成交额"),
                ("turnover_rate_count", "换手率"),
            ):
                count = fields.get(key) or 0
                field_pct = count / total * 100 if total else 0.0
                if field_pct < self.FULL_MARKET_COVERAGE_PCT:
                    shortages.append(f"{label} {count}/{total}")
            data_gaps.insert(0, f"{trade_date} 行情/关键字段覆盖不足：{'，'.join(shortages)}，当前不是全市场扫描")
        stock_fields = market_coverage.get("stock_field_coverage") or {}
        listed_count = stock_fields.get("listed_date_count") or 0
        if self.config.min_listed_days > 0 and listed_count < market_coverage["total_stock_count"]:
            data_gaps.append(
                (
                    f"上市日期仅覆盖 {listed_count}/{market_coverage['total_stock_count']} 只股票；"
                    "缺失上市日期的股票会参与扫描，但无法严格执行次新股过滤"
                )
            )

        return {
            "candidate_count": len(candidates),
            "passed_count": len(passed),
            "market_coverage": market_coverage,
            "filter_reasons": dict(reasons),
            "data_gaps": data_gaps,
            "sample_failures": samples,
        }, passed

    async def market_coverage(self, trade_date: date | None = None) -> dict:
        """返回指定日期或最新K线交易日的行情覆盖率。"""
        resolved_date = await self._resolve_trade_date(trade_date)
        if resolved_date is None:
            return {
                "trade_date": None,
                "total_stock_count": 0,
                "kline_stock_count": 0,
                "coverage_pct": 0.0,
                "min_coverage_pct": self.FULL_MARKET_COVERAGE_PCT,
                "is_full_market": False,
                "field_coverage": {
                    "volume_count": 0,
                    "volume_pct": 0.0,
                    "amount_count": 0,
                    "amount_pct": 0.0,
                    "turnover_rate_count": 0,
                    "turnover_rate_pct": 0.0,
                },
                "stock_field_coverage": {"market_cap_count": 0, "listed_date_count": 0},
            }
        return {"trade_date": str(resolved_date), **await self._market_coverage(resolved_date)}

    async def _market_coverage(self, trade_date: date) -> dict:
        async with self._session_factory() as session:
            total_stock_count = (
                await session.execute(select(func.count()).select_from(Stock))
            ).scalar_one()
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
            listed_date_count = (
                await session.execute(select(func.count()).select_from(Stock).where(Stock.listed_date.isnot(None)))
            ).scalar_one()
            market_cap_count = (
                await session.execute(select(func.count()).select_from(Stock).where(Stock.market_cap.isnot(None)))
            ).scalar_one()

        coverage_pct = kline_stock_count / total_stock_count * 100 if total_stock_count else 0.0
        volume_pct = volume_count / total_stock_count * 100 if total_stock_count else 0.0
        amount_pct = amount_count / total_stock_count * 100 if total_stock_count else 0.0
        turnover_pct = turnover_count / total_stock_count * 100 if total_stock_count else 0.0
        is_full_market = all(
            pct >= self.FULL_MARKET_COVERAGE_PCT
            for pct in (coverage_pct, volume_pct, amount_pct, turnover_pct)
        )
        return {
            "total_stock_count": int(total_stock_count or 0),
            "kline_stock_count": int(kline_stock_count or 0),
            "coverage_pct": round(coverage_pct, 2),
            "min_coverage_pct": self.FULL_MARKET_COVERAGE_PCT,
            "is_full_market": is_full_market,
            "field_coverage": {
                "volume_count": int(volume_count or 0),
                "volume_pct": round(volume_pct, 2),
                "amount_count": int(amount_count or 0),
                "amount_pct": round(amount_pct, 2),
                "turnover_rate_count": int(turnover_count or 0),
                "turnover_rate_pct": round(turnover_pct, 2),
            },
            "stock_field_coverage": {
                "market_cap_count": int(market_cap_count or 0),
                "listed_date_count": int(listed_date_count or 0),
            },
        }

    async def _resolve_trade_date(self, trade_date: date | None) -> date | None:
        """未指定日期时使用最新有K线的交易日，避免周末/节假日空跑。"""
        if trade_date is not None:
            return trade_date
        async with self._session_factory() as session:
            stmt = select(func.max(DailyKline.trade_date)).where(DailyKline.trade_date <= date.today())
            return (await session.execute(stmt)).scalar_one_or_none()

    async def _get_candidates(self, trade_date: date, codes: list[str] | None = None) -> list[dict]:
        """获取候选池: 当日有K线 + 基本过滤"""
        c = self.config

        async with self._session_factory() as session:
            # 联合查询当日K线和股票信息
            stmt = (
                select(
                    DailyKline.code,
                    DailyKline.open,
                    DailyKline.close,
                    DailyKline.high,
                    DailyKline.low,
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
                .where(DailyKline.trade_date == trade_date)
            )
            if codes:
                stmt = stmt.where(DailyKline.code.in_(codes))

            # 基本过滤
            if c.exclude_st:
                stmt = stmt.where(Stock.is_st != True)  # noqa: E712
            if c.min_market_cap > 0:
                cap_threshold = Decimal(str(c.min_market_cap * 1_0000_0000))
                stmt = stmt.where(Stock.market_cap >= cap_threshold)
            if c.min_listed_days > 0:
                earliest = trade_date - timedelta(days=c.min_listed_days)
                stmt = stmt.where(or_(Stock.listed_date <= earliest, Stock.listed_date.is_(None)))

            rows = (await session.execute(stmt)).all()

        candidates = []
        for row in rows:
            open_p = self._to_float(row.open)
            close_p = self._to_float(row.close)
            if open_p <= 0 or close_p <= 0:
                continue
            candidates.append({
                "code": row.code,
                "name": row.name,
                "industry": row.industry,
                "open": open_p,
                "close_price": close_p,
                "high": self._to_float(row.high),
                "low": self._to_float(row.low),
                "volume": int(row.volume or 0),
                "amount": self._to_float(row.amount),
                "turnover_rate": self._to_float(row.turnover_rate),
                "market_cap": self._to_float(row.market_cap),
            })
        return candidates

    async def _evaluate_candidates(
        self,
        candidates: list[dict],
        trade_date: date,
    ) -> tuple[list[dict], Counter[str], list[dict]]:
        """批量计算筛选指标，避免全市场扫描时为每只股票单独查库。"""
        if not candidates:
            return [], Counter(), []

        codes = [cand["code"] for cand in candidates]
        history_by_code = await self._load_recent_history(codes, trade_date)
        main_flow_by_code = await self._load_main_flow_pct_map(codes, trade_date)

        passed: list[dict] = []
        reasons: Counter[str] = Counter()
        samples: list[dict] = []

        for cand in candidates:
            code = cand["code"]
            metrics = self._condition_metrics_from_history(
                cand,
                trade_date,
                history_by_code.get(code, []),
                main_flow_by_code.get(code, 0.0),
            )
            failed = self._failed_conditions(cand, metrics)
            if not failed:
                passed.append(
                    {
                        **cand,
                        "change_pct": round(metrics["change_pct"], 4),
                        "volume_ratio": round(metrics["volume_ratio"], 4),
                        "late_strength": round(metrics["late_strength"], 4),
                        "main_net_pct": round(metrics["main_net_pct"], 4),
                    }
                )
            reasons.update(failed)
            if len(samples) < 10:
                samples.append(
                    {
                        "code": code,
                        "name": cand.get("name"),
                        "failed": failed,
                        "change_pct": round(metrics.get("change_pct", 0.0), 2),
                        "volume_ratio": round(metrics.get("volume_ratio", 0.0), 2),
                        "late_strength": round(metrics.get("late_strength", 0.0), 2),
                        "turnover_rate": round(cand.get("turnover_rate", 0.0), 2),
                    }
                )

        return passed, reasons, samples

    async def _load_recent_history(self, codes: list[str], trade_date: date) -> dict[str, list[dict]]:
        """按股票批量取最近N条K线，供前收、均量和均线计算复用。"""
        c = self.config
        needed_rows = max(c.volume_avg_days + 1, c.ma_short, c.ma_long) + 1
        history_by_code: dict[str, list[dict]] = {}

        async with self._session_factory() as session:
            for chunk in self._chunks(codes):
                row_number = func.row_number().over(
                    partition_by=DailyKline.code,
                    order_by=DailyKline.trade_date.desc(),
                ).label("rn")
                ranked = (
                    select(
                        DailyKline.code,
                        DailyKline.trade_date,
                        DailyKline.close,
                        DailyKline.volume,
                        row_number,
                    )
                    .where(DailyKline.code.in_(chunk), DailyKline.trade_date <= trade_date)
                    .subquery()
                )
                stmt = (
                    select(
                        ranked.c.code,
                        ranked.c.trade_date,
                        ranked.c.close,
                        ranked.c.volume,
                        ranked.c.rn,
                    )
                    .where(ranked.c.rn <= needed_rows)
                    .order_by(ranked.c.code, ranked.c.rn)
                )
                rows = (await session.execute(stmt)).all()
                for row in rows:
                    history_by_code.setdefault(row.code, []).append(
                        {
                            "trade_date": row.trade_date,
                            "close": self._to_float(row.close),
                            "volume": int(row.volume or 0),
                        }
                    )

        return history_by_code

    async def _load_main_flow_pct_map(self, codes: list[str], trade_date: date) -> dict[str, float]:
        values: dict[str, float] = {}
        async with self._session_factory() as session:
            for chunk in self._chunks(codes):
                stmt = select(StockMainFlow.code, StockMainFlow.main_net_pct).where(
                    StockMainFlow.code.in_(chunk),
                    StockMainFlow.trade_date == trade_date,
                )
                rows = (await session.execute(stmt)).all()
                for row in rows:
                    values[row.code] = self._to_float(row.main_net_pct)
        return values

    def _condition_metrics_from_history(
        self,
        cand: dict,
        trade_date: date,
        history: list[dict],
        main_net_pct: float,
    ) -> dict:
        c = self.config
        close_p = cand["close_price"]
        open_p = cand["open"]
        change_pct = 0.0 if open_p <= 0 else (close_p - open_p) / open_p * 100
        prior_rows = [row for row in history if row["trade_date"] < trade_date]
        if prior_rows:
            prev_close = prior_rows[0]["close"]
            if prev_close > 0:
                change_pct = (close_p - prev_close) / prev_close * 100

        volume_rows = [row["volume"] for row in prior_rows[: c.volume_avg_days] if row["volume"] > 0]
        avg_vol = sum(volume_rows) / len(volume_rows) if volume_rows else 0.0
        volume_ratio = cand["volume"] / avg_vol if avg_vol > 0 else 0.0

        ma_short = None
        ma_long = None
        if c.price_above_ma:
            ma_short = self._average_close(history[: c.ma_short])
            ma_long = self._average_close(history[: c.ma_long])

        return {
            "change_pct": change_pct,
            "volume_ratio": volume_ratio,
            "ma_short": ma_short,
            "ma_long": ma_long,
            "late_strength": self._calculate_late_strength(close_p, cand["high"], cand["low"]),
            "main_net_pct": main_net_pct,
        }

    async def _check_conditions(self, cand: dict, trade_date: date) -> tuple[bool, dict]:
        """检查6大条件，返回 (是否通过, 额外指标)"""
        c = self.config
        code = cand["code"]
        close_p = cand["close_price"]
        open_p = cand["open"]
        high = cand["high"]
        low = cand["low"]
        volume = cand["volume"]
        turnover = cand["turnover_rate"]

        # 1. 涨幅条件
        if open_p <= 0:
            return False, {}
        change_pct = (close_p - open_p) / open_p * 100
        # 也考虑使用前一日收盘价计算涨幅
        prev_close = await self._get_prev_close(code, trade_date)
        if prev_close and prev_close > 0:
            change_pct = (close_p - prev_close) / prev_close * 100
        if not (c.min_change_pct <= change_pct <= c.max_change_pct):
            return False, {}

        # 2. 量比条件
        volume_ratio = await self._calculate_volume_ratio(code, trade_date, volume)
        if volume_ratio < c.volume_ratio_min:
            return False, {}

        # 3. 均线条件
        if c.price_above_ma:
            ma_short = await self._calculate_ma(code, trade_date, c.ma_short)
            ma_long = await self._calculate_ma(code, trade_date, c.ma_long)
            if ma_short is None or ma_long is None:
                return False, {}
            if close_p < ma_short or close_p < ma_long:
                return False, {}

        # 4. 尾盘强度
        late_strength = self._calculate_late_strength(close_p, high, low)
        if late_strength < c.late_strength_min:
            return False, {}

        # 5. 换手率条件
        if not (c.min_turnover_rate <= turnover <= c.max_turnover_rate):
            return False, {}

        # 6. 获取主力资金(加分项，不作为硬性条件)
        main_net_pct = await self._get_main_flow_pct(code, trade_date)

        metrics = {
            "change_pct": round(change_pct, 4),
            "volume_ratio": round(volume_ratio, 4),
            "late_strength": round(late_strength, 4),
            "main_net_pct": round(main_net_pct, 4),
        }
        return True, metrics

    async def _condition_metrics(self, cand: dict, trade_date: date) -> dict:
        """计算筛选条件需要的指标，供诊断使用。"""
        c = self.config
        code = cand["code"]
        close_p = cand["close_price"]
        open_p = cand["open"]
        change_pct = 0.0 if open_p <= 0 else (close_p - open_p) / open_p * 100
        prev_close = await self._get_prev_close(code, trade_date)
        if prev_close and prev_close > 0:
            change_pct = (close_p - prev_close) / prev_close * 100

        ma_short = None
        ma_long = None
        if c.price_above_ma:
            ma_short = await self._calculate_ma(code, trade_date, c.ma_short)
            ma_long = await self._calculate_ma(code, trade_date, c.ma_long)

        return {
            "change_pct": change_pct,
            "volume_ratio": await self._calculate_volume_ratio(code, trade_date, cand["volume"]),
            "ma_short": ma_short,
            "ma_long": ma_long,
            "late_strength": self._calculate_late_strength(close_p, cand["high"], cand["low"]),
            "main_net_pct": await self._get_main_flow_pct(code, trade_date),
        }

    def _failed_conditions(self, cand: dict, metrics: dict) -> list[str]:
        c = self.config
        failed: list[str] = []
        if not (c.min_change_pct <= metrics["change_pct"] <= c.max_change_pct):
            failed.append("change_pct")
        if metrics["volume_ratio"] < c.volume_ratio_min:
            failed.append("volume_ratio")
        if c.price_above_ma:
            ma_short = metrics.get("ma_short")
            ma_long = metrics.get("ma_long")
            if ma_short is None or ma_long is None or cand["close_price"] < ma_short or cand["close_price"] < ma_long:
                failed.append("moving_average")
        if metrics["late_strength"] < c.late_strength_min:
            failed.append("late_strength")
        turnover = cand["turnover_rate"]
        if not (c.min_turnover_rate <= turnover <= c.max_turnover_rate):
            failed.append("turnover_rate")
        return failed

    async def _get_prev_close(self, code: str, trade_date: date) -> float | None:
        """获取前一交易日收盘价"""
        async with self._session_factory() as session:
            stmt = (
                select(DailyKline.close)
                .where(DailyKline.code == code, DailyKline.trade_date < trade_date)
                .order_by(desc(DailyKline.trade_date))
                .limit(1)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return self._to_float(row) if row else None

    async def _calculate_volume_ratio(self, code: str, trade_date: date, today_volume: int) -> float:
        """量比 = 今日成交量 / N日平均成交量"""
        days = self.config.volume_avg_days
        async with self._session_factory() as session:
            # 使用子查询取最近N天
            sub = (
                select(DailyKline.volume)
                .where(DailyKline.code == code, DailyKline.trade_date < trade_date)
                .order_by(desc(DailyKline.trade_date))
                .limit(days)
            ).subquery()
            avg_vol = (await session.execute(select(func.avg(sub.c.volume)))).scalar_one_or_none()

        if not avg_vol or float(avg_vol) <= 0:
            return 0.0
        return today_volume / float(avg_vol)

    async def _calculate_ma(self, code: str, trade_date: date, period: int) -> float | None:
        """计算N日均线(包含当日)"""
        async with self._session_factory() as session:
            sub = (
                select(DailyKline.close)
                .where(DailyKline.code == code, DailyKline.trade_date <= trade_date)
                .order_by(desc(DailyKline.trade_date))
                .limit(period)
            ).subquery()
            result = (await session.execute(select(func.avg(sub.c.close)))).scalar_one_or_none()

        return float(result) if result else None

    @staticmethod
    def _calculate_late_strength(close: float, high: float, low: float) -> float:
        """尾盘强度 = (close - low) / (high - low)，越接近1说明收盘越强"""
        if high <= low:
            return 0.5
        return (close - low) / (high - low)

    async def _get_main_flow_pct(self, code: str, trade_date: date) -> float:
        """获取当日主力净流入占比"""
        async with self._session_factory() as session:
            stmt = select(StockMainFlow.main_net_pct).where(
                StockMainFlow.code == code,
                StockMainFlow.trade_date == trade_date,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
        return float(row) if row else 0.0

    async def _finalize_results(
        self,
        passed: list[dict],
        trade_date: date,
        *,
        persist: bool,
        include_backtest: bool = True,
        data_mode: str = "stored",
        quote_source: str | None = None,
        quote_time: datetime | str | None = None,
    ) -> list[dict]:
        if not passed:
            if persist:
                await self._clear_results(trade_date)
            return []

        scored = self._scorer.score_and_rank(passed)
        if include_backtest:
            await self._attach_recent_backtest(scored, trade_date)
        self._rank_results(scored)
        normalized_quote_time = self._normalize_quote_time(quote_time)
        for item in scored:
            item.update(
                {
                    "data_mode": data_mode,
                    "quote_source": quote_source,
                    "quote_time": normalized_quote_time,
                }
            )
            item.update(self._advisor.generate(item))
        if persist:
            await self._persist_results(scored, trade_date)
        return scored

    async def _attach_recent_backtest(self, results: list[dict], trade_date: date) -> None:
        if not results:
            return

        start_date = trade_date - timedelta(days=int(self.config.backtest_lookback_days))
        end_date = trade_date - timedelta(days=1)
        codes = [item["code"] for item in results]

        from eod_screener.backtest import EODBacktestEngine

        summaries = await EODBacktestEngine(self._session_factory, self.config).run_by_code(
            start_date,
            end_date,
            codes,
        )
        for item in results:
            stats = summaries.get(item["code"]) or self._empty_backtest_stats()
            item.update(
                {
                    "backtest_start_date": start_date,
                    "backtest_end_date": end_date,
                    "backtest_total_trades": int(stats.get("total_trades") or 0),
                    "backtest_win_rate": round(float(stats.get("win_rate") or 0.0), 4),
                    "backtest_avg_return": round(float(stats.get("avg_return") or 0.0), 4),
                    "backtest_max_drawdown": round(float(stats.get("max_drawdown") or 0.0), 4),
                    "backtest_profit_loss_ratio": round(float(stats.get("profit_loss_ratio") or 0.0), 4),
                }
            )
            item["backtest_score"] = self._calculate_backtest_score(item)

    @staticmethod
    def _empty_backtest_stats() -> dict:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "max_drawdown": 0.0,
            "profit_loss_ratio": 0.0,
        }

    @staticmethod
    def _calculate_backtest_score(item: dict) -> float:
        total_trades = int(item.get("backtest_total_trades") or 0)
        if total_trades <= 0:
            return 0.0

        avg_return = float(item.get("backtest_avg_return") or 0.0)
        win_rate_pct = float(item.get("backtest_win_rate") or 0.0) * 100
        profit_loss_ratio = min(float(item.get("backtest_profit_loss_ratio") or 0.0), 5.0)
        max_drawdown = float(item.get("backtest_max_drawdown") or 0.0)
        sample_weight = min(total_trades, 5) / 5
        raw = 50 + avg_return * 5 + (win_rate_pct - 50) * 0.35 + profit_loss_ratio * 4 - max_drawdown * 2
        return round(max(0.0, min(100.0, raw * sample_weight)), 2)

    @staticmethod
    def _rank_results(results: list[dict]) -> None:
        has_backtest = any("backtest_score" in item for item in results)
        if has_backtest:
            results.sort(
                key=lambda item: (
                    int(item.get("backtest_total_trades") or 0) > 0,
                    float(item.get("backtest_score") or 0.0),
                    float(item.get("backtest_avg_return") or 0.0),
                    float(item.get("backtest_win_rate") or 0.0),
                    float(item.get("score") or 0.0),
                ),
                reverse=True,
            )
        else:
            results.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)

        for index, item in enumerate(results, 1):
            item["rank"] = index

    @staticmethod
    def _normalize_quote_time(value: datetime | str | None) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    @staticmethod
    def _average_close(rows: list[dict]) -> float | None:
        closes = [row["close"] for row in rows if row["close"] > 0]
        return sum(closes) / len(closes) if closes else None

    @staticmethod
    def _chunks(items: list[str], size: int = 800):
        for index in range(0, len(items), size):
            yield items[index:index + size]

    async def _clear_results(self, trade_date: date) -> None:
        """清除指定交易日旧结果，避免重新运行后保留过期选股。"""
        async with self._session_factory() as session:
            await session.execute(delete(EodScreenResult).where(EodScreenResult.trade_date == trade_date))
            await session.commit()

    async def _persist_results(self, results: list[dict], trade_date: date) -> None:
        """保存选股结果"""
        async with self._session_factory() as session:
            # 先清除当日旧数据
            await session.execute(
                delete(EodScreenResult).where(EodScreenResult.trade_date == trade_date)
            )

            for item in results:
                row = EodScreenResult(
                    code=item["code"],
                    trade_date=trade_date,
                    name=item.get("name"),
                    close_price=Decimal(str(item["close_price"])),
                    change_pct=Decimal(str(item.get("change_pct", 0))),
                    volume_ratio=Decimal(str(item.get("volume_ratio", 0))),
                    turnover_rate=Decimal(str(item.get("turnover_rate", 0))),
                    late_strength=Decimal(str(item.get("late_strength", 0))),
                    score=Decimal(str(item.get("score", 0))),
                    rank=item.get("rank"),
                    signal_strength=item.get("signal_strength"),
                    target_price=Decimal(str(item.get("target_price", 0))),
                    stop_loss_price=Decimal(str(item.get("stop_loss_price", 0))),
                    suggestion=item.get("suggestion"),
                    data_mode=item.get("data_mode"),
                    quote_source=item.get("quote_source"),
                    quote_time=item.get("quote_time"),
                    backtest_start_date=item.get("backtest_start_date"),
                    backtest_end_date=item.get("backtest_end_date"),
                    backtest_total_trades=item.get("backtest_total_trades"),
                    backtest_win_rate=Decimal(str(item.get("backtest_win_rate", 0))),
                    backtest_avg_return=Decimal(str(item.get("backtest_avg_return", 0))),
                    backtest_max_drawdown=Decimal(str(item.get("backtest_max_drawdown", 0))),
                    backtest_profit_loss_ratio=Decimal(str(item.get("backtest_profit_loss_ratio", 0))),
                    backtest_score=Decimal(str(item.get("backtest_score", 0))),
                    config_snapshot=self.config.to_dict(),
                )
                session.add(row)
            await session.commit()

    @staticmethod
    def _to_float(value) -> float:
        if value is None:
            return 0.0
        if isinstance(value, Decimal):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
