from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

# Database fixtures live in tests/db/conftest.py; re-exported so every test package can use them.
from tests.auth.conftest import ctx  # noqa: F401
from tests.booking.conftest import practice  # noqa: F401
from tests.db.conftest import migrated_schema_db, postgres_available  # noqa: F401
from tests.knowledge.conftest import (  # noqa: F401
    fake_embedder,
    indexed_kb_database,
    kb_session,
    model_available,
)


class FakeRedis:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy

    async def ping(self) -> bool:
        if not self.healthy:
            raise ConnectionError("redis unavailable")
        return True

    async def aclose(self) -> None:
        return None


@pytest.fixture
def settings() -> Settings:
    return Settings(env="test", database_url="postgresql+asyncpg://x:x@127.0.0.1:1/x")


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.redis = FakeRedis()
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
