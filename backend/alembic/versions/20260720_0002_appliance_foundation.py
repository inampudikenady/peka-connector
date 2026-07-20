"""Add appliance authentication, operations, scan, and settings state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_0002"
down_revision: str | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("role", sa.String(length=32), server_default="administrator", nullable=False)
        )
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))
        batch.create_index(batch.f("ix_users_role"), ["role"], unique=False)
    op.execute("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)

    with op.batch_alter_table("sources") as batch:
        batch.add_column(
            sa.Column(
                "health_status", sa.String(length=32), server_default="unknown", nullable=False
            )
        )
        batch.add_column(sa.Column("last_success_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_error", sa.String(length=2000), nullable=True))
        batch.add_column(sa.Column("last_scan_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("file_count", sa.Integer(), server_default="0", nullable=False))

    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column("state", sa.String(length=32), server_default="active", nullable=False)
        )
        batch.create_index(batch.f("ix_documents_state"), ["state"], unique=False)
    op.execute("UPDATE documents SET last_seen_at = discovered_at WHERE last_seen_at IS NULL")
    with op.batch_alter_table("documents") as batch:
        batch.alter_column("last_seen_at", existing_type=sa.DateTime(), nullable=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])
    op.create_index(
        op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True
    )

    op.create_table(
        "scan_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("added_count", sa.Integer(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_scan_history_source_id_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_history")),
    )
    op.create_index(op.f("ix_scan_history_source_id"), "scan_history", ["source_id"])
    op.create_index(op.f("ix_scan_history_status"), "scan_history", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_username", sa.String(length=100), nullable=True),
        sa.Column("target_type", sa.String(length=100), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_event_type"), "audit_events", ["event_type"])
    op.create_index(op.f("ix_audit_events_actor_user_id"), "audit_events", ["actor_user_id"])
    op.create_index(op.f("ix_audit_events_created_at"), "audit_events", ["created_at"])

    op.create_table(
        "application_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("component", sa.String(length=100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_application_logs")),
    )
    op.create_index(op.f("ix_application_logs_level"), "application_logs", ["level"])
    op.create_index(op.f("ix_application_logs_component"), "application_logs", ["component"])
    op.create_index(op.f("ix_application_logs_created_at"), "application_logs", ["created_at"])

    op.create_table(
        "product_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("connector_display_name", sa.String(length=200), nullable=False),
        sa.Column("environment_label", sa.String(length=100), nullable=False),
        sa.Column("log_level", sa.String(length=20), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("saas_status", sa.String(length=32), nullable=False),
        sa.Column("connector_id", sa.String(length=200), nullable=True),
        sa.Column("tenant_id", sa.String(length=200), nullable=True),
        sa.Column("saas_url", sa.String(length=500), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_settings")),
    )


def downgrade() -> None:
    op.drop_table("product_settings")
    op.drop_table("application_logs")
    op.drop_table("audit_events")
    op.drop_table("scan_history")
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("documents") as batch:
        batch.drop_index(batch.f("ix_documents_state"))
        batch.drop_column("state")
        batch.drop_column("last_seen_at")
    with op.batch_alter_table("sources") as batch:
        batch.drop_column("file_count")
        batch.drop_column("last_scan_at")
        batch.drop_column("last_error")
        batch.drop_column("last_success_at")
        batch.drop_column("health_status")
    with op.batch_alter_table("users") as batch:
        batch.drop_index(batch.f("ix_users_role"))
        batch.drop_column("last_login_at")
        batch.drop_column("updated_at")
        batch.drop_column("role")
