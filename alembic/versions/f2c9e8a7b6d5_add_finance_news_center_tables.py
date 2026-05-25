"""add_finance_news_center_tables"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f2c9e8a7b6d5"
down_revision: Union[str, None] = "b8d7f0c9a2e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "finance_news_sources",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "url", name="uq_finance_news_sources_type_url"),
    )
    op.create_index("ix_finance_news_sources_category", "finance_news_sources", ["category"])
    op.create_index("ix_finance_news_sources_enabled", "finance_news_sources", ["enabled"])
    op.create_index("ix_finance_news_sources_source_type", "finance_news_sources", ["source_type"])

    op.create_table(
        "finance_news_articles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        sa.Column("source_name", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_metadata", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_hash"),
    )
    op.create_index("ix_finance_news_articles_content_hash", "finance_news_articles", ["content_hash"])
    op.create_index("ix_finance_news_articles_fetched_at", "finance_news_articles", ["fetched_at"])
    op.create_index("ix_finance_news_articles_published_at", "finance_news_articles", ["published_at"])
    op.create_index("ix_finance_news_articles_published_source", "finance_news_articles", ["published_at", "source_name"])
    op.create_index("ix_finance_news_articles_source_id", "finance_news_articles", ["source_id"])
    op.create_index("ix_finance_news_articles_source_name", "finance_news_articles", ["source_name"])

    op.create_table(
        "finance_daily_summaries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("key_points", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("watch_items", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("article_ids", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("source_names", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("article_count", sa.Integer(), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("llm_used", sa.Boolean(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("data_gaps", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("summary_date"),
    )
    op.create_index(
        "ix_finance_daily_summaries_date_generated",
        "finance_daily_summaries",
        ["summary_date", "generated_at"],
    )
    op.create_index("ix_finance_daily_summaries_generated_at", "finance_daily_summaries", ["generated_at"])
    op.create_index("ix_finance_daily_summaries_status", "finance_daily_summaries", ["status"])
    op.create_index("ix_finance_daily_summaries_summary_date", "finance_daily_summaries", ["summary_date"])


def downgrade() -> None:
    op.drop_index("ix_finance_daily_summaries_summary_date", table_name="finance_daily_summaries")
    op.drop_index("ix_finance_daily_summaries_status", table_name="finance_daily_summaries")
    op.drop_index("ix_finance_daily_summaries_generated_at", table_name="finance_daily_summaries")
    op.drop_index("ix_finance_daily_summaries_date_generated", table_name="finance_daily_summaries")
    op.drop_table("finance_daily_summaries")

    op.drop_index("ix_finance_news_articles_source_name", table_name="finance_news_articles")
    op.drop_index("ix_finance_news_articles_source_id", table_name="finance_news_articles")
    op.drop_index("ix_finance_news_articles_published_source", table_name="finance_news_articles")
    op.drop_index("ix_finance_news_articles_published_at", table_name="finance_news_articles")
    op.drop_index("ix_finance_news_articles_fetched_at", table_name="finance_news_articles")
    op.drop_index("ix_finance_news_articles_content_hash", table_name="finance_news_articles")
    op.drop_table("finance_news_articles")

    op.drop_index("ix_finance_news_sources_source_type", table_name="finance_news_sources")
    op.drop_index("ix_finance_news_sources_enabled", table_name="finance_news_sources")
    op.drop_index("ix_finance_news_sources_category", table_name="finance_news_sources")
    op.drop_table("finance_news_sources")
