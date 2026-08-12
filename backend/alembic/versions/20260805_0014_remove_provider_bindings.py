"""Remove the obsolete active ticket-provider binding.

Revision ID: 20260805_0014
Revises: 20260804_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260805_0014"
down_revision: str | None = "20260804_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("connector_provider_bindings")
    op.drop_index(op.f("ix_zammad_tickets_provider_role"), table_name="zammad_tickets")
    op.drop_index(
        op.f("ix_zammad_tickets_provider_generation"), table_name="zammad_tickets"
    )
    with op.batch_alter_table("zammad_tickets") as batch:
        batch.drop_column("provider_role")
        batch.drop_column("provider_generation")


def downgrade() -> None:
    with op.batch_alter_table("zammad_tickets") as batch:
        batch.add_column(
            sa.Column(
                "provider_role",
                sa.String(length=64),
                nullable=False,
                server_default="ticketing",
            )
        )
        batch.add_column(
            sa.Column(
                "provider_generation",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
    op.create_index(
        op.f("ix_zammad_tickets_provider_role"),
        "zammad_tickets",
        ["provider_role"],
        unique=False,
    )
    op.create_index(
        op.f("ix_zammad_tickets_provider_generation"),
        "zammad_tickets",
        ["provider_generation"],
        unique=False,
    )
    op.create_table(
        "connector_provider_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connector_id", sa.String(length=200), nullable=False),
        sa.Column("provider_role", sa.String(length=64), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["connector_integrations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connector_id", "provider_role"),
    )
    for column in ("connector_id", "provider_role", "integration_id", "enabled"):
        op.create_index(
            op.f(f"ix_connector_provider_bindings_{column}"),
            "connector_provider_bindings",
            [column],
            unique=False,
        )
