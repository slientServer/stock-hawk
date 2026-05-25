"""add_watchlist_items"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "c6d8f1a2b3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("source", sa.String(30), nullable=False, server_default="manual"),
        # Mode 1
        sa.Column("mode1_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mode1_target_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("mode1_floor_price", sa.Numeric(12, 4), nullable=True),
        # Mode 2
        sa.Column("mode2_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mode2_base_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("mode2_up_pct", sa.Float(), nullable=True),
        sa.Column("mode2_down_pct", sa.Float(), nullable=True),
        # Mode 3
        sa.Column("mode3_enabled", sa.Boolean(), nullable=False, server_default="false"),
        # 推送去重
        sa.Column("last_notified_mode1", sa.String(20), nullable=True),
        sa.Column("last_notified_mode2", sa.String(20), nullable=True),
        sa.Column("last_notified_mode3_date", sa.String(10), nullable=True),
        # 其他
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_watchlist_items_code", "watchlist_items", ["code"])
    op.create_index("ix_watchlist_items_status", "watchlist_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_items_status", table_name="watchlist_items")
    op.drop_index("ix_watchlist_items_code", table_name="watchlist_items")
    op.drop_table("watchlist_items")
