"""初始化数据采集：从 AKShare 采集真实 A 股数据 + 灌入知识图谱种子"""
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.database import async_session_factory
from common.logger import get_logger
from data_collector.storage import DataStorage
from data_collector.cache.redis_cache import RedisCache
from data_collector.sources.financial_report import FinancialReportCollector
from data_collector.sources.market_basic import StockBasicCollector
from data_collector.sources.market_kline import KlineCollector
from data_collector.sources.fund_flow import FundFlowCollector
from data_collector.sources.shareholder import ShareholderCollector
from knowledge_graph.neo4j_client import Neo4jClient
from knowledge_graph.seed_data import get_all_nodes, get_all_relationships, ALL_CHAINS

logger = get_logger("init_data")

# 3 条产业链涉及的 24 只股票
SEED_CODES = []
for chain in ALL_CHAINS:
    for c in chain["companies"]:
        if c["code"] not in SEED_CODES:
            SEED_CODES.append(c["code"])


async def step_stock_list(storage: DataStorage):
    """Step 1: 采集全 A 股股票列表"""
    logger.info("=" * 60)
    logger.info("Step 1/6: 采集全 A 股股票列表")
    collector = StockBasicCollector(storage)
    count = await collector.collect_stock_list()
    logger.info(f"  -> 完成: {count} 只股票")
    return count


async def step_klines(storage: DataStorage, cache: RedisCache):
    """Step 2: 采集种子股票近 1 年 K 线"""
    logger.info("=" * 60)
    logger.info(f"Step 2/6: 采集 {len(SEED_CODES)} 只种子股票近 1 年 K 线")
    collector = KlineCollector(storage, cache)
    start = date.today() - timedelta(days=365)
    total = await collector.collect_batch(SEED_CODES, start_date=start)
    logger.info(f"  -> 完成: {total} 条 K 线记录")
    return total


async def step_north_flow(storage: DataStorage, cache: RedisCache):
    """Step 3: 采集近 90 天北向资金"""
    logger.info("=" * 60)
    logger.info("Step 3/6: 采集近 90 天北向资金")
    collector = FundFlowCollector(storage, cache)
    start = date.today() - timedelta(days=90)
    count = await collector.collect_north_flow(start_date=start)
    logger.info(f"  -> 完成: {count} 条北向资金记录")
    return count


async def step_shareholder(storage: DataStorage):
    """Step 4: 采集种子股票股东户数"""
    logger.info("=" * 60)
    logger.info(f"Step 4/6: 采集 {len(SEED_CODES)} 只种子股票股东户数")
    collector = ShareholderCollector(storage)
    total = await collector.collect_batch(SEED_CODES)
    logger.info(f"  -> 完成: {total} 条股东户数记录")
    return total


async def step_financial_reports(storage: DataStorage):
    """Step 5: 采集种子股票财报指标"""
    logger.info("=" * 60)
    logger.info(f"Step 5/6: 采集 {len(SEED_CODES)} 只种子股票财报指标（Tushare，需 TUSHARE_TOKEN）")
    collector = FinancialReportCollector(storage)
    result = await collector.collect_batch(SEED_CODES)
    if result.blocking_issues:
        logger.warning(f"  -> 财报采集阻断: {result.blocking_issues}")
    if result.errors:
        logger.warning(f"  -> 财报采集失败股票: {result.errors}")
    if result.warnings:
        logger.warning(f"  -> 财报采集警告: {result.warnings[:5]}")
    logger.info(f"  -> 完成: status={result.status}, records={result.records_count}")
    return result.as_dict()


async def step_knowledge_graph():
    """Step 6: 灌入知识图谱种子数据"""
    logger.info("=" * 60)
    logger.info("Step 6/6: 灌入知识图谱种子数据（3 条产业链 24 家公司）")
    client = await Neo4jClient.get_instance()
    await client.ensure_schema()

    nodes = get_all_nodes()
    for label, items in nodes.items():
        if not items:
            continue
        key_fields = {
            "IndustryChain": ["name"],
            "Segment": ["uid"],
            "Company": ["code"],
            "Technology": ["name"],
            "Product": ["name"],
        }[label]
        count = await client.merge_nodes_batch(label, items, key_fields)
        logger.info(f"  {label}: {count} 个节点")

    rels = get_all_relationships()
    rel_count = await client.merge_relationships_batch(rels)
    logger.info(f"  关系: {rel_count} 条")

    await client.close()
    return rel_count


async def main():
    logger.info("Stock Hawk 初始化数据采集 — 使用 AKShare 真实数据")
    logger.info(f"种子股票: {len(SEED_CODES)} 只")
    logger.info(f"产业链: 光通信 / AI算力 / 新能源车")
    print()

    storage = DataStorage(async_session_factory)
    cache = RedisCache()
    await cache.connect()

    results = {}
    try:
        results["stocks"] = await step_stock_list(storage)
        results["klines"] = await step_klines(storage, cache)
        results["north_flow"] = await step_north_flow(storage, cache)
        results["shareholder"] = await step_shareholder(storage)
        results["financial_reports"] = await step_financial_reports(storage)
        results["kg"] = await step_knowledge_graph()
    finally:
        await cache.close()

    print()
    logger.info("=" * 60)
    logger.info("全部完成！数据汇总:")
    for k, v in results.items():
        logger.info(f"  {k}: {v}")
    logger.info("现在可以访问 http://localhost:3010 查看 Dashboard")


if __name__ == "__main__":
    asyncio.run(main())
