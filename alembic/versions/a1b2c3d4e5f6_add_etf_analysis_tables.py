"""add_etf_analysis_tables

Revision ID: a1b2c3d4e5f6
Revises: e7c9a5d2b4f8
Create Date: 2026-05-15 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "e7c9a5d2b4f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "etf_watch_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("sector", sa.String(50), nullable=True),
        sa.Column("is_holding", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cost_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("target_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("stop_loss_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=True, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_etf_watch_items_code"),
    )
    op.create_index("ix_etf_watch_items_code", "etf_watch_items", ["code"])
    op.create_index("ix_etf_watch_items_sector", "etf_watch_items", ["sector"])
    op.create_index("ix_etf_watch_items_status", "etf_watch_items", ["status"])

    op.create_table(
        "etf_analysis_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(50), nullable=True),
        sa.Column("analysis_time", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("trigger_type", sa.String(20), nullable=True),
        sa.Column("etf_count", sa.Integer(), nullable=True),
        sa.Column("hot_sectors", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("rotation_signals", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("recommendations", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("individual_analysis", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("market_overview", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("llm_used", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("data_gaps", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_etf_analysis_records_task_id", "etf_analysis_records", ["task_id"])
    op.create_index("ix_etf_analysis_records_time", "etf_analysis_records", ["analysis_time"])


def downgrade() -> None:
    op.drop_index("ix_etf_analysis_records_time", table_name="etf_analysis_records")
    op.drop_index("ix_etf_analysis_records_task_id", table_name="etf_analysis_records")
    op.drop_table("etf_analysis_records")

    op.drop_index("ix_etf_watch_items_status", table_name="etf_watch_items")
    op.drop_index("ix_etf_watch_items_sector", table_name="etf_watch_items")
    op.drop_index("ix_etf_watch_items_code", table_name="etf_watch_items")
    op.drop_table("etf_watch_items")
