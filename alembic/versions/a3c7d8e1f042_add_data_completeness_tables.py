"""add data completeness tables

Revision ID: a3c7d8e1f042
Revises: 8e2f7c3b9a41
Create Date: 2026-05-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = "a3c7d8e1f042"
down_revision = "8e2f7c3b9a41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- stocks: add listed_date ---
    op.add_column("stocks", sa.Column("listed_date", sa.Date(), nullable=True))

    # --- commodity_prices ---
    op.create_table(
        "commodity_prices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_name", sa.String(100), nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(16, 4), nullable=True),
        sa.Column("price_change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("inventory", sa.Numeric(16, 2), nullable=True),
        sa.Column("chain_id", sa.String(50), nullable=True),
        sa.Column("is_manual", sa.Boolean(), nullable=True, server_default="false"),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_name", "price_date", name="uq_commodity_prices_product_date"),
    )
    op.create_index("ix_commodity_prices_product_name", "commodity_prices", ["product_name"])
    op.create_index("ix_commodity_prices_price_date", "commodity_prices", ["price_date"])
    op.create_index("ix_commodity_prices_product_date", "commodity_prices", ["product_name", "price_date"])
    op.create_index("ix_commodity_prices_chain_id", "commodity_prices", ["chain_id"])

    # --- news_events ---
    op.create_table(
        "news_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("publish_time", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("related_codes", JSON, nullable=True),
        sa.Column("event_type", sa.String(30), nullable=True),
        sa.Column("sentiment", sa.String(10), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title", "publish_time", name="uq_news_events_title_time"),
    )
    op.create_index("ix_news_events_publish_time", "news_events", ["publish_time"])
    op.create_index("ix_news_events_event_type", "news_events", ["event_type"])

    # --- overseas_stocks ---
    op.create_table(
        "overseas_stocks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(12, 4), nullable=True),
        sa.Column("close", sa.Numeric(12, 4), nullable=True),
        sa.Column("high", sa.Numeric(12, 4), nullable=True),
        sa.Column("low", sa.Numeric(12, 4), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "trade_date", name="uq_overseas_stocks_symbol_date"),
    )
    op.create_index("ix_overseas_stocks_symbol", "overseas_stocks", ["symbol"])
    op.create_index("ix_overseas_stocks_trade_date", "overseas_stocks", ["trade_date"])
    op.create_index("ix_overseas_stocks_symbol_date", "overseas_stocks", ["symbol", "trade_date"])

    # --- overseas_mappings ---
    op.create_table(
        "overseas_mappings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("a_code", sa.String(10), nullable=False),
        sa.Column("overseas_symbol", sa.String(20), nullable=False),
        sa.Column("a_name", sa.String(50), nullable=True),
        sa.Column("overseas_name", sa.String(100), nullable=True),
        sa.Column("relation_type", sa.String(30), nullable=True),
        sa.Column("chain_id", sa.String(50), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("a_code", "overseas_symbol", name="uq_overseas_mappings_a_overseas"),
    )
    op.create_index("ix_overseas_mappings_a_code", "overseas_mappings", ["a_code"])
    op.create_index("ix_overseas_mappings_overseas_symbol", "overseas_mappings", ["overseas_symbol"])

    # --- institutional_holdings ---
    op.create_table(
        "institutional_holdings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("institution_name", sa.String(200), nullable=True),
        sa.Column("hold_amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("hold_change", sa.Numeric(16, 2), nullable=True),
        sa.Column("hold_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "report_date", "institution_name", name="uq_institutional_holdings_code_date_inst"),
    )
    op.create_index("ix_institutional_holdings_code", "institutional_holdings", ["code"])
    op.create_index("ix_institutional_holdings_report_date", "institutional_holdings", ["report_date"])
    op.create_index("ix_institutional_holdings_code_date", "institutional_holdings", ["code", "report_date"])


def downgrade() -> None:
    op.drop_table("institutional_holdings")
    op.drop_table("overseas_mappings")
    op.drop_table("overseas_stocks")
    op.drop_table("news_events")
    op.drop_table("commodity_prices")
    op.drop_column("stocks", "listed_date")
