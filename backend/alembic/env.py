from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (registers all tables)
from alembic import context
from app.core.config import get_settings
from app.database.connection import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata

# Tables owned by LangGraph's checkpointer (created by PostgresSaver.setup(), not by our models).
# Alembic must never touch them: autogenerate would otherwise DROP the workflow checkpoints.
LANGGRAPH_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations",
                    "store", "store_vectors", "store_migrations", "vector_migrations"}


def include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in LANGGRAPH_TABLES:
        return False
    if type_ == "index" and getattr(getattr(obj, "table", None), "name", None) in LANGGRAPH_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, compare_type=True, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          include_object=include_object,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
