"""widen_shareholder_count_change

Revision ID: c1d2e3f4a5b6
Revises: a2b3c4d5e6f7
Create Date: 2026-05-29 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "shareholder_counts",
        "holder_count_change",
        existing_type=sa.Numeric(precision=8, scale=4),
        type_=sa.Numeric(precision=12, scale=4),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "shareholder_counts",
        "holder_count_change",
        existing_type=sa.Numeric(precision=12, scale=4),
        type_=sa.Numeric(precision=8, scale=4),
        existing_nullable=True,
    )
