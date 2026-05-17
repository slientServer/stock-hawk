"""add_etf_daily_klines

Revision ID: b8d7f0c9a2e1
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16 13:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d7f0c9a2e1"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "etf_daily_klines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(12, 4), nullable=True),
        sa.Column("close", sa.Numeric(12, 4), nullable=True),
        sa.Column("high", sa.Numeric(12, 4), nullable=True),
        sa.Column("low", sa.Numeric(12, 4), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.Numeric(16, 2), nullable=True),
        sa.Column("change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("turnover_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "trade_date", name="uq_etf_daily_klines_code_date"),
    )
    op.create_index("ix_etf_daily_klines_code", "etf_daily_klines", ["code"])
    op.create_index("ix_etf_daily_klines_trade_date", "etf_daily_klines", ["trade_date"])
    op.create_index("ix_etf_daily_klines_code_date", "etf_daily_klines", ["code", "trade_date"])


def downgrade() -> None:
    op.drop_index("ix_etf_daily_klines_code_date", table_name="etf_daily_klines")
    op.drop_index("ix_etf_daily_klines_trade_date", table_name="etf_daily_klines")
    op.drop_index("ix_etf_daily_klines_code", table_name="etf_daily_klines")
    op.drop_table("etf_daily_klines")
