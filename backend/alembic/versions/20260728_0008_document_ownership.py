"""Add explicit managed-document ownership metadata.

Revision ID: 20260728_0008
Revises: 20260728_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0008"
down_revision: str | None = "20260728_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("owner_instance_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("owner_connector_id", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("owner_tenant_id", sa.String(length=200), nullable=True))
        batch.create_index(batch.f("ix_documents_owner_instance_id"), ["owner_instance_id"])
        batch.create_index(batch.f("ix_documents_owner_connector_id"), ["owner_connector_id"])
        batch.create_index(batch.f("ix_documents_owner_tenant_id"), ["owner_tenant_id"])

    # The protected managed source belongs to this local connector instance. SaaS
    # ownership is backfilled only when registration history does not contradict
    # the current connector and tenant.
    op.execute(
        """
        UPDATE documents
        SET owner_instance_id = (
            SELECT instance_id FROM product_settings WHERE id = 1
        )
        WHERE source_id IN (
            SELECT id FROM sources
            WHERE system_managed = 1
              AND json_extract(configuration, '$.path') = '/data/sources/documents'
        )
        """
    )
    op.execute(
        """
        UPDATE documents
        SET owner_connector_id = (
                SELECT connector_id FROM product_settings WHERE id = 1
            ),
            owner_tenant_id = (
                SELECT tenant_id FROM product_settings WHERE id = 1
            )
        WHERE owner_instance_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM audit_events, product_settings
              WHERE audit_events.event_type = 'connector.registration_succeeded'
                AND (
                    audit_events.target_id != product_settings.connector_id
                    OR json_extract(audit_events.details, '$.tenant_id')
                       != product_settings.tenant_id
                )
          )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_index(batch.f("ix_documents_owner_tenant_id"))
        batch.drop_index(batch.f("ix_documents_owner_connector_id"))
        batch.drop_index(batch.f("ix_documents_owner_instance_id"))
        batch.drop_column("owner_tenant_id")
        batch.drop_column("owner_connector_id")
        batch.drop_column("owner_instance_id")
