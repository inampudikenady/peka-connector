"""Milestone one certificates, services, and dependencies.

Revision ID: 20260728_0007
Revises: 59ac2e409f69
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.infrastructure.database import types

revision: str = "20260728_0007"
down_revision: str | None = "59ac2e409f69"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trusted_certificate_authorities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("not_valid_before", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("not_valid_after", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trusted_certificate_authorities")),
        sa.UniqueConstraint("name", name=op.f("uq_trusted_certificate_authorities_name")),
        sa.UniqueConstraint(
            "stored_path", name=op.f("uq_trusted_certificate_authorities_stored_path")
        ),
    )
    with op.batch_alter_table("trusted_certificate_authorities") as batch_op:
        batch_op.create_index(batch_op.f("ix_trusted_certificate_authorities_enabled"), ["enabled"])
        batch_op.create_index(
            batch_op.f("ix_trusted_certificate_authorities_fingerprint_sha256"),
            ["fingerprint_sha256"],
            unique=True,
        )
        batch_op.create_index(
            batch_op.f("ix_trusted_certificate_authorities_not_valid_after"),
            ["not_valid_after"],
        )
    op.create_table(
        "inventory_services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("service_type", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("protocol", sa.String(length=16), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=1000), nullable=False),
        sa.Column("endpoint", sa.String(length=2000), nullable=False),
        sa.Column("first_seen_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["inventory_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["inventory_observations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_services")),
        sa.UniqueConstraint(
            "observation_id",
            "protocol",
            "port",
            "path",
            name=op.f("uq_inventory_services_observation_id"),
        ),
    )
    with op.batch_alter_table("inventory_services") as batch_op:
        batch_op.create_index(batch_op.f("ix_inventory_services_asset_id"), ["asset_id"])
        batch_op.create_index(
            batch_op.f("ix_inventory_services_observation_id"), ["observation_id"]
        )
        batch_op.create_index(batch_op.f("ix_inventory_services_port"), ["port"])
        batch_op.create_index(batch_op.f("ix_inventory_services_service_type"), ["service_type"])
    op.create_table(
        "inventory_dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("target_asset_id", sa.Uuid(), nullable=True),
        sa.Column("source_observation_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("target_reference", sa.String(length=2000), nullable=False),
        sa.Column("evidence", sa.String(length=1000), nullable=False),
        sa.Column("first_seen_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", types.UTCDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_asset_id"], ["inventory_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_observation_id"], ["inventory_observations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["target_asset_id"], ["inventory_assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_dependencies")),
        sa.UniqueConstraint(
            "source_asset_id",
            "relation_type",
            "target_reference",
            "source_observation_id",
            name=op.f("uq_inventory_dependencies_source_asset_id"),
        ),
    )
    with op.batch_alter_table("inventory_dependencies") as batch_op:
        batch_op.create_index(
            batch_op.f("ix_inventory_dependencies_relation_type"), ["relation_type"]
        )
        batch_op.create_index(
            batch_op.f("ix_inventory_dependencies_source_asset_id"), ["source_asset_id"]
        )
        batch_op.create_index(
            batch_op.f("ix_inventory_dependencies_source_observation_id"),
            ["source_observation_id"],
        )
        batch_op.create_index(
            batch_op.f("ix_inventory_dependencies_target_asset_id"), ["target_asset_id"]
        )


def downgrade() -> None:
    op.drop_table("inventory_dependencies")
    op.drop_table("inventory_services")
    op.drop_table("trusted_certificate_authorities")
