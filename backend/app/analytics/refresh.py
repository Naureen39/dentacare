"""Refreshing the materialized views behind the analytics endpoints."""

from datetime import UTC, datetime

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models import AppSetting

logger = structlog.get_logger(__name__)

# Order matters: the monthly view is built from the daily one.
VIEWS = (
    "mv_daily_revenue",
    "mv_monthly_revenue",
    "mv_service_mix",
    "mv_dentist_performance",
    "mv_utilization_daily",
    "mv_hourly_heatmap",
    "mv_payer_mix",
    "mv_ar_aging",
    "mv_cohort_retention",
    "mv_chatbot_daily",
)
REFRESHED_AT_KEY = "analytics_refreshed_at"


async def refresh_views(engine: AsyncEngine, *, concurrently: bool = True) -> dict[str, int]:
    """Refresh every view. Concurrent refresh keeps dashboards readable while it runs, but needs
    a populated view, so the first fill (or a failure) falls back to a plain refresh."""
    refreshed = failed = 0
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        for name in VIEWS:
            try:
                try:
                    if not concurrently:
                        raise RuntimeError("plain refresh requested")
                    await connection.execute(
                        text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {name}")  # noqa: S608
                    )
                except Exception:  # noqa: BLE001
                    await connection.execute(text(f"REFRESH MATERIALIZED VIEW {name}"))
                refreshed += 1
            except Exception:  # noqa: BLE001
                failed += 1
                logger.error("materialized_view_refresh_failed", view=name)
        if refreshed:
            stamp = datetime.now(UTC).isoformat()
            statement = insert(AppSetting).values(key=REFRESHED_AT_KEY, value=stamp)
            await connection.execute(
                statement.on_conflict_do_update(
                    index_elements=[AppSetting.key], set_={"value": statement.excluded.value}
                )
            )
    logger.info("analytics_refreshed", refreshed=refreshed, failed=failed)
    return {"refreshed": refreshed, "failed": failed}


async def refreshed_at(db: AsyncSession) -> datetime | None:
    value = (
        await db.execute(
            text("SELECT value #>> '{}' FROM app_settings WHERE key = :k"), {"k": REFRESHED_AT_KEY}
        )
    ).scalar_one_or_none()
    return datetime.fromisoformat(value) if value else None
