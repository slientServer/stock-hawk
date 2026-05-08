"""add stock_main_flows table

Revision ID: b5d2e9f14a73
Revises: a3c7d8e1f042
Create Date: 2026-05-08

"""

from alembic import op
import sqlalchemy as sa

revision = "b5d2e9f14a73"
down_revision = "a3c7d8e1f042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_main_flows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("main_net", sa.Numeric(16, 2), nullable=True),
        sa.Column("main_buy", sa.Numeric(16, 2), nullable=True),
        sa.Column("main_sell", sa.Numeric(16, 2), nullable=True),
        sa.Column("retail_net", sa.Numeric(16, 2), nullable=True),
        sa.Column("main_net_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "trade_date", name="uq_stock_main_flows_code_date"),
    )
    op.create_index("ix_stock_main_flows_code", "stock_main_flows", ["code"])
    op.create_index("ix_stock_main_flows_trade_date", "stock_main_flows", ["trade_date"])
    op.create_index("ix_stock_main_flows_code_date", "stock_main_flows", ["code", "trade_date"])


def downgrade() -> None:
    op.drop_index("ix_stock_main_flows_code_date", table_name="stock_main_flows")
    op.drop_index("ix_stock_main_flows_trade_date", table_name="stock_main_flows")
    op.drop_index("ix_stock_main_flows_code", table_name="stock_main_flows")
    op.drop_table("stock_main_flows")
