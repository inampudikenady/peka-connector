"""Add automatic scan scheduling and SaaS connector lifecycle state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_0003"
down_revision: str | None = "20260720_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE product_settings SET saas_status = 'unregistered' "
        "WHERE saas_status = 'not_registered'"
    )
    with op.batch_alter_table("sources") as batch:
        batch.add_column(sa.Column("next_scheduled_scan_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_scheduled_scan_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("scan_in_progress", sa.Boolean(), server_default=sa.false(), nullable=False)
        )

    with op.batch_alter_table("scan_history") as batch:
        batch.add_column(
            sa.Column("trigger", sa.String(length=20), server_default="manual", nullable=False)
        )
        batch.create_index(batch.f("ix_scan_history_trigger"), ["trigger"], unique=False)

    with op.batch_alter_table("product_settings") as batch:
        batch.add_column(sa.Column("instance_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("encrypted_connector_secret", sa.Text(), nullable=True))
        batch.add_column(sa.Column("encryption_key_check", sa.Text(), nullable=True))
        batch.add_column(sa.Column("registered_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "heartbeat_interval_seconds", sa.Integer(), server_default="300", nullable=False
            )
        )
        batch.add_column(sa.Column("last_heartbeat_attempt_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("next_heartbeat_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_heartbeat_status", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("last_heartbeat_error", sa.String(length=2000), nullable=True))
        batch.add_column(
            sa.Column("heartbeat_failure_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch.add_column(
            sa.Column(
                "heartbeat_job_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )
        batch.create_unique_constraint("uq_product_settings_instance_id", ["instance_id"])


def downgrade() -> None:
    with op.batch_alter_table("product_settings") as batch:
        batch.drop_constraint("uq_product_settings_instance_id", type_="unique")
        batch.drop_column("heartbeat_job_enabled")
        batch.drop_column("heartbeat_failure_count")
        batch.drop_column("last_heartbeat_error")
        batch.drop_column("last_heartbeat_status")
        batch.drop_column("next_heartbeat_at")
        batch.drop_column("last_heartbeat_attempt_at")
        batch.drop_column("heartbeat_interval_seconds")
        batch.drop_column("registered_at")
        batch.drop_column("encryption_key_check")
        batch.drop_column("encrypted_connector_secret")
        batch.drop_column("instance_id")
    with op.batch_alter_table("scan_history") as batch:
        batch.drop_index(batch.f("ix_scan_history_trigger"))
        batch.drop_column("trigger")
    with op.batch_alter_table("sources") as batch:
        batch.drop_column("scan_in_progress")
        batch.drop_column("last_scheduled_scan_at")
        batch.drop_column("next_scheduled_scan_at")
