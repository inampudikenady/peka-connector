"""Add stream-scoped source activation.

Revision ID: 20260813_0017
Revises: 20260812_0016
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op
from app.infrastructure.database import types

revision: str = "20260813_0017"
down_revision: str | None = "20260812_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_STREAMS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "prometheus": (("monitoring", "prometheus", "Prometheus"),),
    "loki": (("logs", "loki", "Loki"),),
    "zammad": (("ticketing", "zammad", "Zammad"),),
    "servicenow": (
        ("ticketing", "servicenow", "ServiceNow"),
        ("cmdb", "servicenow_cmdb", "ServiceNow CMDB"),
    ),
    "generic_cmdb": (("cmdb", "local_cmdb", "Local CMDB"),),
    "documents": (("knowledge", "documents", "Documents"),),
}


def upgrade() -> None:
    op.create_table(
        "integration_stream_activations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.String(200), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("stream", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("source_name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("activated_at", types.UTCDateTime(timezone=True), nullable=True),
        sa.Column("created_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["connector_integrations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_stream_activations")),
        sa.UniqueConstraint(
            "connector_id",
            "stream",
            "source_key",
            name="uq_stream_activation_connector_stream_source",
        ),
    )
    for column in ("connector_id", "integration_id", "stream", "source_key", "enabled", "active"):
        op.create_index(
            op.f(f"ix_integration_stream_activations_{column}"),
            "integration_stream_activations",
            [column],
        )
    op.create_index(
        "uq_stream_activation_one_active",
        "integration_stream_activations",
        ["connector_id", "stream"],
        unique=True,
        sqlite_where=sa.text("active = 1"),
        postgresql_where=sa.text("active = true"),
    )

    bind = op.get_bind()
    now = datetime.now(UTC)
    rows = bind.execute(
        sa.text(
            "SELECT id, connector_id, integration_type, enabled, capabilities_json, "
            "last_successful_sync_at, updated_at FROM connector_integrations"
        )
    ).mappings().all()
    candidates: dict[tuple[str, str], list[tuple[object, object, object]]] = {}
    for row in rows:
        capabilities = row["capabilities_json"] or {}
        if isinstance(capabilities, str):
            capabilities = json.loads(capabilities)
        source_streams = SOURCE_STREAMS.get(row["integration_type"], ())
        if row["integration_type"] == "servicenow":
            source_streams = tuple(
                item
                for item in source_streams
                if (item[0] == "ticketing" and capabilities.get("incidents", False))
                or (item[0] == "cmdb" and capabilities.get("cmdb", False))
            )
        for stream, source_key, source_name in source_streams:
            activation_id = uuid4()
            bind.execute(
                sa.text(
                    "INSERT INTO integration_stream_activations "
                    "(id, connector_id, integration_id, stream, source_key, source_name, enabled, "
                    "active, activated_at, created_at, updated_at) VALUES "
                    "(:id, :connector_id, :integration_id, :stream, :source_key, :source_name, "
                    ":enabled, false, NULL, :now, :now)"
                ),
                {
                    "id": activation_id.hex,
                    "connector_id": row["connector_id"],
                    "integration_id": str(row["id"]).replace("-", ""),
                    "stream": stream,
                    "source_key": source_key,
                    "source_name": source_name,
                    "enabled": bool(row["enabled"]),
                    "now": now,
                },
            )
            if row["enabled"]:
                sort_time = row["last_successful_sync_at"] or row["updated_at"] or now
                candidates.setdefault((row["connector_id"], stream), []).append(
                    (sort_time, str(row["id"]), activation_id)
                )
    # Existing multi-enabled streams select the freshest synchronized source, then UUID.
    # No configuration is removed and the other source remains enabled but inactive.
    for values in candidates.values():
        selected = max(values, key=lambda item: (item[0], item[1]))[2]
        bind.execute(
            sa.text(
                "UPDATE integration_stream_activations SET active=true, activated_at=:now "
                "WHERE id=:id"
            ),
            {"id": selected.hex, "now": now},
        )


def downgrade() -> None:
    op.drop_table("integration_stream_activations")
