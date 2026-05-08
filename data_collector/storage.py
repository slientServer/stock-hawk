from datetime import datetime
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.models import (
    AgentLog,
    CollectLog,
    FundFlow,
    Signal,
    StockFundFlow,
)


class DataStorage:
    """统一的数据存储接口，封装PG写入操作"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def upsert_daily_klines(self, records: list[dict]):
        """批量写入日K线（INSERT ON CONFLICT DO UPDATE）"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO daily_klines (code, trade_date, open, close, high, low, volume, amount, turnover_rate, source, updated_at)
                VALUES (:code, :trade_date, :open, :close, :high, :low, :volume, :amount, :turnover_rate, :source, :updated_at)
                ON CONFLICT (code, trade_date) DO UPDATE SET
                    open = EXCLUDED.open,
                    close = EXCLUDED.close,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    volume = EXCLUDED.volume,
                    amount = EXCLUDED.amount,
                    turnover_rate = EXCLUDED.turnover_rate,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def upsert_technical_indicators(self, records: list[dict]):
        """批量写入技术指标"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO technical_indicators (code, trade_date, macd, macd_signal, macd_hist,
                    kdj_k, kdj_d, kdj_j, rsi_6, rsi_12, rsi_24,
                    boll_upper, boll_mid, boll_lower, updated_at)
                VALUES (:code, :trade_date, :macd, :macd_signal, :macd_hist,
                    :kdj_k, :kdj_d, :kdj_j, :rsi_6, :rsi_12, :rsi_24,
                    :boll_upper, :boll_mid, :boll_lower, :updated_at)
                ON CONFLICT (code, trade_date) DO UPDATE SET
                    macd = EXCLUDED.macd,
                    macd_signal = EXCLUDED.macd_signal,
                    macd_hist = EXCLUDED.macd_hist,
                    kdj_k = EXCLUDED.kdj_k,
                    kdj_d = EXCLUDED.kdj_d,
                    kdj_j = EXCLUDED.kdj_j,
                    rsi_6 = EXCLUDED.rsi_6,
                    rsi_12 = EXCLUDED.rsi_12,
                    rsi_24 = EXCLUDED.rsi_24,
                    boll_upper = EXCLUDED.boll_upper,
                    boll_mid = EXCLUDED.boll_mid,
                    boll_lower = EXCLUDED.boll_lower,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def upsert_stock_basic(self, records: list[dict]):
        """批量写入股票基本信息"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO stocks (code, name, industry, market, market_cap, listed_date, is_st, updated_at)
                VALUES (:code, :name, :industry, :market, :market_cap, :listed_date, :is_st, :updated_at)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    industry = COALESCE(EXCLUDED.industry, stocks.industry),
                    market = EXCLUDED.market,
                    market_cap = COALESCE(EXCLUDED.market_cap, stocks.market_cap),
                    listed_date = COALESCE(EXCLUDED.listed_date, stocks.listed_date),
                    is_st = EXCLUDED.is_st,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("listed_date", None)
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def upsert_financial_reports(self, records: list[dict]):
        """批量写入财报指标（必须保留 publish_date，避免信号前视）"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO financial_reports (
                    code, report_date, publish_date, revenue, revenue_yoy,
                    net_profit, net_profit_yoy, gross_margin, roe,
                    pe_ratio, pb_ratio, source, updated_at
                )
                VALUES (
                    :code, :report_date, :publish_date, :revenue, :revenue_yoy,
                    :net_profit, :net_profit_yoy, :gross_margin, :roe,
                    :pe_ratio, :pb_ratio, :source, :updated_at
                )
                ON CONFLICT (code, report_date) DO UPDATE SET
                    publish_date = EXCLUDED.publish_date,
                    revenue = EXCLUDED.revenue,
                    revenue_yoy = EXCLUDED.revenue_yoy,
                    net_profit = EXCLUDED.net_profit,
                    net_profit_yoy = EXCLUDED.net_profit_yoy,
                    gross_margin = EXCLUDED.gross_margin,
                    roe = EXCLUDED.roe,
                    pe_ratio = EXCLUDED.pe_ratio,
                    pb_ratio = EXCLUDED.pb_ratio,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            optional_fields = (
                "publish_date",
                "revenue",
                "revenue_yoy",
                "net_profit",
                "net_profit_yoy",
                "gross_margin",
                "roe",
                "pe_ratio",
                "pb_ratio",
                "source",
            )
            for record in records:
                for field in optional_fields:
                    record.setdefault(field, None)
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def insert_fund_flow(self, record: dict):
        """写入或更新北向资金。"""
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO fund_flows (trade_date, north_buy, north_sell, north_net, source, updated_at)
                VALUES (:trade_date, :north_buy, :north_sell, :north_net, :source, :updated_at)
                ON CONFLICT (trade_date) DO UPDATE SET
                    north_buy = EXCLUDED.north_buy,
                    north_sell = EXCLUDED.north_sell,
                    north_net = EXCLUDED.north_net,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """)
            await session.execute(
                stmt,
                {
                    "trade_date": record["trade_date"],
                    "north_buy": record.get("north_buy"),
                    "north_sell": record.get("north_sell"),
                    "north_net": record.get("north_net"),
                    "source": record.get("source"),
                    "updated_at": datetime.now(),
                },
            )
            await session.commit()

    async def insert_signal(self, signal: dict):
        """写入信号记录"""
        async with self.session_factory() as session:
            obj = Signal(
                signal_type=signal.get("signal_type"),
                chain_id=signal.get("chain_id"),
                source_entity=signal.get("source_entity"),
                target_codes=signal.get("target_codes"),
                strength=signal.get("strength"),
                confidence=signal.get("confidence"),
                detail=signal.get("detail"),
                raw_data_ref=signal.get("raw_data_ref"),
                trigger_date=signal.get("trigger_date"),
                expire_date=signal.get("expire_date"),
                source=signal.get("source"),
            )
            session.add(obj)
            await session.commit()

    async def insert_collect_log(self, log: dict):
        """写入采集日志"""
        async with self.session_factory() as session:
            obj = CollectLog(
                source=log.get("source"),
                task_type=log.get("task_type"),
                status=log.get("status"),
                records_count=log.get("records_count"),
                error_message=log.get("error_message"),
                started_at=log.get("started_at"),
                finished_at=log.get("finished_at"),
            )
            session.add(obj)
            await session.commit()

    async def insert_agent_log(self, log: dict):
        """写入Agent日志"""
        async with self.session_factory() as session:
            obj = AgentLog(
                agent_id=log.get("agent_id"),
                task_id=log.get("task_id"),
                workflow_type=log.get("workflow_type"),
                input_data=log.get("input_data"),
                prompt_text=log.get("prompt_text"),
                llm_response=log.get("llm_response"),
                output_data=log.get("output_data"),
                tokens_used=log.get("tokens_used"),
                duration_ms=log.get("duration_ms"),
                status=log.get("status"),
                error_message=log.get("error_message"),
            )
            session.add(obj)
            await session.commit()

    async def upsert_shareholder_counts(self, records: list[dict]):
        """批量写入股东户数（INSERT ON CONFLICT DO UPDATE）"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO shareholder_counts (code, end_date, holder_count, holder_count_change, avg_holding, source, updated_at)
                VALUES (:code, :end_date, :holder_count, :holder_count_change, :avg_holding, :source, :updated_at)
                ON CONFLICT (code, end_date) DO UPDATE SET
                    holder_count = EXCLUDED.holder_count,
                    holder_count_change = EXCLUDED.holder_count_change,
                    avg_holding = EXCLUDED.avg_holding,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def insert_stock_fund_flows(self, records: list[dict]):
        """批量写入龙虎榜数据"""
        if not records:
            return
        async with self.session_factory() as session:
            for record in records:
                obj = StockFundFlow(
                    code=record.get("code"),
                    trade_date=record.get("trade_date"),
                    reason=record.get("reason"),
                    buy_amount=record.get("buy_amount"),
                    sell_amount=record.get("sell_amount"),
                    net_amount=record.get("net_amount"),
                    source=record.get("source", "akshare"),
                )
                session.add(obj)
            await session.commit()

    async def upsert_commodity_prices(self, records: list[dict]):
        """批量写入商品价格"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO commodity_prices (product_name, price_date, price, price_change_pct, inventory, chain_id, is_manual, source, updated_at)
                VALUES (:product_name, :price_date, :price, :price_change_pct, :inventory, :chain_id, :is_manual, :source, :updated_at)
                ON CONFLICT (product_name, price_date) DO UPDATE SET
                    price = EXCLUDED.price,
                    price_change_pct = EXCLUDED.price_change_pct,
                    inventory = COALESCE(EXCLUDED.inventory, commodity_prices.inventory),
                    chain_id = COALESCE(EXCLUDED.chain_id, commodity_prices.chain_id),
                    is_manual = EXCLUDED.is_manual,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("inventory", None)
                record.setdefault("chain_id", None)
                record.setdefault("is_manual", False)
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def upsert_news_events(self, records: list[dict]):
        """批量写入新闻事件"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO news_events (title, content, publish_time, source, related_codes, event_type, sentiment, updated_at)
                VALUES (:title, :content, :publish_time, :source, :related_codes, :event_type, :sentiment, :updated_at)
                ON CONFLICT (title, publish_time) DO UPDATE SET
                    content = COALESCE(EXCLUDED.content, news_events.content),
                    related_codes = COALESCE(EXCLUDED.related_codes, news_events.related_codes),
                    event_type = COALESCE(EXCLUDED.event_type, news_events.event_type),
                    sentiment = COALESCE(EXCLUDED.sentiment, news_events.sentiment),
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("content", None)
                record.setdefault("related_codes", None)
                record.setdefault("event_type", None)
                record.setdefault("sentiment", None)
                record.setdefault("updated_at", now)
                if record.get("related_codes") is not None and not isinstance(record["related_codes"], str):
                    record["related_codes"] = json.dumps(record["related_codes"], ensure_ascii=False)
            await session.execute(stmt, records)
            await session.commit()

    async def upsert_overseas_stocks(self, records: list[dict]):
        """批量写入海外股票行情"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO overseas_stocks (symbol, name, trade_date, open, close, high, low, volume, change_pct, source, updated_at)
                VALUES (:symbol, :name, :trade_date, :open, :close, :high, :low, :volume, :change_pct, :source, :updated_at)
                ON CONFLICT (symbol, trade_date) DO UPDATE SET
                    name = COALESCE(EXCLUDED.name, overseas_stocks.name),
                    open = EXCLUDED.open,
                    close = EXCLUDED.close,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    volume = EXCLUDED.volume,
                    change_pct = EXCLUDED.change_pct,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("name", None)
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def upsert_overseas_mappings(self, records: list[dict]):
        """批量写入海外映射关系"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO overseas_mappings (a_code, overseas_symbol, a_name, overseas_name, relation_type, chain_id, confidence, updated_at)
                VALUES (:a_code, :overseas_symbol, :a_name, :overseas_name, :relation_type, :chain_id, :confidence, :updated_at)
                ON CONFLICT (a_code, overseas_symbol) DO UPDATE SET
                    a_name = COALESCE(EXCLUDED.a_name, overseas_mappings.a_name),
                    overseas_name = COALESCE(EXCLUDED.overseas_name, overseas_mappings.overseas_name),
                    relation_type = COALESCE(EXCLUDED.relation_type, overseas_mappings.relation_type),
                    chain_id = COALESCE(EXCLUDED.chain_id, overseas_mappings.chain_id),
                    confidence = COALESCE(EXCLUDED.confidence, overseas_mappings.confidence),
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("a_name", None)
                record.setdefault("overseas_name", None)
                record.setdefault("relation_type", None)
                record.setdefault("chain_id", None)
                record.setdefault("confidence", None)
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def upsert_stock_main_flows(self, records: list[dict]):
        """批量写入个股主力资金流"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO stock_main_flows (code, trade_date, main_net, main_buy, main_sell, retail_net, main_net_pct, source, updated_at)
                VALUES (:code, :trade_date, :main_net, :main_buy, :main_sell, :retail_net, :main_net_pct, :source, :updated_at)
                ON CONFLICT (code, trade_date) DO UPDATE SET
                    main_net = EXCLUDED.main_net,
                    main_buy = EXCLUDED.main_buy,
                    main_sell = EXCLUDED.main_sell,
                    retail_net = EXCLUDED.retail_net,
                    main_net_pct = EXCLUDED.main_net_pct,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()

    async def upsert_institutional_holdings(self, records: list[dict]):
        """批量写入机构持仓"""
        if not records:
            return
        async with self.session_factory() as session:
            stmt = text("""
                INSERT INTO institutional_holdings (code, report_date, institution_name, hold_amount, hold_change, hold_ratio, source, updated_at)
                VALUES (:code, :report_date, :institution_name, :hold_amount, :hold_change, :hold_ratio, :source, :updated_at)
                ON CONFLICT (code, report_date, institution_name) DO UPDATE SET
                    hold_amount = EXCLUDED.hold_amount,
                    hold_change = EXCLUDED.hold_change,
                    hold_ratio = EXCLUDED.hold_ratio,
                    source = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now()
            for record in records:
                record.setdefault("hold_change", None)
                record.setdefault("hold_ratio", None)
                record.setdefault("updated_at", now)
            await session.execute(stmt, records)
            await session.commit()