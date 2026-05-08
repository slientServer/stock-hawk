"""刷新财报指标。

默认刷新知识图谱种子股票；传入 --codes 可指定代码列表。缺 TUSHARE_TOKEN 时会显式返回 blocked。
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.database import async_session_factory
from common.logger import get_logger
from data_collector.sources.financial_report import FinancialReportCollector
from data_collector.storage import DataStorage
from knowledge_graph.seed_data import ALL_CHAINS

logger = get_logger("refresh_financial_reports")


def _seed_codes() -> list[str]:
    codes: list[str] = []
    for chain in ALL_CHAINS:
        for company in chain["companies"]:
            code = company["code"]
            if code not in codes:
                codes.append(code)
    return codes


def _parse_codes(value: str | None) -> list[str]:
    if not value:
        return _seed_codes()
    return [item.strip() for item in value.split(",") if item.strip()]


async def main():
    parser = argparse.ArgumentParser(description="Refresh Tushare financial reports")
    parser.add_argument("--codes", help="逗号分隔股票代码，如 300308,300502；默认使用种子股票")
    parser.add_argument("--years", type=int, default=3, help="采集年数，默认 3")
    args = parser.parse_args()

    codes = _parse_codes(args.codes)
    storage = DataStorage(async_session_factory)
    collector = FinancialReportCollector(storage)
    result = await collector.collect_batch(codes, years=args.years)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, default=str))

    if result.status in ("blocked", "failed"):
        logger.error(f"财报刷新未完成: status={result.status}")
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
