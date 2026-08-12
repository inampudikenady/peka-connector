"""Add durable local knowledge activity timestamps.

Revision ID: 20260812_0016
Revises: 20260811_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260812_0016"
down_revision: str | None = "20260811_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("knowledge_indexed_at", sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE documents SET knowledge_indexed_at = updated_at "
        "WHERE knowledge_status = 'INDEXED' AND knowledge_indexed_at IS NULL"
    )
    with op.batch_alter_table("product_settings") as batch:
        batch.add_column(
            sa.Column("last_successful_knowledge_search_at", sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("product_settings") as batch:
        batch.drop_column("last_successful_knowledge_search_at")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("knowledge_indexed_at")
