"""Phase 7 验证脚本：财报采集可靠性。"""

import asyncio
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = 0
FAIL = 0


def ok(msg: str):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def fail(msg: str):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


def check(condition: bool, msg: str):
    if condition:
        ok(msg)
    else:
        fail(msg)


class FakeStorage:
    def __init__(self):
        self.logs = []
        self.records = []

    async def insert_collect_log(self, log: dict):
        self.logs.append(log)

    async def upsert_financial_reports(self, records: list[dict]):
        self.records.extend(records)


def attach_fake_akshare(collector, include_disclosure: bool = True):
    async def fake_indicator(code: str, years: int):
        return pd.DataFrame([
            {
                "REPORT_DATE": "2024-03-31",
                "TOTAL_OPERATE_INCOME": "100.50",
                "TOTAL_OPERATE_INCOME_YOY": "21.3%",
                "PARENT_NETPROFIT": "10.25",
                "PARENT_NETPROFIT_YOY": "35.7",
                "XSMLL": "28.4",
                "WEIGHTAVG_ROE": "9.8",
            }
        ])

    async def fake_profit(code: str):
        return pd.DataFrame([
            {
                "REPORT_DATE": "2024-03-31",
                "TOTAL_OPERATE_INCOME": "100.50",
                "PARENT_NETPROFIT": "10.25",
            }
        ])

    async def fake_disclosures(code: str, years: int):
        if not include_disclosure:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "代码": code,
                "公告标题": "2024年第一季度报告",
                "公告时间": "2024-04-20 18:00:00",
            }
        ])

    async def fake_valuation(code: str, years: int):
        return pd.DataFrame([
            {"trade_date": "2024-04-19", "pe_ratio": 22.0, "pb_ratio": 3.2},
            {"trade_date": "2024-04-22", "pe_ratio": 30.0, "pb_ratio": 4.0},
        ])

    collector._fetch_ak_financial_indicator = fake_indicator
    collector._fetch_ak_profit_sheet = fake_profit
    collector._fetch_ak_disclosures = fake_disclosures
    collector._fetch_ak_valuation_history = fake_valuation


def test_fallback_without_token_uses_akshare():
    from data_collector.sources.financial_report import FinancialReportCollector

    async def _run():
        storage = FakeStorage()
        collector = FinancialReportCollector(storage, token="")
        attach_fake_akshare(collector)
        result = await collector.collect_batch(["300308"])
        check(result.status == "completed", "missing TUSHARE_TOKEN falls back to AKShare")
        check(result.sources_attempted == ["tushare", "akshare"], "fallback records attempted sources")
        check(result.sources_used == ["akshare"], "fallback records used source")
        check(len(storage.records) == 1, "fallback writes one AKShare record")
        check(storage.records[0]["source"] == "akshare+baidu", "fallback record source includes valuation source")
        check(str(storage.records[0]["publish_date"]) == "2024-04-20", "fallback uses disclosure publish_date")
        check(storage.records[0]["pe_ratio"] == 22.0, "fallback uses valuation on or before publish_date")
        check(storage.records[0]["pb_ratio"] == 3.2, "fallback writes pb_ratio")
        check(storage.logs and storage.logs[0]["source"] == "akshare", "fallback collection log uses akshare source")

    asyncio.run(_run())


def test_record_building():
    from data_collector.sources.financial_report import FinancialReportCollector

    storage = FakeStorage()
    collector = FinancialReportCollector(storage, token="dummy")

    income = pd.DataFrame([
        {
            "ts_code": "300308.SZ",
            "end_date": "20240331",
            "f_ann_date": "20240420",
            "total_revenue": "100.50",
            "n_income_attr_p": "10.25",
        }
    ])
    indicator = pd.DataFrame([
        {
            "ts_code": "300308.SZ",
            "end_date": "20240331",
            "ann_date": "20240420",
            "q_sales_yoy": "21.3",
            "q_netprofit_yoy": "35.7",
            "grossprofit_margin": "28.4",
            "roe": "9.8",
        }
    ])
    daily_basic = pd.DataFrame([
        {"trade_date": "20240422", "pe_ttm": "30.0", "pb": "4.0"},
        {"trade_date": "20240419", "pe_ttm": "22.0", "pb": "3.2"},
    ])

    records, warnings = collector._build_records("300308", income, indicator, daily_basic)
    check(len(records) == 1, "sample report builds one record")
    record = records[0]
    check(str(record["report_date"]) == "2024-03-31", "report_date parsed")
    check(str(record["publish_date"]) == "2024-04-20", "publish_date parsed")
    check(record["revenue"] == 100.5, "revenue parsed from income")
    check(record["net_profit_yoy"] == 35.7, "net_profit_yoy parsed from indicator")
    check(record["pe_ratio"] == 22.0, "valuation uses latest trading day on or before publish date")
    check(not warnings, "complete sample has no warnings")


def test_financial_percentage_precision_allows_extreme_yoy():
    from common.models import FinancialReport

    percentage_columns = ("revenue_yoy", "net_profit_yoy", "gross_margin", "roe")
    for column_name in percentage_columns:
        column_type = FinancialReport.__table__.c[column_name].type
        check(column_type.precision == 12, f"{column_name} precision widened to 12")
        check(column_type.scale == 4, f"{column_name} scale remains 4")


def test_ts_code_mapping():
    from data_collector.sources.financial_report import FinancialReportCollector

    collector = FinancialReportCollector(FakeStorage(), token="dummy")
    check(collector._to_ts_code("600519") == "600519.SH", "SH code mapping")
    check(collector._to_ts_code("300308") == "300308.SZ", "SZ code mapping")
    check(collector._to_ts_code("430047") == "430047.BJ", "BJ code mapping")
    check(collector._to_ts_code("SZ300308") == "300308.SZ", "prefixed SZ code mapping")


def test_tushare_permission_fallback_uses_akshare():
    from data_collector.sources.financial_report import FinancialReportCollector

    async def _run():
        storage = FakeStorage()
        collector = FinancialReportCollector(storage, token="dummy")
        collector._get_pro_api = lambda: object()

        async def denied_income(pro, ts_code, start, end):
            raise RuntimeError("抱歉，您没有接口(income)访问权限")

        collector._fetch_income = denied_income
        attach_fake_akshare(collector)

        result = await collector.collect_batch(["300308"])
        check(result.status == "completed", "Tushare permission failure falls back to AKShare")
        check(result.records_count == 1, "permission fallback writes AKShare record")
        check(any("Tushare unavailable" in item for item in result.warnings), "fallback result keeps Tushare issue")
        check(
            storage.records and storage.records[0]["source"] == "akshare+baidu",
            "permission fallback record source includes valuation source",
        )

    asyncio.run(_run())


def test_akshare_requires_publish_date():
    from data_collector.sources.financial_report import FinancialReportCollector

    async def _run():
        storage = FakeStorage()
        collector = FinancialReportCollector(storage, token="")
        attach_fake_akshare(collector, include_disclosure=False)

        result = await collector.collect_batch(["300308"])
        check(result.status == "failed", "AKShare fallback fails without disclosure publish_date")
        check(not storage.records, "missing publish_date writes no financial records")
        check("300308" in result.errors, "missing publish_date is reported as an error")

    asyncio.run(_run())


def main():
    print("\n" + "=" * 60)
    print(" Phase 7: Financial Ingestion Reliability - Verification")
    print("=" * 60 + "\n")
    test_fallback_without_token_uses_akshare()
    test_record_building()
    test_financial_percentage_precision_allows_extreme_yoy()
    test_ts_code_mapping()
    test_tushare_permission_fallback_uses_akshare()
    test_akshare_requires_publish_date()
    print("=" * 60)
    print(f" Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
