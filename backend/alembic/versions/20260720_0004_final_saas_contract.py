"""Align persisted lifecycle metrics with the final PEKA SaaS contract."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_0004"
down_revision: str | None = "20260720_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("product_settings") as batch:
        batch.add_column(sa.Column("last_heartbeat_failed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("heartbeat_round_trip_ms", sa.Float(), nullable=True))
        batch.add_column(sa.Column("last_saas_server_time", sa.DateTime(), nullable=True))
    with op.batch_alter_table("scan_history") as batch:
        batch.add_column(sa.Column("correlation_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE scan_history SET correlation_id = lower(hex(randomblob(16)))")
    with op.batch_alter_table("scan_history") as batch:
        batch.alter_column("correlation_id", nullable=False)
        batch.create_index(
            batch.f("ix_scan_history_correlation_id"), ["correlation_id"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("scan_history") as batch:
        batch.drop_index(batch.f("ix_scan_history_correlation_id"))
        batch.drop_column("correlation_id")
    with op.batch_alter_table("product_settings") as batch:
        batch.drop_column("last_saas_server_time")
        batch.drop_column("heartbeat_round_trip_ms")
        batch.drop_column("last_heartbeat_failed_at")
