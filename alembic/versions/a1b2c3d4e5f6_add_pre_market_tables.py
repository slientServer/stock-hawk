"""add_pre_market_tables"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c6d8f1a2b3e4"
down_revision: Union[str, None] = "f2c9e8a7b6d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sector_catalysts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("sector_name", sa.String(100), nullable=True),
        sa.Column("catalyst_strength", sa.Integer(), nullable=True),
        sa.Column("catalyst_type", sa.String(50), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("related_news_ids", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("related_codes", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_used", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "sector_name", name="uq_sector_catalysts_date_sector"),
    )
    op.create_index("ix_sector_catalysts_trade_date", "sector_catalysts", ["trade_date"])

    op.create_table(
        "pre_market_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=True),
        sa.Column("result_type", sa.String(20), nullable=True),
        sa.Column("code", sa.String(10), nullable=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("close_price", sa.Numeric(12, 4), nullable=True),
        # 激进标专用
        sa.Column("change_pct_5d", sa.Numeric(8, 4), nullable=True),
        sa.Column("change_pct_1d", sa.Numeric(8, 4), nullable=True),
        sa.Column("turnover_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("volume_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("market_cap", sa.Numeric(16, 2), nullable=True),
        sa.Column("main_net_1d", sa.Numeric(16, 2), nullable=True),
        sa.Column("main_net_3d", sa.Numeric(16, 2), nullable=True),
        sa.Column("above_ma5", sa.Boolean(), nullable=True),
        sa.Column("catalyst_sector", sa.String(100), nullable=True),
        sa.Column("catalyst_strength", sa.Integer(), nullable=True),
        # 稳健标专用
        sa.Column("change_pct_3d", sa.Numeric(8, 4), nullable=True),
        sa.Column("ma5_direction", sa.String(10), nullable=True),
        sa.Column("ma5_deviation", sa.Numeric(8, 4), nullable=True),
        sa.Column("amount_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("avg_amplitude", sa.Numeric(8, 4), nullable=True),
        # 共有字段
        sa.Column("score", sa.Numeric(6, 2), nullable=True),
        sa.Column("score_detail", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("target_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("stop_loss_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("suggestion", sa.Text(), nullable=True),
        # 绩效追踪
        sa.Column("actual_return_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("actual_exit_date", sa.Date(), nullable=True),
        sa.Column("actual_exit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("exit_type", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "trade_date", "result_type", name="uq_pre_market_results_code_date_type"),
    )
    op.create_index("ix_pre_market_results_trade_date", "pre_market_results", ["trade_date"])
    op.create_index("ix_pre_market_results_code", "pre_market_results", ["code"])
    op.create_index("ix_pre_market_results_date_type", "pre_market_results", ["trade_date", "result_type"])
    op.create_index("ix_pre_market_results_date_score", "pre_market_results", ["trade_date", "score"])
    op.create_index("ix_pre_market_results_exit_type", "pre_market_results", ["exit_type"])


def downgrade() -> None:
    op.drop_index("ix_pre_market_results_exit_type", table_name="pre_market_results")
    op.drop_index("ix_pre_market_results_date_score", table_name="pre_market_results")
    op.drop_index("ix_pre_market_results_date_type", table_name="pre_market_results")
    op.drop_index("ix_pre_market_results_code", table_name="pre_market_results")
    op.drop_index("ix_pre_market_results_trade_date", table_name="pre_market_results")
    op.drop_table("pre_market_results")

    op.drop_index("ix_sector_catalysts_trade_date", table_name="sector_catalysts")
    op.drop_table("sector_catalysts")
