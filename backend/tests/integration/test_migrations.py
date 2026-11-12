from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text

from masters_cycling_lab.infrastructure.db.migrations import alembic_config, head_revision, upgrade
from masters_cycling_lab.infrastructure.db.models import Base


def table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_fresh_database_migrates_to_head(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        version = connection.execute(text("select version_num from alembic_version")).scalar_one()
        vector = connection.execute(text("select extversion from pg_extension where extname = 'vector'")).scalar()
    assert version == head_revision()
    assert vector is not None


def test_models_match_the_migrations(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    assert differences == []


def test_downgrade_then_upgrade_again(empty_database: str) -> None:
    upgrade(empty_database)
    assert "documents" in table_names(empty_database)

    command.downgrade(alembic_config(empty_database), "base")
    assert table_names(empty_database) <= {"alembic_version"}

    upgrade(empty_database)
    assert {"documents", "chunk_embeddings", "query_evidence"} <= table_names(empty_database)
