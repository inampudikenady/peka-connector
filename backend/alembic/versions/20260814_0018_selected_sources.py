"""Normalize stream activation rows to selected-source semantics.

Revision ID: 20260814_0018
Revises: 20260813_0017
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260814_0018"
down_revision: str | None = "20260813_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")


def _identifier(value: object) -> str:
    return str(value).replace("-", "")


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, connector_id, integration_id, stream, enabled, active, "
            "activated_at, updated_at, created_at FROM integration_stream_activations"
        )
    ).mappings().all()
    grouped: dict[tuple[str, str], list[sa.RowMapping]] = {}
    for row in rows:
        grouped.setdefault((str(row["connector_id"]), str(row["stream"])), []).append(row)

    bind.execute(
        sa.text("UPDATE integration_stream_activations SET enabled=false, active=false")
    )
    selected_integrations: set[str] = set()
    for (connector_id, stream), candidates in grouped.items():
        active = [row for row in candidates if bool(row["active"])]
        eligible = active or [row for row in candidates if bool(row["enabled"])]
        if not eligible:
            continue
        selected = max(
            eligible,
            key=lambda row: (
                str(row["activated_at"] or row["updated_at"] or row["created_at"] or ""),
                str(row["id"]),
            ),
        )
        if not active and len(eligible) > 1:
            logger.warning(
                "Ambiguous v2.0.0 source state for connector=%s stream=%s; "
                "selected integration=%s deterministically",
                connector_id,
                stream,
                selected["integration_id"],
            )
        bind.execute(
            sa.text(
                "UPDATE integration_stream_activations "
                "SET enabled=true, active=true WHERE id=:id"
            ),
            {"id": _identifier(selected["id"])},
        )
        selected_integrations.add(_identifier(selected["integration_id"]))

    integration_ids = {
        _identifier(row["integration_id"])
        for row in rows
    }
    for integration_id in integration_ids:
        selected = integration_id in selected_integrations
        bind.execute(
            sa.text("UPDATE connector_integrations SET enabled=:selected WHERE id=:id"),
            {"selected": selected, "id": integration_id},
        )
        bind.execute(
            sa.text(
                "UPDATE servicenow_configurations "
                "SET enabled=:selected WHERE integration_id=:id"
            ),
            {"selected": selected, "id": integration_id},
        )
    bind.execute(
        sa.text(
            "UPDATE zammad_configurations SET enabled=false WHERE id IN ("
            "SELECT legacy_zammad_configuration_id FROM connector_integrations "
            "WHERE integration_type='zammad' AND enabled=false "
            "AND legacy_zammad_configuration_id IS NOT NULL)"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE zammad_configurations SET enabled=true WHERE id IN ("
            "SELECT legacy_zammad_configuration_id FROM connector_integrations "
            "WHERE integration_type='zammad' AND enabled=true "
            "AND legacy_zammad_configuration_id IS NOT NULL)"
        )
    )
    with op.batch_alter_table("integration_stream_activations") as batch:
        batch.create_check_constraint(
            "ck_stream_activation_selected_state", "enabled = active"
        )


def downgrade() -> None:
    with op.batch_alter_table("integration_stream_activations") as batch:
        batch.drop_constraint("ck_stream_activation_selected_state", type_="check")
