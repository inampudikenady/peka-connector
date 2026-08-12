"""Add independent ServiceNow configuration and normalized caches.

Revision ID: 20260804_0013
Revises: 20260803_0012
"""

from collections.abc import Sequence

from alembic import op
from app.infrastructure.database.models.servicenow import (
    ServiceNowCIModel,
    ServiceNowConfigurationModel,
    ServiceNowJournalModel,
    ServiceNowRecordModel,
    ServiceNowRelationshipModel,
    ServiceNowSyncCursorModel,
)

revision: str = "20260804_0013"
down_revision: str | None = "20260803_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    ServiceNowConfigurationModel.__table__,
    ServiceNowSyncCursorModel.__table__,
    ServiceNowCIModel.__table__,
    ServiceNowRelationshipModel.__table__,
    ServiceNowRecordModel.__table__,
    ServiceNowJournalModel.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
