"""add_eod_screen_backtest_columns

Revision ID: c2e8a4f6b901
Revises: b75bebde1c4c
Create Date: 2026-05-11 16:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2e8a4f6b901"
down_revision: Union[str, None] = "b75bebde1c4c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("eod_screen_results", sa.Column("backtest_start_date", sa.Date(), nullable=True))
    op.add_column("eod_screen_results", sa.Column("backtest_end_date", sa.Date(), nullable=True))
    op.add_column("eod_screen_results", sa.Column("backtest_total_trades", sa.Integer(), nullable=True))
    op.add_column("eod_screen_results", sa.Column("backtest_win_rate", sa.Numeric(precision=6, scale=4), nullable=True))
    op.add_column("eod_screen_results", sa.Column("backtest_avg_return", sa.Numeric(precision=8, scale=4), nullable=True))
    op.add_column("eod_screen_results", sa.Column("backtest_max_drawdown", sa.Numeric(precision=8, scale=4), nullable=True))
    op.add_column(
        "eod_screen_results",
        sa.Column("backtest_profit_loss_ratio", sa.Numeric(precision=8, scale=4), nullable=True),
    )
    op.add_column("eod_screen_results", sa.Column("backtest_score", sa.Numeric(precision=6, scale=2), nullable=True))
    op.create_index(
        "ix_eod_screen_results_date_backtest",
        "eod_screen_results",
        ["trade_date", "backtest_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_eod_screen_results_date_backtest", table_name="eod_screen_results")
    op.drop_column("eod_screen_results", "backtest_score")
    op.drop_column("eod_screen_results", "backtest_profit_loss_ratio")
    op.drop_column("eod_screen_results", "backtest_max_drawdown")
    op.drop_column("eod_screen_results", "backtest_avg_return")
    op.drop_column("eod_screen_results", "backtest_win_rate")
    op.drop_column("eod_screen_results", "backtest_total_trades")
    op.drop_column("eod_screen_results", "backtest_end_date")
    op.drop_column("eod_screen_results", "backtest_start_date")
