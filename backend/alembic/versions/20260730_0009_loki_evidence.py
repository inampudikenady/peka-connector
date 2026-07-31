"""Add connector-local Loki evidence configuration.

Revision ID: 20260730_0009
Revises: 20260728_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.infrastructure.database import types

revision: str = "20260730_0009"
down_revision: str | None = "20260728_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "loki_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=False),
        sa.Column("auth_type", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=500), nullable=True),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column("tls_verify", sa.Boolean(), nullable=False),
        sa.Column("request_timeout_seconds", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("discovery_lookback_days", sa.Integer(), nullable=False),
        sa.Column("discovered_schema_json", sa.JSON(), nullable=False),
        sa.Column(
            "last_successful_test_at",
            types.UTCDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_successful_discovery_at",
            types.UTCDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_failed_discovery_at",
            types.UTCDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("stream_count", sa.Integer(), nullable=False),
        sa.Column("created_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loki_configurations")),
        sa.UniqueConstraint("name", name=op.f("uq_loki_configurations_name")),
    )
    with op.batch_alter_table("loki_configurations") as batch_op:
        batch_op.create_index(
            batch_op.f("ix_loki_configurations_enabled"),
            ["enabled"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("loki_configurations") as batch_op:
        batch_op.drop_index(batch_op.f("ix_loki_configurations_enabled"))
    op.drop_table("loki_configurations")
