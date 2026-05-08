"""财务报告数据采集。

优先使用 Tushare Pro。若 Tushare 未配置或账号无接口权限，则降级到 AKShare；
AKShare 降级路径必须通过巨潮公告反查披露日。缺少 publish_date 的记录会被跳过，
避免报告期日期冒充披露日期造成回测前视。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

from common.config import get_settings
from common.logger import get_logger
from data_collector.storage import DataStorage

logger = get_logger(__name__)


class FinancialDataBlockedError(RuntimeError):
    """财报采集因配置或依赖缺失被阻断。"""


@dataclass
class FinancialCollectionResult:
    status: str
    records_count: int = 0
    codes_requested: list[str] = field(default_factory=list)
    codes_succeeded: list[str] = field(default_factory=list)
    sources_attempted: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def data_reliable(self) -> bool:
        return self.status == "completed" and not self.blocking_issues

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["data_reliable"] = self.data_reliable
        return data


class FinancialReportCollector:
    """A 股财报指标采集器。"""

    _AK_REPORT_DATE_FIELDS = (
        "REPORT_DATE",
        "report_date",
        "END_DATE",
        "end_date",
        "报告期",
        "报告日期",
        "截止日期",
        "日期",
    )
    _AK_REVENUE_FIELDS = (
        "TOTAL_OPERATE_INCOME",
        "TOTAL_OPERATEINCOME",
        "TOTALOPERATEREVE",
        "OPERATE_INCOME",
        "营业总收入",
        "营业收入",
        "营业收入(元)",
        "主营业务收入",
        "total_revenue",
        "revenue",
        "operate_income",
    )
    _AK_REVENUE_YOY_FIELDS = (
        "TOTAL_OPERATE_INCOME_YOY",
        "TOTALOPERATEREVETZ",
        "DJD_TOI_YOY",
        "OPERATE_INCOME_YOY",
        "营业总收入同比增长",
        "营业收入同比增长率",
        "营业收入同比增长率(%)",
        "主营业务收入增长率(%)",
        "YSTZ",
        "YSHZ",
        "revenue_yoy",
    )
    _AK_NET_PROFIT_FIELDS = (
        "PARENT_NETPROFIT",
        "PARENTNETPROFIT",
        "NETPROFIT",
        "NET_PROFIT",
        "归属于母公司股东的净利润",
        "归母净利润",
        "净利润",
        "五、净利润",
        "net_profit",
    )
    _AK_NET_PROFIT_YOY_FIELDS = (
        "PARENT_NETPROFIT_YOY",
        "PARENTNETPROFITTZ",
        "DJD_DPNP_YOY",
        "NETPROFIT_YOY",
        "归母净利润同比增长",
        "净利润同比增长率",
        "净利润同比增长率(%)",
        "净利润增长率(%)",
        "SJLTZ",
        "net_profit_yoy",
    )
    _AK_GROSS_MARGIN_FIELDS = (
        "XSMLL",
        "GROSS_PROFIT_RATIO",
        "SALE_GROSS_PROFIT_RATE",
        "销售毛利率",
        "销售毛利率(%)",
        "毛利率",
        "gross_margin",
        "grossprofit_margin",
    )
    _AK_ROE_FIELDS = (
        "WEIGHTAVG_ROE",
        "ROE",
        "ROEJQ",
        "加权净资产收益率",
        "净资产收益率",
        "净资产收益率(%)",
        "roe",
        "roe_waa",
    )

    def __init__(
        self,
        storage: DataStorage,
        token: str | None = None,
        request_interval_seconds: float = 0.35,
    ):
        self.storage = storage
        self.token = token if token is not None else get_settings().data_source.tushare_token
        self.request_interval_seconds = request_interval_seconds
        self._pro = None
        self._tushare_skip_reason: str | None = None

    async def collect_financial_report(self, code: str, years: int = 3) -> FinancialCollectionResult:
        """采集单只股票近 N 年财报，Tushare 不可用时降级 AKShare。"""
        if self._tushare_skip_reason:
            tushare_result = FinancialCollectionResult(
                status="blocked",
                codes_requested=[code],
                sources_attempted=["tushare"],
            )
            fallback_reason = f"Tushare skipped after previous non-recoverable issue: {self._tushare_skip_reason}"
        else:
            tushare_result, fallback_reason = await self._collect_financial_report_tushare(code, years)
            if fallback_reason and self._is_non_recoverable_tushare_issue(fallback_reason):
                self._tushare_skip_reason = fallback_reason
        if tushare_result.status == "completed":
            return tushare_result
        if not fallback_reason:
            return tushare_result

        akshare_result = await self._collect_financial_report_akshare(code, years)
        akshare_result.sources_attempted = self._merge_unique(
            tushare_result.sources_attempted + akshare_result.sources_attempted
        )
        if fallback_reason:
            akshare_result.warnings.insert(
                0,
                f"{code}: Tushare unavailable, used AKShare fallback ({fallback_reason})",
            )
        return akshare_result

    async def _collect_financial_report_tushare(
        self,
        code: str,
        years: int,
    ) -> tuple[FinancialCollectionResult, str | None]:
        """使用 Tushare 采集单只股票；返回 fallback_reason 表示可降级。"""
        result = FinancialCollectionResult(
            status="completed",
            codes_requested=[code],
            sources_attempted=["tushare"],
        )
        try:
            pro = self._get_pro_api()
            ts_code = self._to_ts_code(code)
            today = date.today()
            start = date(today.year - years, 1, 1)
            end = today

            income_df = await self._fetch_income(pro, ts_code, start, end)
            if income_df is None or income_df.empty:
                result.status = "failed"
                result.errors[code] = "Tushare income returned no rows"
                return result, result.errors[code]

            indicator_df = await self._fetch_fina_indicator(pro, ts_code, start, end)
            daily_basic_df = await self._fetch_daily_basic(pro, ts_code, start, end)
            records, warnings = self._build_records(code, income_df, indicator_df, daily_basic_df)
            result.warnings.extend(warnings)

            if not records:
                result.status = "failed"
                result.errors[code] = "No usable financial reports after validation"
                return result, result.errors[code]

            try:
                await self.storage.upsert_financial_reports(records)
            except Exception as e:
                result.status = "failed"
                result.errors[code] = f"Failed to write Tushare financial reports: {e}"
                logger.error(f"财报数据写入失败: code={code}, source=tushare, error={e}")
                return result, None
            result.records_count = len(records)
            result.codes_succeeded.append(code)
            result.sources_used.append("tushare")
            logger.info(f"写入财报数据: code={code}, records={len(records)}")
            return result, None
        except FinancialDataBlockedError as e:
            result.status = "blocked"
            result.blocking_issues.append(str(e))
            logger.warning(f"Tushare 财报采集被阻断: code={code}, reason={e}")
            return result, str(e)
        except Exception as e:
            result.status = "failed"
            result.errors[code] = f"Tushare financial collection failed: {e}"
            logger.warning(f"Tushare 财报采集失败，准备降级: code={code}, error={e}")
            return result, str(e)

    async def _collect_financial_report_akshare(self, code: str, years: int) -> FinancialCollectionResult:
        """使用 AKShare 采集单只股票；必须通过公告数据确认 publish_date。"""
        result = FinancialCollectionResult(
            status="completed",
            codes_requested=[code],
            sources_attempted=["akshare"],
        )
        warnings: list[str] = []

        try:
            indicator_df = await self._fetch_ak_financial_indicator(code, years)
        except FinancialDataBlockedError as e:
            result.status = "blocked"
            result.blocking_issues.append(str(e))
            return result
        except Exception as e:
            indicator_df = None
            warnings.append(f"{code}: AKShare financial indicator failed: {e}")
            logger.warning(f"AKShare 财务指标采集失败: code={code}, error={e}")

        try:
            profit_df = await self._fetch_ak_profit_sheet(code)
        except FinancialDataBlockedError as e:
            result.status = "blocked"
            result.blocking_issues.append(str(e))
            return result
        except Exception as e:
            profit_df = None
            warnings.append(f"{code}: AKShare profit sheet failed: {e}")
            logger.warning(f"AKShare 利润表采集失败: code={code}, error={e}")

        if self._is_empty_frame(indicator_df) and self._is_empty_frame(profit_df):
            result.status = "failed"
            result.errors[code] = "AKShare financial metrics returned no rows"
            result.warnings.extend(warnings)
            return result

        try:
            disclosures_df = await self._fetch_ak_disclosures(code, years)
        except FinancialDataBlockedError as e:
            result.status = "blocked"
            result.blocking_issues.append(str(e))
            result.warnings.extend(warnings)
            return result
        except Exception as e:
            disclosures_df = None
            warnings.append(f"{code}: AKShare disclosure lookup failed: {e}")
            logger.warning(f"AKShare 公告披露日采集失败: code={code}, error={e}")

        if self._is_empty_frame(disclosures_df):
            result.status = "failed"
            result.errors[code] = "AKShare disclosure data returned no rows; cannot determine publish_date"
            result.warnings.extend(warnings)
            return result

        try:
            valuation_df = await self._fetch_ak_valuation_history(code, years)
        except FinancialDataBlockedError as e:
            valuation_df = None
            warnings.append(f"{code}: AKShare valuation blocked: {e}")
        except Exception as e:
            valuation_df = None
            warnings.append(f"{code}: AKShare valuation lookup failed: {e}")
            logger.warning(f"AKShare 估值采集失败: code={code}, error={e}")

        records, build_warnings = self._build_ak_records(
            code,
            indicator_df,
            profit_df,
            disclosures_df,
            valuation_df,
            years,
        )
        result.warnings.extend(warnings)
        result.warnings.extend(build_warnings)

        if not records:
            result.status = "failed"
            result.errors[code] = "No AKShare financial reports with reliable publish_date"
            return result

        try:
            await self.storage.upsert_financial_reports(records)
        except Exception as e:
            result.status = "failed"
            result.errors[code] = f"Failed to write AKShare financial reports: {e}"
            logger.error(f"财报数据写入失败: code={code}, source=akshare, error={e}")
            return result

        result.records_count = len(records)
        result.codes_succeeded.append(code)
        result.sources_used.append("akshare")
        logger.info(f"写入 AKShare 财报数据: code={code}, records={len(records)}")
        return result

    async def collect_batch(self, codes: list[str], years: int = 3) -> FinancialCollectionResult:
        """批量采集多只股票财报。"""
        normalized_codes = [str(code).strip() for code in codes if str(code).strip()]
        aggregate = FinancialCollectionResult(status="completed", codes_requested=normalized_codes)

        for i, code in enumerate(normalized_codes):
            item = await self.collect_financial_report(code, years=years)
            aggregate.records_count += item.records_count
            aggregate.codes_succeeded = self._merge_unique(aggregate.codes_succeeded + item.codes_succeeded)
            aggregate.sources_attempted = self._merge_unique(
                aggregate.sources_attempted + item.sources_attempted
            )
            aggregate.sources_used = self._merge_unique(aggregate.sources_used + item.sources_used)
            aggregate.warnings.extend(item.warnings)
            aggregate.errors.update(item.errors)
            aggregate.blocking_issues.extend(item.blocking_issues)
            if i < len(normalized_codes) - 1:
                await asyncio.sleep(self.request_interval_seconds)

        if aggregate.codes_succeeded and (aggregate.errors or aggregate.blocking_issues):
            aggregate.status = "partial"
        elif aggregate.blocking_issues and not aggregate.errors:
            aggregate.status = "blocked"
        elif aggregate.errors and not aggregate.codes_succeeded:
            aggregate.status = "failed"

        await self._write_collect_log(aggregate)
        logger.info(
            "批量采集财报完成: requested=%s, succeeded=%s, records=%s, status=%s",
            len(normalized_codes),
            len(aggregate.codes_succeeded),
            aggregate.records_count,
            aggregate.status,
        )
        return aggregate

    def _get_pro_api(self):
        if self._pro is not None:
            return self._pro
        if not self.token:
            raise FinancialDataBlockedError("TUSHARE_TOKEN is required for financial report ingestion")
        try:
            import tushare as ts
        except ImportError as e:
            raise FinancialDataBlockedError("Python package 'tushare' is not installed") from e

        ts.set_token(self.token)
        self._pro = ts.pro_api(self.token)
        return self._pro

    def _get_akshare(self):
        try:
            import akshare as ak
        except ImportError as e:
            raise FinancialDataBlockedError("Python package 'akshare' is not installed") from e
        return ak

    async def _fetch_income(self, pro, ts_code: str, start: date, end: date) -> pd.DataFrame | None:
        return await asyncio.to_thread(
            pro.income,
            ts_code=ts_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )

    async def _fetch_fina_indicator(self, pro, ts_code: str, start: date, end: date) -> pd.DataFrame | None:
        try:
            return await asyncio.to_thread(
                pro.fina_indicator,
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception as e:
            logger.warning(f"Tushare fina_indicator 采集失败: ts_code={ts_code}, error={e}")
            return None

    async def _fetch_daily_basic(self, pro, ts_code: str, start: date, end: date) -> pd.DataFrame | None:
        try:
            return await asyncio.to_thread(
                pro.daily_basic,
                ts_code=ts_code,
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception as e:
            logger.warning(f"Tushare daily_basic 采集失败: ts_code={ts_code}, error={e}")
            return None

    async def _fetch_ak_financial_indicator(self, code: str, years: int) -> pd.DataFrame | None:
        ak = self._get_akshare()
        ts_code = self._to_ts_code(code)
        start_year = str(date.today().year - years)

        if hasattr(ak, "stock_financial_analysis_indicator_em"):
            try:
                return await asyncio.to_thread(
                    ak.stock_financial_analysis_indicator_em,
                    symbol=ts_code,
                    indicator="按报告期",
                )
            except Exception as e:
                logger.warning(f"AKShare 东方财富主要指标采集失败: code={code}, error={e}")

        if not hasattr(ak, "stock_financial_analysis_indicator"):
            raise RuntimeError("AKShare financial indicator function is unavailable")
        return await asyncio.to_thread(
            ak.stock_financial_analysis_indicator,
            symbol=self._plain_code(code),
            start_year=start_year,
        )

    async def _fetch_ak_profit_sheet(self, code: str) -> pd.DataFrame | None:
        ak = self._get_akshare()
        if not hasattr(ak, "stock_profit_sheet_by_report_em"):
            return None
        return await asyncio.to_thread(
            ak.stock_profit_sheet_by_report_em,
            symbol=self._to_em_prefixed_code(code),
        )

    async def _fetch_ak_disclosures(self, code: str, years: int) -> pd.DataFrame | None:
        ak = self._get_akshare()
        if not hasattr(ak, "stock_zh_a_disclosure_report_cninfo"):
            raise RuntimeError("AKShare cninfo disclosure function is unavailable")

        today = date.today()
        start = date(today.year - years, 1, 1)
        plain_code = self._plain_code(code)
        frames: list[pd.DataFrame] = []
        for category in ("一季报", "半年报", "三季报", "年报"):
            try:
                df = await asyncio.to_thread(
                    ak.stock_zh_a_disclosure_report_cninfo,
                    symbol=plain_code,
                    market="沪深京",
                    category=category,
                    start_date=start.strftime("%Y%m%d"),
                    end_date=today.strftime("%Y%m%d"),
                )
                if not self._is_empty_frame(df):
                    frames.append(df)
            except Exception as e:
                logger.warning(
                    "AKShare 巨潮公告采集失败: code=%s, category=%s, error=%s",
                    code,
                    category,
                    e,
                )

        if not frames:
            schedule_df = await self._fetch_ak_disclosure_schedule(ak, code, start, today)
            if not self._is_empty_frame(schedule_df):
                frames.append(schedule_df)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    async def _fetch_ak_disclosure_schedule(
        self,
        ak,
        code: str,
        start: date,
        end: date,
    ) -> pd.DataFrame | None:
        if not hasattr(ak, "stock_report_disclosure"):
            return None

        plain_code = self._plain_code(code)
        rows: list[dict[str, Any]] = []
        for report_date in self._report_periods_between(start, end):
            try:
                df = await asyncio.to_thread(
                    ak.stock_report_disclosure,
                    market="沪深京",
                    period=self._cninfo_period_label(report_date),
                )
            except Exception as e:
                logger.warning(
                    "AKShare 预约披露采集失败: code=%s, period=%s, error=%s",
                    code,
                    report_date,
                    e,
                )
                continue
            if self._is_empty_frame(df):
                continue
            code_col = self._find_column(df, ("股票代码", "代码", "SECURITY_CODE", "secCode"))
            publish_col = self._find_column(df, ("实际披露", "公告时间", "publish_date"))
            if not code_col or not publish_col:
                continue
            matched = df[df[code_col].astype(str).str.zfill(6) == plain_code]
            for _, row in matched.iterrows():
                publish_date = self._parse_date(row.get(publish_col))
                if publish_date is None:
                    continue
                rows.append({
                    "_report_date": report_date,
                    "公告标题": self._cninfo_period_label(report_date),
                    "公告时间": publish_date,
                    "代码": plain_code,
                })

        return pd.DataFrame(rows)

    async def _fetch_ak_valuation_history(self, code: str, years: int) -> pd.DataFrame | None:
        """用百度股市通估值历史补 PE/PB；无可用数据时返回空表，不构造估值。"""
        ak = self._get_akshare()
        if not hasattr(ak, "stock_zh_valuation_baidu"):
            return None

        period = self._valuation_period_label(years)
        frames: list[pd.DataFrame] = []
        for indicator, column_name in (
            ("市盈率(TTM)", "pe_ratio"),
            ("市净率", "pb_ratio"),
        ):
            try:
                df = await asyncio.to_thread(
                    ak.stock_zh_valuation_baidu,
                    symbol=self._plain_code(code),
                    indicator=indicator,
                    period=period,
                )
            except Exception as e:
                logger.warning(
                    "AKShare 百度估值采集失败: code=%s, indicator=%s, error=%s",
                    code,
                    indicator,
                    e,
                )
                continue
            if self._is_empty_frame(df):
                continue
            date_col = self._find_column(df, ("date", "日期", "trade_date"))
            value_col = self._find_column(df, ("value", "数值", indicator))
            if not date_col or not value_col:
                continue
            work = df[[date_col, value_col]].copy()
            work["trade_date"] = work[date_col].map(self._parse_date)
            work[column_name] = work[value_col].map(self._parse_number)
            work = work[["trade_date", column_name]].dropna(subset=["trade_date", column_name])
            if not work.empty:
                frames.append(work)

        if not frames:
            return pd.DataFrame()

        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.merge(frame, on="trade_date", how="outer")
        return merged.sort_values("trade_date")

    def _valuation_period_label(self, years: int) -> str:
        if years <= 1:
            return "近一年"
        if years <= 3:
            return "近三年"
        if years <= 5:
            return "近五年"
        if years <= 10:
            return "近十年"
        return "全部"

    def _valuation_asof(self, df: pd.DataFrame | None, publish_date: date) -> dict[str, float | None]:
        if df is None or df.empty or "trade_date" not in df.columns:
            return {"pe_ratio": None, "pb_ratio": None}

        df = df.copy()
        df["_trade_date"] = df["trade_date"].map(self._parse_date)
        df = df[df["_trade_date"].notna()]
        df = df[df["_trade_date"] <= publish_date].sort_values("_trade_date", ascending=False)
        if df.empty:
            return {"pe_ratio": None, "pb_ratio": None}

        latest = df.iloc[0]
        pe_ratio = self._first_number(latest, ("pe_ttm", "pe", "pe_ratio"))
        pb_ratio = self._first_number(latest, ("pb", "pb_ratio"))
        return {"pe_ratio": pe_ratio, "pb_ratio": pb_ratio}

    def _build_records(
        self,
        code: str,
        income_df: pd.DataFrame,
        indicator_df: pd.DataFrame | None,
        daily_basic_df: pd.DataFrame | None,
    ) -> tuple[list[dict], list[str]]:
        warnings: list[str] = []
        income_by_period = self._latest_by_period(income_df)
        indicator_by_period = self._latest_by_period(indicator_df) if indicator_df is not None else {}
        records: list[dict] = []

        for period, income_row in income_by_period.items():
            report_date = self._parse_date(period)
            publish_date = self._first_date(income_row, ("f_ann_date", "ann_date", "publish_date"))
            if report_date is None:
                warnings.append(f"{code}: skipped income row without report_date")
                continue
            if publish_date is None:
                warnings.append(f"{code}: skipped {report_date} because publish_date is missing")
                continue
            if publish_date > date.today():
                warnings.append(f"{code}: skipped {report_date} because publish_date is in the future")
                continue

            indicator_row = indicator_by_period.get(period)
            valuation = self._valuation_asof(daily_basic_df, publish_date)
            if valuation["pe_ratio"] is None or valuation["pb_ratio"] is None:
                warnings.append(f"{code}: valuation missing as of {publish_date}")

            record = {
                "code": code,
                "report_date": report_date,
                "publish_date": publish_date,
                "revenue": self._first_number(income_row, ("total_revenue", "revenue", "operate_income")),
                "revenue_yoy": self._first_number(
                    indicator_row,
                    ("q_sales_yoy", "or_yoy", "yoy_sales", "tr_yoy", "revenue_yoy"),
                ),
                "net_profit": self._first_number(
                    income_row,
                    ("n_income_attr_p", "n_income", "net_profit", "net_profit_attr_p"),
                ),
                "net_profit_yoy": self._first_number(
                    indicator_row,
                    ("q_netprofit_yoy", "q_profit_yoy", "netprofit_yoy", "dt_netprofit_yoy", "yoy_net_profit"),
                ),
                "gross_margin": self._first_number(
                    indicator_row,
                    ("grossprofit_margin", "gross_profit_margin", "sale_gpr", "gross_margin"),
                ),
                "roe": self._first_number(indicator_row, ("roe", "roe_waa", "roe_dt")),
                "pe_ratio": valuation["pe_ratio"],
                "pb_ratio": valuation["pb_ratio"],
                "source": "tushare",
            }
            records.append(record)

        records.sort(key=lambda item: item["report_date"])
        return records, warnings

    def _build_ak_records(
        self,
        code: str,
        indicator_df: pd.DataFrame | None,
        profit_df: pd.DataFrame | None,
        disclosures_df: pd.DataFrame,
        valuation_df: pd.DataFrame | None,
        years: int,
    ) -> tuple[list[dict], list[str]]:
        warnings: list[str] = []
        today = date.today()
        start = date(today.year - years, 1, 1)
        indicator_by_period = self._latest_ak_by_period(indicator_df)
        profit_by_period = self._latest_ak_by_period(profit_df)
        publish_dates = self._build_ak_publish_date_map(disclosures_df)
        records: list[dict] = []

        if not publish_dates:
            warnings.append(f"{code}: AKShare disclosure data did not contain usable publish_date mappings")

        periods = sorted(set(indicator_by_period) | set(profit_by_period))
        for report_date in periods:
            if report_date < start or report_date > today:
                continue
            publish_date = publish_dates.get(report_date)
            if publish_date is None:
                warnings.append(f"{code}: skipped {report_date} because AKShare publish_date is missing")
                continue
            if publish_date > today:
                warnings.append(f"{code}: skipped {report_date} because publish_date is in the future")
                continue

            indicator_row = indicator_by_period.get(report_date)
            profit_row = profit_by_period.get(report_date)
            revenue = self._first_number(indicator_row, self._AK_REVENUE_FIELDS)
            if revenue is None:
                revenue = self._first_number(profit_row, self._AK_REVENUE_FIELDS)
            net_profit = self._first_number(indicator_row, self._AK_NET_PROFIT_FIELDS)
            if net_profit is None:
                net_profit = self._first_number(profit_row, self._AK_NET_PROFIT_FIELDS)
            revenue_yoy = self._first_number(indicator_row, self._AK_REVENUE_YOY_FIELDS)
            net_profit_yoy = self._first_number(indicator_row, self._AK_NET_PROFIT_YOY_FIELDS)
            gross_margin = self._first_number(indicator_row, self._AK_GROSS_MARGIN_FIELDS)
            roe = self._first_number(indicator_row, self._AK_ROE_FIELDS)
            valuation = self._valuation_asof(valuation_df, publish_date)

            if all(
                value is None
                for value in (revenue, revenue_yoy, net_profit, net_profit_yoy, gross_margin, roe)
            ):
                warnings.append(f"{code}: skipped {report_date} because AKShare metrics are missing")
                continue

            records.append({
                "code": code,
                "report_date": report_date,
                "publish_date": publish_date,
                "revenue": revenue,
                "revenue_yoy": revenue_yoy,
                "net_profit": net_profit,
                "net_profit_yoy": net_profit_yoy,
                "gross_margin": gross_margin,
                "roe": roe,
                "pe_ratio": valuation["pe_ratio"],
                "pb_ratio": valuation["pb_ratio"],
                "source": "akshare+baidu" if valuation["pe_ratio"] is not None or valuation["pb_ratio"] is not None else "akshare",
            })

        records.sort(key=lambda item: item["report_date"])
        if records:
            missing_valuation_count = sum(
                1
                for item in records
                if item.get("pe_ratio") is None or item.get("pb_ratio") is None
            )
            if missing_valuation_count:
                warnings.append(
                    f"{code}: valuation missing for {missing_valuation_count}/{len(records)} AKShare fallback records"
                )
        return records, warnings

    def _latest_by_period(self, df: pd.DataFrame | None) -> dict[str, pd.Series]:
        if df is None or df.empty or "end_date" not in df.columns:
            return {}

        work = df.copy()
        work["_publish_date"] = work.apply(
            lambda row: self._first_date(row, ("f_ann_date", "ann_date", "publish_date")),
            axis=1,
        )
        work = work[work["_publish_date"].notna()]
        work = work.sort_values(["end_date", "_publish_date"])

        result: dict[str, pd.Series] = {}
        for _, row in work.iterrows():
            period = str(row["end_date"]).strip()
            if period:
                result[period] = row
        return result

    def _latest_ak_by_period(self, df: pd.DataFrame | None) -> dict[date, pd.Series]:
        if self._is_empty_frame(df):
            return {}

        work = df.copy()
        work["_report_date"] = work.apply(
            lambda row: self._first_date(row, self._AK_REPORT_DATE_FIELDS),
            axis=1,
        )
        work = work[work["_report_date"].notna()]
        work = work.sort_values("_report_date")

        result: dict[date, pd.Series] = {}
        for _, row in work.iterrows():
            report_date = row["_report_date"]
            if isinstance(report_date, date):
                result[report_date] = row
        return result

    def _build_ak_publish_date_map(self, df: pd.DataFrame | None) -> dict[date, date]:
        if self._is_empty_frame(df):
            return {}

        today = date.today()
        result: dict[date, date] = {}
        for _, row in df.iterrows():
            title = self._first_text(
                row,
                ("公告标题", "announcementTitle", "title", "TITLE", "报告名称"),
            )
            if title and self._skip_ak_disclosure_title(title):
                continue

            report_date = self._first_date(
                row,
                ("_report_date", "报告期", "report_date", "REPORT_DATE", "end_date", "END_DATE"),
            )
            if report_date is None and title:
                report_date = self._extract_report_date_from_title(title)
            if report_date is None:
                continue

            publish_date = self._first_date(
                row,
                ("公告时间", "实际披露", "publish_date", "ann_date", "f_ann_date", "announcementTime"),
            )
            if publish_date is None or publish_date > today:
                continue

            existing = result.get(report_date)
            if existing is None or publish_date < existing:
                result[report_date] = publish_date
        return result

    def _skip_ak_disclosure_title(self, title: str) -> bool:
        text = re.sub(r"\s+", "", title)
        return any(
            keyword in text
            for keyword in (
                "更正",
                "补充",
                "修订",
                "取消",
                "作废",
                "延期披露",
                "问询函",
                "说明会",
                "审计报告",
                "内部控制",
                "社会责任",
                "ESG",
            )
        )

    def _extract_report_date_from_title(self, title: str) -> date | None:
        text = re.sub(r"\s+", "", title)
        year_match = re.search(r"(20\d{2})年", text)
        if not year_match:
            return None
        year = int(year_match.group(1))
        if re.search(r"(第一季度|一季度|1季度|一季报)", text):
            return date(year, 3, 31)
        if re.search(r"(半年度|半年报|中期)", text):
            return date(year, 6, 30)
        if re.search(r"(第三季度|三季度|3季度|三季报)", text):
            return date(year, 9, 30)
        if re.search(r"(年度报告|年报)", text):
            return date(year, 12, 31)
        return None

    def _to_ts_code(self, code: str) -> str:
        raw = str(code).strip().upper()
        if "." in raw:
            return raw.upper()
        if raw.startswith(("SH", "SZ", "BJ")) and len(raw) > 2:
            return f"{raw[2:]}.{raw[:2]}"
        if raw.startswith("6"):
            return f"{raw}.SH"
        if raw.startswith(("4", "8")):
            return f"{raw}.BJ"
        return f"{raw}.SZ"

    def _plain_code(self, code: str) -> str:
        raw = str(code).strip().upper()
        if "." in raw:
            return raw.split(".", 1)[0].zfill(6)
        if raw.startswith(("SH", "SZ", "BJ")):
            return raw[2:].zfill(6)
        return raw.zfill(6)

    def _to_em_prefixed_code(self, code: str) -> str:
        ts_code = self._to_ts_code(code)
        plain, exchange = ts_code.split(".", 1)
        return f"{exchange}{plain}"

    def _report_periods_between(self, start: date, end: date) -> list[date]:
        periods: list[date] = []
        for year in range(start.year, end.year + 1):
            for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
                period = date(year, month, day)
                if start <= period <= end:
                    periods.append(period)
        return periods

    def _cninfo_period_label(self, report_date: date) -> str:
        if report_date.month == 3:
            return f"{report_date.year}一季"
        if report_date.month == 6:
            return f"{report_date.year}半年报"
        if report_date.month == 9:
            return f"{report_date.year}三季"
        return f"{report_date.year}年报"

    def _parse_date(self, value: Any) -> date | None:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            if len(text) == 8 and text.isdigit():
                return datetime.strptime(text, "%Y%m%d").date()
            return pd.Timestamp(text).date()
        except Exception:
            return None

    def _is_empty_frame(self, df: pd.DataFrame | None) -> bool:
        return df is None or df.empty

    def _find_column(self, df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
        columns_by_lower = {str(column).lower(): column for column in df.columns}
        for candidate in candidates:
            if candidate in df.columns:
                return candidate
            lowered = candidate.lower()
            if lowered in columns_by_lower:
                return columns_by_lower[lowered]
        return None

    def _first_date(self, row: pd.Series | None, fields: tuple[str, ...]) -> date | None:
        if row is None:
            return None
        for field_name in fields:
            if field_name not in row.index:
                continue
            parsed = self._parse_date(row.get(field_name))
            if parsed:
                return parsed
        return None

    def _first_text(self, row: pd.Series | None, fields: tuple[str, ...]) -> str:
        if row is None:
            return ""
        for field_name in fields:
            if field_name not in row.index:
                continue
            value = row.get(field_name)
            if value is None or pd.isna(value):
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def _first_number(self, row: pd.Series | None, fields: tuple[str, ...]) -> float | None:
        if row is None:
            return None
        for field_name in fields:
            if field_name not in row.index:
                continue
            value = self._parse_number(row.get(field_name))
            if value is not None:
                return value
        return None

    def _parse_number(self, value: Any) -> float | None:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, str):
            text = value.strip().replace(",", "").replace("%", "")
            if text in {"", "-", "--", "None", "nan", "NaN", "null"}:
                return None
            value = text
        parsed = pd.to_numeric(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return float(parsed)

    def _is_non_recoverable_tushare_issue(self, reason: str) -> bool:
        lowered = reason.lower()
        return any(
            marker in lowered
            for marker in (
                "tushare_token",
                "not installed",
                "没有接口",
                "访问权限",
                "permission",
                "权限",
            )
        )

    def _merge_unique(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    async def _write_collect_log(self, result: FinancialCollectionResult):
        status = "success" if result.status == "completed" else result.status
        source = "+".join(result.sources_used or result.sources_attempted or ["financial_report"])
        error_message = None
        if result.blocking_issues:
            error_message = "; ".join(result.blocking_issues)
        elif result.errors:
            error_message = "; ".join(f"{code}: {err}" for code, err in result.errors.items())

        try:
            await self.storage.insert_collect_log({
                "source": source,
                "task_type": "financial_report",
                "status": status,
                "records_count": result.records_count,
                "error_message": error_message,
                "started_at": datetime.now(),
                "finished_at": datetime.now(),
            })
        except Exception as e:
            logger.warning(f"财报采集日志写入失败: {e}")
