"""Add explainable Zammad ticket type and asset relationships.

Revision ID: 20260801_0011
Revises: 20260801_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_0011"
down_revision: str | None = "20260801_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("zammad_tickets") as batch:
        batch.add_column(
            sa.Column(
                "ticket_type_reason", sa.String(length=500), nullable=False, server_default=""
            )
        )
        batch.add_column(
            sa.Column("asset_relationships_json", sa.JSON(), nullable=False, server_default="[]")
        )
    # Force the next enabled sync through the existing bounded reconciliation so
    # cached tickets receive deterministic type and relationship classifications.
    op.execute(
        sa.text("UPDATE zammad_configurations SET last_reconciled_at = NULL, sync_cursor_at = NULL")
    )


def downgrade() -> None:
    with op.batch_alter_table("zammad_tickets") as batch:
        batch.drop_column("asset_relationships_json")
        batch.drop_column("ticket_type_reason")
