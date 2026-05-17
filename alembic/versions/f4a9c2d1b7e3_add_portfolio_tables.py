"""add_portfolio_tables

Revision ID: f4a9c2d1b7e3
Revises: d9a3b2c7e614
Create Date: 2026-05-11 20:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f4a9c2d1b7e3"
down_revision: Union[str, None] = "d9a3b2c7e614"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("target_price", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("stop_loss_price", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("opened_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_portfolio_positions_code"), "portfolio_positions", ["code"], unique=False)
    op.create_index("ix_portfolio_positions_code_status", "portfolio_positions", ["code", "status"], unique=False)
    op.create_index(op.f("ix_portfolio_positions_status"), "portfolio_positions", ["status"], unique=False)

    op.create_table(
        "portfolio_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("position_id", sa.BigInteger(), nullable=True),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("amount", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("realized_profit", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("before_snapshot", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("after_snapshot", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_portfolio_transactions_action"), "portfolio_transactions", ["action"], unique=False)
    op.create_index(op.f("ix_portfolio_transactions_code"), "portfolio_transactions", ["code"], unique=False)
    op.create_index(op.f("ix_portfolio_transactions_created_at"), "portfolio_transactions", ["created_at"], unique=False)
    op.create_index(op.f("ix_portfolio_transactions_position_id"), "portfolio_transactions", ["position_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_portfolio_transactions_position_id"), table_name="portfolio_transactions")
    op.drop_index(op.f("ix_portfolio_transactions_created_at"), table_name="portfolio_transactions")
    op.drop_index(op.f("ix_portfolio_transactions_code"), table_name="portfolio_transactions")
    op.drop_index(op.f("ix_portfolio_transactions_action"), table_name="portfolio_transactions")
    op.drop_table("portfolio_transactions")
    op.drop_index(op.f("ix_portfolio_positions_status"), table_name="portfolio_positions")
    op.drop_index("ix_portfolio_positions_code_status", table_name="portfolio_positions")
    op.drop_index(op.f("ix_portfolio_positions_code"), table_name="portfolio_positions")
    op.drop_table("portfolio_positions")
