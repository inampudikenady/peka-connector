"""Track ServiceNow synchronization attempts.

Revision ID: 20260815_0019
Revises: 20260814_0018
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.infrastructure.database import types

revision: str = "20260815_0019"
down_revision: str | None = "20260814_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Migration 0013 historically creates this table from the live model. A
    # fresh upgrade can therefore already contain this newer column, while an
    # actual deployed v2 database still needs it added here.
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("servicenow_configurations")
    }
    if "last_attempted_sync_at" not in columns:
        op.add_column(
            "servicenow_configurations",
            sa.Column("last_attempted_sync_at", types.UTCDateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("servicenow_configurations")
    }
    if "last_attempted_sync_at" in columns:
        op.drop_column("servicenow_configurations", "last_attempted_sync_at")
