"""Add managed document inventory and durable delivery jobs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_0005"
down_revision: str | None = "20260720_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("normalized_filename", sa.String(512), nullable=True))
        batch.add_column(sa.Column("document_key", sa.String(2200), nullable=True))
        batch.add_column(sa.Column("mime_type", sa.String(200), nullable=True))
        batch.add_column(sa.Column("content_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("local_status", sa.String(32), nullable=True))
        batch.add_column(sa.Column("delivery_status", sa.String(32), nullable=True))
        batch.add_column(sa.Column("upload_attempt_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("last_upload_attempt_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("uploaded_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("remote_document_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("remote_version_id", sa.String(200), nullable=True))
        batch.add_column(sa.Column("last_error_code", sa.String(100), nullable=True))
        batch.add_column(sa.Column("last_error_message", sa.String(1000), nullable=True))
        batch.add_column(sa.Column("first_seen_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("stable_since_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("entry_method", sa.String(32), nullable=True))
        batch.add_column(sa.Column("version_sequence", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("deletion_requested", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.execute(
        """UPDATE documents SET normalized_filename=lower(filename),
        document_key='filesystem/' || relative_path, mime_type='application/octet-stream',
        content_hash=sha256, local_status='DISCOVERED', delivery_status='NOT_APPLICABLE',
        upload_attempt_count=0, first_seen_at=discovered_at, entry_method='EXTERNAL_SOURCE',
        version_sequence=1, deletion_requested=0, created_at=discovered_at,
        updated_at=last_seen_at"""
    )
    with op.batch_alter_table("documents") as batch:
        for column in (
            "normalized_filename",
            "document_key",
            "mime_type",
            "content_hash",
            "local_status",
            "delivery_status",
            "upload_attempt_count",
            "first_seen_at",
            "entry_method",
            "version_sequence",
            "deletion_requested",
            "created_at",
            "updated_at",
        ):
            batch.alter_column(column, nullable=False)
        batch.create_index(batch.f("ix_documents_local_status"), ["local_status"])
        batch.create_index(batch.f("ix_documents_delivery_status"), ["delivery_status"])

    op.create_table(
        "document_delivery_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("version_sequence", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("spool_path", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_sequence", "operation"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_document_delivery_jobs_document_id"), "document_delivery_jobs", ["document_id"]
    )
    op.create_index(
        op.f("ix_document_delivery_jobs_operation"), "document_delivery_jobs", ["operation"]
    )
    op.create_index(op.f("ix_document_delivery_jobs_state"), "document_delivery_jobs", ["state"])
    op.create_index(
        op.f("ix_document_delivery_jobs_next_retry_at"), "document_delivery_jobs", ["next_retry_at"]
    )
    op.create_index(
        op.f("ix_document_delivery_jobs_correlation_id"),
        "document_delivery_jobs",
        ["correlation_id"],
    )


def downgrade() -> None:
    op.drop_table("document_delivery_jobs")
    with op.batch_alter_table("documents") as batch:
        batch.drop_index(batch.f("ix_documents_delivery_status"))
        batch.drop_index(batch.f("ix_documents_local_status"))
        for column in (
            "deleted_at",
            "updated_at",
            "created_at",
            "deletion_requested",
            "version_sequence",
            "entry_method",
            "stable_since_at",
            "first_seen_at",
            "last_error_message",
            "last_error_code",
            "remote_version_id",
            "remote_document_id",
            "uploaded_at",
            "last_upload_attempt_at",
            "upload_attempt_count",
            "delivery_status",
            "local_status",
            "content_hash",
            "mime_type",
            "document_key",
            "normalized_filename",
        ):
            batch.drop_column(column)
