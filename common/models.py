from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Stock(Base):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(50))
    industry: Mapped[str | None] = mapped_column(String(50))
    market: Mapped[str | None] = mapped_column(String(10))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric)
    listed_date: Mapped[date | None] = mapped_column(Date)
    is_st: Mapped[bool | None] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_stocks_industry", "industry"),
        Index("ix_stocks_market", "market"),
    )


class DailyKline(Base):
    __tablename__ = "daily_klines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    source: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uq_daily_klines_code_date"),
        Index("ix_daily_klines_code_date", "code", "trade_date"),
    )


class TechnicalIndicator(Base):
    __tablename__ = "technical_indicators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    macd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    macd_signal: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    macd_hist: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    kdj_k: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    kdj_d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    kdj_j: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    rsi_6: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    rsi_12: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    rsi_24: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    boll_upper: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    boll_mid: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    boll_lower: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uq_technical_indicators_code_date"),
        Index("ix_technical_indicators_code_date", "code", "trade_date"),
    )


class FinancialReport(Base):
    __tablename__ = "financial_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    report_date: Mapped[date] = mapped_column(Date)
    publish_date: Mapped[date | None] = mapped_column(Date)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    revenue_yoy: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    net_profit: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    net_profit_yoy: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    gross_margin: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    roe: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    pe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    pb_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    source: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("code", "report_date", name="uq_financial_reports_code_report_date"),
        Index("ix_financial_reports_code_report_date", "code", "report_date"),
    )


class FundFlow(Base):
    __tablename__ = "fund_flows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    north_buy: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    north_sell: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    north_net: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    source: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("trade_date", name="uq_fund_flows_trade_date"),
    )


class StockFundFlow(Base):
    __tablename__ = "stock_fund_flows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(String(10), index=True)
    trade_date: Mapped[date | None] = mapped_column(Date, index=True)
    reason: Mapped[str | None] = mapped_column(String(200))
    buy_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    sell_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    source: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ShareholderCount(Base):
    __tablename__ = "shareholder_counts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    end_date: Mapped[date] = mapped_column(Date)
    holder_count: Mapped[int | None] = mapped_column(Integer)
    holder_count_change: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    avg_holding: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    source: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("code", "end_date", name="uq_shareholder_counts_code_end_date"),
        Index("ix_shareholder_counts_code_end_date", "code", "end_date"),
    )


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_type: Mapped[str | None] = mapped_column(String(30), index=True)
    chain_id: Mapped[str | None] = mapped_column(String(50), index=True)
    source_entity: Mapped[str | None] = mapped_column(String(100))
    target_codes: Mapped[dict | None] = mapped_column(JSON)
    strength: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    detail: Mapped[str | None] = mapped_column(Text)
    raw_data_ref: Mapped[str | None] = mapped_column(String(200))
    trigger_date: Mapped[datetime | None] = mapped_column(DateTime)
    expire_date: Mapped[datetime | None] = mapped_column(DateTime)
    source: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


class ChainScore(Base):
    __tablename__ = "chain_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_id: Mapped[str] = mapped_column(String(50), index=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    score_detail: Mapped[dict | None] = mapped_column(JSON)
    signal_count: Mapped[int | None] = mapped_column(Integer)
    score_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("chain_id", "score_date", name="uq_chain_scores_chain_id_score_date"),
        Index("ix_chain_scores_chain_id_score_date", "chain_id", "score_date"),
    )


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(String(50), index=True)
    signal_type: Mapped[str | None] = mapped_column(String(30))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    total_signals: Mapped[int | None] = mapped_column(Integer)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    avg_return_30d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    avg_return_60d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    avg_return_90d: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    result_detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


class CollectLog(Base):
    __tablename__ = "collect_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str | None] = mapped_column(String(50), index=True)
    task_type: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str | None] = mapped_column(String(20))
    records_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[str | None] = mapped_column(String(50), index=True)
    task_id: Mapped[str | None] = mapped_column(String(50), index=True)
    workflow_type: Mapped[str | None] = mapped_column(String(30))
    input_data: Mapped[dict | None] = mapped_column(JSON)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    llm_response: Mapped[str | None] = mapped_column(Text)
    output_data: Mapped[dict | None] = mapped_column(JSON)
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


class CommodityPrice(Base):
    __tablename__ = "commodity_prices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_name: Mapped[str] = mapped_column(String(100), index=True)
    price_date: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(16, 4))
    price_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    inventory: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    chain_id: Mapped[str | None] = mapped_column(String(50), index=True)
    is_manual: Mapped[bool | None] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("product_name", "price_date", name="uq_commodity_prices_product_date"),
        Index("ix_commodity_prices_product_date", "product_name", "price_date"),
    )


class NewsEvent(Base):
    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str | None] = mapped_column(Text)
    publish_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str | None] = mapped_column(String(50))
    related_codes: Mapped[dict | None] = mapped_column(JSON)
    event_type: Mapped[str | None] = mapped_column(String(30), index=True)
    sentiment: Mapped[str | None] = mapped_column(String(10))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("title", "publish_time", name="uq_news_events_title_time"),
        Index("ix_news_events_publish_time", "publish_time"),
    )


class OverseasStock(Base):
    __tablename__ = "overseas_stocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str | None] = mapped_column(String(100))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    source: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "trade_date", name="uq_overseas_stocks_symbol_date"),
        Index("ix_overseas_stocks_symbol_date", "symbol", "trade_date"),
    )


class OverseasMapping(Base):
    __tablename__ = "overseas_mappings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    a_code: Mapped[str] = mapped_column(String(10), index=True)
    overseas_symbol: Mapped[str] = mapped_column(String(20), index=True)
    a_name: Mapped[str | None] = mapped_column(String(50))
    overseas_name: Mapped[str | None] = mapped_column(String(100))
    relation_type: Mapped[str | None] = mapped_column(String(30))
    chain_id: Mapped[str | None] = mapped_column(String(50))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("a_code", "overseas_symbol", name="uq_overseas_mappings_a_overseas"),
    )


class StockMainFlow(Base):
    __tablename__ = "stock_main_flows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    main_net: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    main_buy: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    main_sell: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    retail_net: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    main_net_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    source: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uq_stock_main_flows_code_date"),
        Index("ix_stock_main_flows_code_date", "code", "trade_date"),
    )


class StockAnalysisReport(Base):
    __tablename__ = "stock_analysis_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str | None] = mapped_column(String(50))
    analysis_time: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), index=True)
    latest_trade_date: Mapped[date | None] = mapped_column(Date, index=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    action: Mapped[str | None] = mapped_column(String(20), index=True)
    confidence: Mapped[str | None] = mapped_column(String(10), index=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    time_horizon: Mapped[str | None] = mapped_column(String(20))
    summary: Mapped[str | None] = mapped_column(Text)
    analysis_result: Mapped[dict | None] = mapped_column(JSON)
    input_snapshot: Mapped[dict | None] = mapped_column(JSON)
    data_gaps: Mapped[list | None] = mapped_column(JSON)
    source_policy: Mapped[str | None] = mapped_column(Text)
    llm_used: Mapped[bool | None] = mapped_column(Boolean, default=False)
    task_id: Mapped[str | None] = mapped_column(String(50), index=True)

    __table_args__ = (
        Index("ix_stock_analysis_reports_code_time", "code", "analysis_time"),
    )


class InstitutionalHolding(Base):
    __tablename__ = "institutional_holdings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    institution_name: Mapped[str | None] = mapped_column(String(200))
    hold_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    hold_change: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    hold_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    source: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("code", "report_date", "institution_name", name="uq_institutional_holdings_code_date_inst"),
        Index("ix_institutional_holdings_code_date", "code", "report_date"),
    )


class EodScreenResult(Base):
    __tablename__ = "eod_screen_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    name: Mapped[str | None] = mapped_column(String(50))
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    volume_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    late_strength: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    rank: Mapped[int | None] = mapped_column(Integer)
    signal_strength: Mapped[str | None] = mapped_column(String(10))
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    stop_loss_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    suggestion: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str | None] = mapped_column(String(20))
    quote_source: Mapped[str | None] = mapped_column(String(50))
    quote_time: Mapped[datetime | None] = mapped_column(DateTime)
    backtest_start_date: Mapped[date | None] = mapped_column(Date)
    backtest_end_date: Mapped[date | None] = mapped_column(Date)
    backtest_total_trades: Mapped[int | None] = mapped_column(Integer)
    backtest_win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    backtest_avg_return: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    backtest_max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    backtest_profit_loss_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    backtest_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    config_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uq_eod_screen_results_code_date"),
        Index("ix_eod_screen_results_date_score", "trade_date", "score"),
        Index("ix_eod_screen_results_date_backtest", "trade_date", "backtest_score"),
    )


class EodBacktestResult(Base):
    __tablename__ = "eod_backtest_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(String(50), index=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    total_trades: Mapped[int | None] = mapped_column(Integer)
    win_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    avg_return: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    max_drawdown: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    profit_loss_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    config_snapshot: Mapped[dict | None] = mapped_column(JSON)
    result_detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())


class PortfolioPosition(Base):
    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer, default=100)
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    stop_loss_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    status: Mapped[str | None] = mapped_column(String(20), default="active", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_portfolio_positions_code_status", "code", "status"),
    )


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    position_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    action: Mapped[str] = mapped_column(String(30), index=True)
    quantity: Mapped[int | None] = mapped_column(Integer)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    realized_profit: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    note: Mapped[str | None] = mapped_column(Text)
    before_snapshot: Mapped[dict | None] = mapped_column(JSON)
    after_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), index=True)


class EtfWatchItem(Base):
    __tablename__ = "etf_watch_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str | None] = mapped_column(String(100))
    sector: Mapped[str | None] = mapped_column(String(50), index=True)
    is_holding: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    quantity: Mapped[int | None] = mapped_column(Integer)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    stop_loss_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("code", name="uq_etf_watch_items_code"),
        Index("ix_etf_watch_items_sector", "sector"),
    )


class EtfDailyKline(Base):
    __tablename__ = "etf_daily_klines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(16, 2))
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    turnover_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    source: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uq_etf_daily_klines_code_date"),
        Index("ix_etf_daily_klines_code_date", "code", "trade_date"),
    )


class EtfAnalysisRecord(Base):
    __tablename__ = "etf_analysis_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(String(50), index=True)
    analysis_time: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), index=True)
    trigger_type: Mapped[str | None] = mapped_column(String(20))
    etf_count: Mapped[int | None] = mapped_column(Integer)
    hot_sectors: Mapped[dict | None] = mapped_column(JSON)
    rotation_signals: Mapped[dict | None] = mapped_column(JSON)
    recommendations: Mapped[dict | None] = mapped_column(JSON)
    individual_analysis: Mapped[dict | None] = mapped_column(JSON)
    market_overview: Mapped[dict | None] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text)
    llm_used: Mapped[bool | None] = mapped_column(Boolean, default=False)
    data_gaps: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_etf_analysis_records_time", "analysis_time"),
    )
