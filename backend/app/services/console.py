"""Helpers for the console: dated price changes."""

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.db.models import Service, ServicePriceChange


async def apply_due_price_changes(db: AsyncSession, today: date) -> int:
    """Make every price change whose day has come the service's price. Returns how many applied.

    Changes apply in date order, so the latest one due wins. Prices already on an appointment's
    invoice are not touched: invoices keep the price they were issued with.
    """
    due = (
        (
            await db.execute(
                select(ServicePriceChange)
                .where(
                    ServicePriceChange.applied_at.is_(None),
                    ServicePriceChange.effective_from <= today,
                )
                .order_by(ServicePriceChange.effective_from, ServicePriceChange.created_at)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for change in due:
        await db.execute(
            update(Service).where(Service.id == change.service_id).values(base_price=change.price)
        )
        change.applied_at = func.now()
    if due:
        await db.commit()
    return len(due)
