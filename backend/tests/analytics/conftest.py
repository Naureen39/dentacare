"""A seeded clinic for analytics tests.

The database is built once per test session with the same generator the demo uses, scaled down
to 700 patients and a fixed "today", so the data is identical on every run. Tests compare each
endpoint with SQL written separately against the base tables.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

import fakeredis
import pytest
from alembic import command
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.enums import UserRole
from app.main import create_app
from app.services.mailer import InMemoryMailer
from app.services.queue import RecordingJobQueue
from scripts.seed import seed
from tests.auth.conftest import Ctx, make_settings, unique_email
from tests.db.conftest import (
    alembic_config,
    drop_database,
    recreate_database,
    sqlalchemy_url,
)

if TYPE_CHECKING:
    from tests.analytics.helpers import Api

DATABASE = "meridian_analytics_test"
NOW = datetime(2026, 6, 16, 15, 0, tzinfo=UTC)
AS_OF = NOW.date()  # the endpoints are told to treat this as today
PATIENTS = 700
KEEP_TABLES = ("users",)  # only users and what hangs off them are cleared between tests


def analytics_settings(**overrides: Any) -> Settings:
    return make_settings(
        DATABASE,
        rate_limit_chat_per_minute=1000,
        model_dir=str(overrides.pop("model_dir", "models/analytics-test")),
        **overrides,
    )


@pytest.fixture(scope="session")
def seeded_database(postgres_available: None) -> Iterator[str]:
    recreate_database(DATABASE)
    command.upgrade(alembic_config(DATABASE), "head")

    async def run() -> dict[str, Any]:
        settings = analytics_settings()
        engine = create_async_engine(sqlalchemy_url(DATABASE), poolclass=NullPool)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            return await seed(
                factory, settings, now=NOW, patients=PATIENTS, demo=False, engine=engine
            )
        finally:
            await engine.dispose()

    report = asyncio.run(run())
    assert report["appointments"] > 1000, report
    yield DATABASE
    drop_database(DATABASE)


@pytest.fixture
async def ctx(seeded_database: str, tmp_path: Any) -> AsyncIterator[Ctx]:
    """Replaces the shared ``ctx``: the same wiring on the seeded database, which must survive."""
    settings = analytics_settings(model_dir=tmp_path / "models")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        mailer = InMemoryMailer()
        jobs = RecordingJobQueue()
        app.state.redis = redis
        app.state.mailer = mailer
        app.state.jobs = jobs
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            context = Ctx(
                app=app, client=client, mailer=mailer, jobs=jobs, redis=redis, settings=settings,
                session_factory=app.state.session_factory, passwords=app.state.passwords,
            )  # fmt: skip
            context.totp_secrets = {}
            await _clear_users(context.session_factory)
            yield context
            await _clear_users(context.session_factory)
        await redis.aclose()


async def _clear_users(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as db:
        for table in ("audit_logs", "refresh_tokens", "auth_tokens", "mfa_recovery_codes"):
            await db.execute(text(f"DELETE FROM {table}"))  # noqa: S608
        # Accounts made by a test bring a patient or dentist record along; the seeded ones have
        # no login, so anything linked to a user belongs to a test.
        await db.execute(text("DELETE FROM patients WHERE user_id IS NOT NULL"))
        await db.execute(
            text(
                "UPDATE dentists SET user_id = NULL WHERE user_id IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM appointments a WHERE a.dentist_id = dentists.id)"
            )
        )
        await db.execute(text("DELETE FROM dentists WHERE user_id IS NOT NULL"))
        await db.execute(text("DELETE FROM users"))
        await db.commit()


def day(text_value: str) -> date:
    return date.fromisoformat(text_value)


@pytest.fixture
async def admin(ctx: Ctx) -> "Api":  # noqa: UP037
    from tests.analytics.helpers import Api

    email = unique_email("admin")
    await ctx.create_user(email, UserRole.ADMIN)
    return Api(ctx, ctx.auth(await ctx.access_token(email)))
