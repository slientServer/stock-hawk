"""add_stock_analysis_reports

Revision ID: e7c9a5d2b4f8
Revises: f4a9c2d1b7e3
Create Date: 2026-05-14 19:50:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7c9a5d2b4f8"
down_revision: Union[str, None] = "f4a9c2d1b7e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_analysis_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=True),
        sa.Column("analysis_time", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("latest_trade_date", sa.Date(), nullable=True),
        sa.Column("current_price", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.String(length=10), nullable=True),
        sa.Column("score", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("time_horizon", sa.String(length=20), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("analysis_result", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("input_snapshot", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("data_gaps", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("source_policy", sa.Text(), nullable=True),
        sa.Column("llm_used", sa.Boolean(), nullable=True),
        sa.Column("task_id", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_stock_analysis_reports_action"), "stock_analysis_reports", ["action"], unique=False)
    op.create_index(op.f("ix_stock_analysis_reports_analysis_time"), "stock_analysis_reports", ["analysis_time"], unique=False)
    op.create_index(op.f("ix_stock_analysis_reports_code"), "stock_analysis_reports", ["code"], unique=False)
    op.create_index("ix_stock_analysis_reports_code_time", "stock_analysis_reports", ["code", "analysis_time"], unique=False)
    op.create_index(op.f("ix_stock_analysis_reports_confidence"), "stock_analysis_reports", ["confidence"], unique=False)
    op.create_index(op.f("ix_stock_analysis_reports_latest_trade_date"), "stock_analysis_reports", ["latest_trade_date"], unique=False)
    op.create_index(op.f("ix_stock_analysis_reports_task_id"), "stock_analysis_reports", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stock_analysis_reports_task_id"), table_name="stock_analysis_reports")
    op.drop_index(op.f("ix_stock_analysis_reports_latest_trade_date"), table_name="stock_analysis_reports")
    op.drop_index(op.f("ix_stock_analysis_reports_confidence"), table_name="stock_analysis_reports")
    op.drop_index("ix_stock_analysis_reports_code_time", table_name="stock_analysis_reports")
    op.drop_index(op.f("ix_stock_analysis_reports_code"), table_name="stock_analysis_reports")
    op.drop_index(op.f("ix_stock_analysis_reports_analysis_time"), table_name="stock_analysis_reports")
    op.drop_index(op.f("ix_stock_analysis_reports_action"), table_name="stock_analysis_reports")
    op.drop_table("stock_analysis_reports")
