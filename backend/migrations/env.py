from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from masters_cycling_lab.config import get_settings
from masters_cycling_lab.infrastructure.db.models import Base
from masters_cycling_lab.infrastructure.db.session import CONNECT_ARGS

config = context.config
if config.config_file_name and "database_url" not in config.attributes:
    # Only configure logging for the CLI; tests pass database_url and keep their own logging.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def database_url() -> str:
    url: str | None = config.attributes.get("database_url")
    return url or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url(), poolclass=pool.NullPool, connect_args=CONNECT_ARGS)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
