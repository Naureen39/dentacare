"""Typed access to the key/value rows in ``app_settings``."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppSetting


async def get_setting(session: AsyncSession, key: str, default: Any) -> Any:
    value = (
        await session.execute(select(AppSetting.value).where(AppSetting.key == key))
    ).scalar_one_or_none()
    return default if value is None else value


@dataclass(frozen=True)
class BookingRules:
    min_notice_hours: int = 2
    max_horizon_days: int = 90
    same_day_enabled: bool = True
    buffer_minutes: int = 10
    grid_minutes: int = 15
    cancellation_free_hours: int = 24

    @classmethod
    async def load(cls, session: AsyncSession) -> "BookingRules":
        defaults = cls()
        return cls(
            min_notice_hours=int(
                await get_setting(session, "booking_min_notice_hours", defaults.min_notice_hours)
            ),
            max_horizon_days=int(
                await get_setting(session, "booking_max_horizon_days", defaults.max_horizon_days)
            ),
            same_day_enabled=bool(
                await get_setting(session, "booking_same_day_enabled", defaults.same_day_enabled)
            ),
            buffer_minutes=int(
                await get_setting(session, "booking_buffer_minutes", defaults.buffer_minutes)
            ),
            grid_minutes=int(
                await get_setting(session, "booking_slot_grid_minutes", defaults.grid_minutes)
            ),
            cancellation_free_hours=int(
                await get_setting(
                    session, "cancellation_free_hours", defaults.cancellation_free_hours
                )
            ),
        )
