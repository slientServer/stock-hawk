"""widen_financial_report_percentages

Revision ID: 8e2f7c3b9a41
Revises: 424d9591d028
Create Date: 2026-05-07 15:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8e2f7c3b9a41"
down_revision: Union[str, None] = "424d9591d028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column_name in ("revenue_yoy", "net_profit_yoy", "gross_margin", "roe"):
        op.alter_column(
            "financial_reports",
            column_name,
            existing_type=sa.Numeric(precision=8, scale=4),
            type_=sa.Numeric(precision=12, scale=4),
            existing_nullable=True,
        )


def downgrade() -> None:
    for column_name in ("revenue_yoy", "net_profit_yoy", "gross_margin", "roe"):
        op.alter_column(
            "financial_reports",
            column_name,
            existing_type=sa.Numeric(precision=12, scale=4),
            type_=sa.Numeric(precision=8, scale=4),
            existing_nullable=True,
        )
