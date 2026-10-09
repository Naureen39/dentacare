"""Time the analytics dashboard against the seeded database.

Runs the real application in this process (no network between the script and the API), signs
in as the first administrator by issuing an access token, and times what the dashboard asks for:

* the first load of the Overview tab and of every other tab over 24 months, as the browser
  would send it (all of a tab's requests at once);
* a change of filter that has not been asked before (a new dentist, a new grouping);
* the same views again, which are served from the stored responses.

Targets from the plan: first load under 2.5 seconds, a filter change served from stored
answers under 800 milliseconds.

    uv run python -m scripts.benchmark_dashboard
"""

import asyncio
import statistics
import time
from datetime import timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import Settings
from app.core.security import create_access_token
from app.main import create_app

FIRST_LOAD_LIMIT = 2.5
CACHED_LIMIT = 0.8

TABS = {
    "overview": [
        "/summary",
        "/revenue/trend",
        "/forecast/revenue",
        "/appointments/status-trend",
        "/revenue/by-service",
    ],
    "revenue": [
        "/revenue/service-trends",
        "/revenue/dentist-services",
        "/revenue/trend",
        "/appointments/status-trend",
        "/revenue/by-weekday",
        "/summary",
    ],
    "appointments": [
        "/appointments/heatmap",
        "/appointments/status-trend",
        "/appointments/lead-time",
        "/appointments/channels",
        "/no-show/upcoming-risk",
    ],
    "patients": [
        "/patients/new-vs-returning",
        "/patients/retention-cohorts",
        "/patients/demographics",
        "/patients/top",
    ],
    "dentists": ["/dentists/leaderboard", "/revenue/service-trends"],
    "finance": [
        "/finance/ar-aging",
        "/finance/collection-rate",
        "/revenue/trend",
    ],
    "chatbot": ["/chatbot/summary"],
}


async def timed(
    client: AsyncClient, headers: dict[str, str], paths: list[str], params: dict[str, str]
) -> float:
    start = time.perf_counter()
    responses = await asyncio.gather(
        *(client.get(f"/api/v1/analytics{p}", params=params, headers=headers) for p in paths)
    )
    elapsed = time.perf_counter() - start
    bad = [
        (p, r.status_code) for p, r in zip(paths, responses, strict=True) if r.status_code != 200
    ]
    if bad:
        raise SystemExit(f"requests failed: {bad}")
    return elapsed


async def main() -> None:
    settings = Settings()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as db:
            admin = (
                await db.execute(text("SELECT id FROM users WHERE role = 'admin' LIMIT 1"))
            ).scalar_one()
            today = (await db.execute(text("SELECT clinic_date(now())"))).scalar_one()
            dentist = str(
                (
                    await db.execute(text("SELECT id FROM dentists ORDER BY created_at LIMIT 1"))
                ).scalar_one()
            )
        token = create_access_token(settings, admin, "admin", mfa=True)
        headers = {"Authorization": f"Bearer {token}"}
        async for key in app.state.redis.scan_iter("analytics:*"):  # start with nothing stored
            await app.state.redis.delete(key)

        end = today - timedelta(days=1)
        base = {"from": str(end - timedelta(days=729)), "to": str(end), "granularity": "month"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://bench") as client:
            print(f"24 months, {base['from']} to {base['to']}\n")
            # A running server already has its database and Redis connections open. Opening them
            # is not what a visitor waits for, so do it first with a few small requests.
            short = {**base, "from": str(end - timedelta(days=6))}
            await asyncio.gather(*(timed(client, headers, ["/summary"], short) for _ in range(8)))
            async for key in app.state.redis.scan_iter("analytics:*"):
                await app.state.redis.delete(key)
            print("One request at a time, nothing stored")
            every = sorted({path for paths in TABS.values() for path in paths})
            for path in every:
                one = await timed(client, headers, [path], base)
                print(f"  {path:<34}{one * 1000:>8.0f} ms")
            async for key in app.state.redis.scan_iter("analytics:*"):
                await app.state.redis.delete(key)
            print()
            print(f"{'view':<34}{'first load':>12}{'stored':>10}")
            first_loads: list[float] = []
            for tab, paths in TABS.items():
                cold = await timed(client, headers, paths, base)
                warm = await timed(client, headers, paths, base)
                first_loads.append(cold)
                print(f"{tab:<34}{cold * 1000:>10.0f}ms{warm * 1000:>8.0f}ms")

            print("\nFilter changes on the overview")
            changes = {
                "another dentist": {**base, "dentist_id": dentist},
                "weekly grouping": {**base, "granularity": "week"},
                "insurer payments only": {**base, "payer_type": "insurer"},
                "last 90 days": {
                    **base,
                    "from": str(end - timedelta(days=89)),
                    "granularity": "day",
                },
            }
            cached: list[float] = []
            for name, params in changes.items():
                cold = await timed(client, headers, TABS["overview"], params)
                warm = await timed(client, headers, TABS["overview"], params)
                cached.append(warm)
                print(f"{name:<34}{cold * 1000:>10.0f}ms{warm * 1000:>8.0f}ms")

        slowest_first = max(first_loads)
        slowest_cached = max(cached)
        print(
            f"\nslowest first load {slowest_first * 1000:.0f} ms (limit {FIRST_LOAD_LIMIT * 1000:.0f}), "
            f"slowest stored answer {slowest_cached * 1000:.0f} ms (limit {CACHED_LIMIT * 1000:.0f}), "
            f"median first load {statistics.median(first_loads) * 1000:.0f} ms"
        )
        if slowest_first > FIRST_LOAD_LIMIT or slowest_cached > CACHED_LIMIT:
            raise SystemExit("A target was missed.")


if __name__ == "__main__":
    asyncio.run(main())
