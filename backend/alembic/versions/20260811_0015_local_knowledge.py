"""Add connector-local knowledge indexing state.

Revision ID: 20260811_0015
Revises: 20260805_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0015"
down_revision: str | None = "20260805_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(
            sa.Column("knowledge_status", sa.String(length=32), nullable=False, server_default="PENDING")
        )
        batch.add_column(sa.Column("indexed_content_hash", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column("indexed_chunk_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("knowledge_error", sa.String(length=500), nullable=True))
        batch.create_index("ix_documents_knowledge_status", ["knowledge_status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_index("ix_documents_knowledge_status")
        batch.drop_column("knowledge_error")
        batch.drop_column("indexed_chunk_count")
        batch.drop_column("indexed_content_hash")
        batch.drop_column("knowledge_status")
