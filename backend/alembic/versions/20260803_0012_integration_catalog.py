"""Add generic integrations, provider bindings, and ticket cache provenance.

Revision ID: 20260803_0012
Revises: 20260801_0011
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op
from app.infrastructure.database import types

revision: str = "20260803_0012"
down_revision: str | None = "20260801_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connector_integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.String(200), nullable=False),
        sa.Column("integration_type", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("configuration_encrypted", sa.Text(), nullable=True),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("last_tested_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("last_successful_test_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("initial_sync_status", sa.String(32), nullable=False),
        sa.Column("last_error", sa.String(2000), nullable=True),
        sa.Column("legacy_zammad_configuration_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["legacy_zammad_configuration_id"],
            ["zammad_configurations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_integrations")),
        sa.UniqueConstraint(
            "connector_id", "display_name", name="uq_connector_integrations_connector_name"
        ),
        sa.UniqueConstraint(
            "legacy_zammad_configuration_id",
            name="uq_connector_integrations_legacy_zammad_configuration_id",
        ),
    )
    for column in ("connector_id", "integration_type", "category", "enabled", "status"):
        op.create_index(
            op.f(f"ix_connector_integrations_{column}"),
            "connector_integrations",
            [column],
        )

    op.create_table(
        "connector_provider_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.String(200), nullable=False),
        sa.Column("provider_role", sa.String(64), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("activated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["connector_integrations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connector_provider_bindings")),
        sa.UniqueConstraint(
            "connector_id", "provider_role", name="uq_connector_provider_bindings_connector_role"
        ),
    )
    for column in ("connector_id", "provider_role", "integration_id", "enabled"):
        op.create_index(
            op.f(f"ix_connector_provider_bindings_{column}"),
            "connector_provider_bindings",
            [column],
        )

    with op.batch_alter_table("zammad_tickets") as batch:
        batch.alter_column("configuration_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("connector_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("integration_type", sa.String(64), nullable=True))
        batch.add_column(sa.Column("integration_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("provider_role", sa.String(64), nullable=True))
        batch.add_column(sa.Column("provider_generation", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_record_id", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column("source_updated_at", types.UTCDateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("synced_at", types.UTCDateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cache_status", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_zammad_tickets_integration_id_connector_integrations",
            "connector_integrations",
            ["integration_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    bind = op.get_bind()
    now = datetime.now(UTC)
    product = bind.execute(
        sa.text("SELECT connector_id, instance_id FROM product_settings ORDER BY id LIMIT 1")
    ).mappings().first()
    connector_id = str(
        (product or {}).get("connector_id") or (product or {}).get("instance_id") or "local"
    )
    configurations = bind.execute(
        sa.text(
            "SELECT id, name, enabled, connection_state, last_successful_test_at, "
            "last_successful_sync_at, last_error, created_at, updated_at "
            "FROM zammad_configurations ORDER BY created_at"
        )
    ).mappings().all()
    first_enabled_integration = None
    for configuration in configurations:
        integration_id = uuid4()
        if configuration["enabled"] and first_enabled_integration is None:
            first_enabled_integration = integration_id
        bind.execute(
            sa.text(
                "INSERT INTO connector_integrations "
                "(id, connector_id, integration_type, display_name, category, enabled, status, "
                "configuration_json, configuration_encrypted, capabilities_json, last_tested_at, "
                "last_successful_test_at, last_successful_sync_at, initial_sync_status, "
                "last_error, "
                "legacy_zammad_configuration_id, created_at, updated_at) VALUES "
                "(:id, :connector_id, 'zammad', :display_name, 'ITSM', :enabled, :status, "
                "'{}', NULL, '{\"tickets\": true}', :last_tested_at, :last_successful_test_at, "
                ":last_successful_sync_at, :initial_sync_status, :last_error, :legacy_id, "
                ":created_at, :updated_at)"
            ),
            {
                "id": integration_id.hex,
                "connector_id": connector_id,
                "display_name": configuration["name"],
                "enabled": configuration["enabled"],
                "status": "healthy"
                if configuration["connection_state"] == "connected"
                else "attention",
                "last_tested_at": configuration["last_successful_test_at"],
                "last_successful_test_at": configuration["last_successful_test_at"],
                "last_successful_sync_at": configuration["last_successful_sync_at"],
                "initial_sync_status": "completed"
                if configuration["last_successful_sync_at"]
                else "not_started",
                "last_error": configuration["last_error"],
                "legacy_id": str(configuration["id"]).replace("-", ""),
                "created_at": configuration["created_at"] or now,
                "updated_at": configuration["updated_at"] or now,
            },
        )
        bind.execute(
            sa.text(
                "UPDATE zammad_tickets SET connector_id=:connector_id, "
                "integration_type='zammad', integration_id=:integration_id, "
                "provider_role='ticketing', provider_generation=1, source_record_id=external_id, "
                "source_updated_at=updated_at_source, synced_at=synchronized_at, "
                "cache_status=CASE WHEN visible THEN 'active' ELSE 'deleted' END "
                "WHERE configuration_id=:configuration_id"
            ),
            {
                "connector_id": connector_id,
                "integration_id": integration_id.hex,
                "configuration_id": str(configuration["id"]).replace("-", ""),
            },
        )
    if first_enabled_integration is not None:
        bind.execute(
            sa.text(
                "INSERT INTO connector_provider_bindings "
                "(id, connector_id, provider_role, integration_id, enabled, generation, "
                "activated_at, updated_at) VALUES "
                "(:id, :connector_id, 'ticketing', :integration_id, true, 1, :now, :now)"
            ),
            {
                "id": uuid4().hex,
                "connector_id": connector_id,
                "integration_id": first_enabled_integration.hex,
                "now": now,
            },
        )

    with op.batch_alter_table("zammad_tickets") as batch:
        for column in (
            "connector_id",
            "integration_type",
            "integration_id",
            "provider_role",
            "provider_generation",
            "source_record_id",
            "source_updated_at",
            "synced_at",
            "cache_status",
        ):
            batch.create_index(op.f(f"ix_zammad_tickets_{column}"), [column])
        for column, column_type in (
            ("connector_id", sa.String(200)),
            ("integration_type", sa.String(64)),
            ("integration_id", sa.Uuid()),
            ("provider_role", sa.String(64)),
            ("provider_generation", sa.Integer()),
            ("source_record_id", sa.String(100)),
            ("source_updated_at", types.UTCDateTime(timezone=True)),
            ("synced_at", types.UTCDateTime(timezone=True)),
            ("cache_status", sa.String(32)),
        ):
            batch.alter_column(column, existing_type=column_type, nullable=False)
        batch.create_unique_constraint(
            "uq_ticket_cache_integration_source_record", ["integration_id", "source_record_id"]
        )


def downgrade() -> None:
    # The legacy schema can represent only Zammad-owned cache records.
    op.execute(sa.text("DELETE FROM zammad_tickets WHERE integration_type != 'zammad'"))
    with op.batch_alter_table("zammad_tickets") as batch:
        batch.alter_column("configuration_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_constraint("uq_ticket_cache_integration_source_record", type_="unique")
        for column in (
            "cache_status",
            "synced_at",
            "source_updated_at",
            "source_record_id",
            "provider_generation",
            "provider_role",
            "integration_id",
            "integration_type",
            "connector_id",
        ):
            batch.drop_index(op.f(f"ix_zammad_tickets_{column}"))
            batch.drop_column(column)
    op.drop_table("connector_provider_bindings")
    op.drop_table("connector_integrations")
