from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import get_settings
from app.infrastructure.database.base import Base
from app.infrastructure.database.models import (  # noqa: F401
    CMDBDatasetModel,
    ConnectorIntegrationModel,
    DocumentModel,
    InventoryAssetModel,
    PrometheusConfigurationModel,
    SourceModel,
    UserModel,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

sync_url = get_settings().database_url.replace("sqlite+aiosqlite", "sqlite")
config.set_main_option("sqlalchemy.url", sync_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
