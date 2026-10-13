"""Print an access token for the first administrator, for tools that cannot sign in with a
second factor (the load tests). It uses the application's own settings and signing key, so it is
as sensitive as the key itself: never run it against a production database.

    uv run python -m scripts.mint_admin_token
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.core.security import create_access_token


async def main() -> None:
    settings = Settings()
    if settings.env == "production":
        raise SystemExit("Refusing to mint a token in production.")
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as db:
            admin = (await db.execute(text("SELECT id FROM users WHERE role = 'admin' LIMIT 1"))).scalar_one()
    finally:
        await engine.dispose()
    print(create_access_token(settings, admin, "admin", mfa=True))


if __name__ == "__main__":
    asyncio.run(main())
