"""add_eod_screen_quote_metadata

Revision ID: d9a3b2c7e614
Revises: c2e8a4f6b901
Create Date: 2026-05-11 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d9a3b2c7e614"
down_revision: Union[str, None] = "c2e8a4f6b901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("eod_screen_results", sa.Column("data_mode", sa.String(length=20), nullable=True))
    op.add_column("eod_screen_results", sa.Column("quote_source", sa.String(length=50), nullable=True))
    op.add_column("eod_screen_results", sa.Column("quote_time", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("eod_screen_results", "quote_time")
    op.drop_column("eod_screen_results", "quote_source")
    op.drop_column("eod_screen_results", "data_mode")
