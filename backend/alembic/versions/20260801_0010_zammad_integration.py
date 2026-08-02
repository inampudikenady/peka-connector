"""Add connector-local Zammad configuration and normalized ticket cache.

Revision ID: 20260801_0010
Revises: 20260730_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.infrastructure.database import types

revision: str = "20260801_0010"
down_revision: str | None = "20260730_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "zammad_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("instance_key", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("token_configured", sa.Boolean(), nullable=False),
        sa.Column("tls_verify", sa.Boolean(), nullable=False),
        sa.Column("request_timeout_seconds", sa.Float(), nullable=False),
        sa.Column("sync_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("history_window_days", sa.Integer(), nullable=False),
        sa.Column("group_filters_json", sa.JSON(), nullable=False),
        sa.Column("include_closed_tickets", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("connection_state", sa.String(32), nullable=False),
        sa.Column("sync_cursor_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("last_successful_test_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("last_reconciled_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("last_sync_duration_seconds", sa.Float(), nullable=True),
        sa.Column("next_scheduled_sync_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("synchronized_ticket_count", sa.Integer(), nullable=False),
        sa.Column("synchronized_article_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(2000), nullable=True),
        sa.Column("created_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zammad_configurations")),
        sa.UniqueConstraint("name", name=op.f("uq_zammad_configurations_name")),
        sa.UniqueConstraint("instance_key", name=op.f("uq_zammad_configurations_instance_key")),
    )
    op.create_index(op.f("ix_zammad_configurations_enabled"), "zammad_configurations", ["enabled"])
    op.create_index(
        op.f("ix_zammad_configurations_instance_key"), "zammad_configurations", ["instance_key"]
    )

    op.create_table(
        "zammad_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("instance_key", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("number", sa.String(100), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("state", sa.String(255), nullable=False),
        sa.Column("state_type", sa.String(64), nullable=False),
        sa.Column("priority", sa.String(255), nullable=True),
        sa.Column("group_name", sa.String(500), nullable=True),
        sa.Column("owner", sa.String(500), nullable=True),
        sa.Column("customer", sa.String(500), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("created_at_source", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at_source", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("closed_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("ticket_type", sa.String(64), nullable=False),
        sa.Column("initial_description", sa.Text(), nullable=True),
        sa.Column("latest_update_text", sa.Text(), nullable=True),
        sa.Column("latest_update_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("referenced_asset_ids_json", sa.JSON(), nullable=False),
        sa.Column("referenced_hostnames_json", sa.JSON(), nullable=False),
        sa.Column("referenced_fqdns_json", sa.JSON(), nullable=False),
        sa.Column("referenced_ip_addresses_json", sa.JSON(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("synchronized_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("created_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["configuration_id"], ["zammad_configurations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zammad_tickets")),
        sa.UniqueConstraint(
            "configuration_id", "external_id", name=op.f("uq_zammad_tickets_configuration_id")
        ),
        sa.UniqueConstraint(
            "configuration_id", "number", name=op.f("uq_zammad_tickets_configuration_number")
        ),
    )
    for column in (
        "configuration_id",
        "instance_key",
        "external_id",
        "number",
        "title",
        "state",
        "state_type",
        "group_name",
        "created_at_source",
        "updated_at_source",
        "is_open",
        "ticket_type",
        "latest_update_at",
        "referenced_asset_ids_json",
        "referenced_hostnames_json",
        "referenced_fqdns_json",
        "referenced_ip_addresses_json",
        "search_text",
        "visible",
    ):
        op.create_index(op.f(f"ix_zammad_tickets_{column}"), "zammad_tickets", [column])

    op.create_table(
        "zammad_ticket_articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=False),
        sa.Column("created_at_source", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at_source", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("author", sa.String(500), nullable=True),
        sa.Column("sender", sa.String(255), nullable=True),
        sa.Column("article_type", sa.String(255), nullable=True),
        sa.Column("internal", sa.Boolean(), nullable=False),
        sa.Column("automated", sa.Boolean(), nullable=False),
        sa.Column("subject", sa.String(1000), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("raw_metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["zammad_tickets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zammad_ticket_articles")),
        sa.UniqueConstraint(
            "ticket_id", "external_id", name=op.f("uq_zammad_ticket_articles_ticket_id_external_id")
        ),
    )
    op.create_index(
        op.f("ix_zammad_ticket_articles_ticket_id"), "zammad_ticket_articles", ["ticket_id"]
    )
    op.create_index(
        op.f("ix_zammad_ticket_articles_external_id"), "zammad_ticket_articles", ["external_id"]
    )
    op.create_index(
        op.f("ix_zammad_ticket_articles_created_at_source"),
        "zammad_ticket_articles",
        ["created_at_source"],
    )
    op.create_index(
        op.f("ix_zammad_ticket_articles_body_text"),
        "zammad_ticket_articles",
        ["body_text"],
    )


def downgrade() -> None:
    op.drop_table("zammad_ticket_articles")
    op.drop_table("zammad_tickets")
    op.drop_table("zammad_configurations")
