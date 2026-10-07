import asyncio

import asyncpg
from alembic import command
from sqlalchemy import make_url

from app.db.base import Base
from tests.db.conftest import SERVER_URL, alembic_config


async def _fetch(database: str, query: str) -> list[str]:
    url = make_url(SERVER_URL).set(database=database, drivername="postgresql")
    conn = await asyncpg.connect(url.render_as_string(hide_password=False))
    try:
        rows = await conn.fetch(query)
    finally:
        await conn.close()
    return sorted(row[0] for row in rows)


def fetch(database: str, query: str) -> list[str]:
    return asyncio.run(_fetch(database, query))


TABLES = "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
ENUM_TYPES = (
    "SELECT typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
    "WHERE n.nspname = 'public' AND t.typtype = 'e'"
)
SEQUENCES = "SELECT sequencename FROM pg_sequences WHERE schemaname = 'public'"
EXTENSIONS = "SELECT extname FROM pg_extension"


def test_upgrade_creates_every_model_table(scratch_db: str) -> None:
    command.upgrade(alembic_config(scratch_db), "head")

    tables = set(fetch(scratch_db, TABLES))
    assert set(Base.metadata.tables) <= tables
    assert {"vector", "pg_trgm", "btree_gist", "pgcrypto", "citext"} <= set(
        fetch(scratch_db, EXTENSIONS)
    )


def test_downgrade_to_base_removes_everything_it_created(scratch_db: str) -> None:
    config = alembic_config(scratch_db)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert fetch(scratch_db, TABLES) == ["alembic_version"]
    assert fetch(scratch_db, ENUM_TYPES) == []
    assert fetch(scratch_db, SEQUENCES) == []
    extensions = set(fetch(scratch_db, EXTENSIONS))
    assert extensions.isdisjoint({"vector", "pg_trgm", "btree_gist", "pgcrypto", "citext"})


def test_upgrade_after_downgrade_succeeds(scratch_db: str) -> None:
    config = alembic_config(scratch_db)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    assert set(Base.metadata.tables) <= set(fetch(scratch_db, TABLES))


def test_models_and_migrations_have_no_drift(scratch_db: str) -> None:
    config = alembic_config(scratch_db)
    command.upgrade(config, "head")
    # Raises CommandError when autogenerate would produce any operation.
    command.check(config)


def test_default_settings_are_seeded(scratch_db: str) -> None:
    command.upgrade(alembic_config(scratch_db), "head")

    keys = fetch(scratch_db, "SELECT key FROM app_settings")
    assert "booking_min_notice_hours" in keys
    assert "booking_max_horizon_days" in keys
    assert "cancellation_free_hours" in keys
