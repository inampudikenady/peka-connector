"""Create one protected managed filesystem document source."""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_0006"
down_revision: str | None = "20260721_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_ID = "d0c0a0016f054bd8a123000000000001"
PATH = "/data/sources/documents"
CONFIGURATION = json.dumps(
    {
        "path": PATH,
        "managed": True,
        "scan_interval_seconds": 300,
        "include_patterns": [
            "**/*.txt",
            "**/*.md",
            "**/*.csv",
            "**/*.pdf",
            "**/*.docx",
            "**/*.xlsx",
        ],
        "exclude_patterns": ["**/.*", "**/.DS_Store", "**/.peka-*", "**/~$*"],
    }
)


def upgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.add_column(
            sa.Column("system_managed", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch.create_index(batch.f("ix_sources_system_managed"), ["system_managed"])

    connection = op.get_bind()
    matching = connection.execute(
        sa.text(
            "SELECT id, configuration FROM sources WHERE "
            "plugin_type IN ('filesystem_documents', 'managed_documents') AND "
            "json_extract(configuration, '$.path') = :path "
            "ORDER BY CASE WHEN id = :source_id THEN 0 ELSE 1 END LIMIT 1"
        ),
        {"path": PATH, "source_id": SOURCE_ID},
    ).first()
    if matching is None:
        connection.execute(
            sa.text(
                "INSERT INTO sources "
                "(id, plugin_type, name, enabled, system_managed, configuration, created_at, "
                "updated_at, health_status, last_success_at, last_error, last_scan_at, "
                "file_count, next_scheduled_scan_at, last_scheduled_scan_at, scan_in_progress) "
                "VALUES (:id, 'filesystem_documents', 'Uploaded Documents', 1, 1, :config, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'unknown', NULL, NULL, NULL, 0, "
                "NULL, NULL, 0)"
            ),
            {"id": SOURCE_ID, "config": CONFIGURATION},
        )
    else:
        existing_configuration = json.loads(matching.configuration)
        interval = existing_configuration.get("scan_interval_seconds", 300)
        if not isinstance(interval, int) or not 30 <= interval <= 86400:
            interval = 300
        configuration = json.loads(CONFIGURATION)
        configuration["scan_interval_seconds"] = interval
        connection.execute(
            sa.text(
                "UPDATE sources SET plugin_type='filesystem_documents', "
                "name='Uploaded Documents', system_managed=1, configuration=:config "
                "WHERE id=:id"
            ),
            {"id": matching.id, "config": json.dumps(configuration)},
        )


def downgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.drop_index(batch.f("ix_sources_system_managed"))
        batch.drop_column("system_managed")
