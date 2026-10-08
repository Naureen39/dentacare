"""Availability engine.

For one service, a date range and optionally one dentist, it takes each dentist's weekly
template, removes breaks, schedule exceptions and active appointments, and cuts the free
windows into slots on a fixed grid. Each slot must fit the service duration plus a cleanup
buffer. All arithmetic is done on timezone aware UTC instants; clinic local wall clock times
are converted at the edges, so daylight saving transitions are handled by the time zone
database rather than by hand.
"""

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.enums import AppointmentStatus
from app.db.models import (
    Appointment,
    Dentist,
    DentistSchedule,
    DentistService,
    ScheduleException,
    Service,
)
from app.services import holds
from app.services.app_settings import BookingRules

MAX_RANGE_DAYS = 31
CACHE_TTL_SECONDS = 30
CACHE_VERSION_KEY = "avail:version"
ACTIVE_STATUSES = (
    AppointmentStatus.BOOKED,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.CHECKED_IN,
    AppointmentStatus.COMPLETED,
)

Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    dentist_id: uuid.UUID
    dentist_name: str


@dataclass(frozen=True)
class DayAvailability:
    date: date
    slots: list[Slot]


# --- pure interval arithmetic ---------------------------------------------------------


def local_to_utc(day: date, at: time, tz: ZoneInfo) -> datetime:
    """Convert a clinic wall clock time to a UTC instant.

    A time that does not exist (spring forward gap) or occurs twice (fall back) resolves with
    the standard ``fold=0`` rule of the zoneinfo database.
    """
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def subtract_intervals(base: list[Interval], cuts: list[Interval]) -> list[Interval]:
    """Remove every cut from the base intervals. Both inputs may be unsorted."""
    result = sorted(base)
    for cut_start, cut_end in sorted(cuts):
        remaining: list[Interval] = []
        for start, end in result:
            if cut_end <= start or cut_start >= end:
                remaining.append((start, end))
                continue
            if start < cut_start:
                remaining.append((start, cut_start))
            if cut_end < end:
                remaining.append((cut_end, end))
        result = remaining
    return result


def ceil_to_grid(moment: datetime, grid_minutes: int) -> datetime:
    """Round up to the next grid boundary (UTC offsets are whole multiples of the grid)."""
    step = grid_minutes * 60
    seconds = int(moment.timestamp())
    rounded = -(-seconds // step) * step
    return datetime.fromtimestamp(rounded, UTC)


def generate_slots(
    free: list[Interval],
    *,
    duration: timedelta,
    buffer: timedelta,
    grid_minutes: int,
    earliest: datetime,
) -> list[tuple[datetime, datetime]]:
    """Cut free windows into grid aligned slots that fit duration plus buffer."""
    needed = duration + buffer
    step = timedelta(minutes=grid_minutes)
    slots: list[tuple[datetime, datetime]] = []
    for window_start, window_end in free:
        cursor = ceil_to_grid(max(window_start, earliest), grid_minutes)
        while cursor + needed <= window_end:
            slots.append((cursor, cursor + duration))
            cursor += step
    return slots


# --- service --------------------------------------------------------------------------


class AvailabilityService:
    def __init__(self, db: AsyncSession, settings: Settings, redis: Redis) -> None:
        self.db = db
        self.settings = settings
        self.redis = redis
        self.tz = ZoneInfo(settings.clinic_tz)

    def local_date(self, moment: datetime) -> date:
        return moment.astimezone(self.tz).date()

    async def search(
        self,
        service_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        dentist_id: uuid.UUID | None = None,
        now: datetime | None = None,
        enforce_rules: bool = True,
        use_cache: bool = False,
        hide_held: bool = True,
    ) -> list[DayAvailability]:
        if date_to < date_from:
            raise AppError("validation_error", "The end date is before the start date.", 422)
        if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
            raise AppError(
                "validation_error", f"Search at most {MAX_RANGE_DAYS} days at a time.", 422
            )
        service = (
            await self.db.execute(
                select(Service).where(Service.id == service_id, Service.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if service is None:
            raise AppError("not_found", "Service not found.", 404)

        cache_key = None
        if use_cache:
            version = await self.redis.get(CACHE_VERSION_KEY) or "0"
            cache_key = f"avail:{version}:{service_id}:{dentist_id or '*'}:{date_from}:{date_to}"
            cached = await self.redis.get(cache_key)
            if cached is not None:
                days = self._decode(json.loads(cached))
                return await self._without_held(days) if hide_held else days

        rules = await BookingRules.load(self.db)
        days = await self._compute(
            service, date_from, date_to, dentist_id, rules, now or datetime.now(UTC), enforce_rules
        )
        if cache_key is not None:
            await self.redis.set(cache_key, json.dumps(self._encode(days)), ex=CACHE_TTL_SECONDS)
        return await self._without_held(days) if hide_held else days

    async def invalidate_cache(self) -> None:
        await self.redis.incr(CACHE_VERSION_KEY)

    # --- computation ---

    async def _compute(
        self,
        service: Service,
        date_from: date,
        date_to: date,
        dentist_id: uuid.UUID | None,
        rules: BookingRules,
        now: datetime,
        enforce_rules: bool,
    ) -> list[DayAvailability]:
        dentists = await self._eligible_dentists(service.id, dentist_id)
        dates = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
        by_date: dict[date, list[Slot]] = {d: [] for d in dates}
        if not dentists:
            return [DayAvailability(d, []) for d in dates]

        buffer = timedelta(minutes=rules.buffer_minutes)
        duration = timedelta(minutes=service.duration_min)
        range_start = local_to_utc(date_from, time(0, 0), self.tz)
        range_end = local_to_utc(date_to + timedelta(days=1), time(0, 0), self.tz)
        ids = [d.id for d in dentists]

        templates: dict[tuple[uuid.UUID, int], DentistSchedule] = {
            (row.dentist_id, row.weekday): row
            for row in (
                await self.db.execute(
                    select(DentistSchedule).where(DentistSchedule.dentist_id.in_(ids))
                )
            ).scalars()
        }
        exceptions: dict[uuid.UUID, list[Interval]] = defaultdict(list)
        for exc in (
            await self.db.execute(
                select(ScheduleException).where(
                    ScheduleException.dentist_id.in_(ids),
                    ScheduleException.starts_at < range_end,
                    ScheduleException.ends_at > range_start,
                )
            )
        ).scalars():
            exceptions[exc.dentist_id].append((exc.starts_at, exc.ends_at))

        # Existing appointments occupy their slot plus the cleanup buffer that follows.
        busy: dict[uuid.UUID, list[Interval]] = defaultdict(list)
        window = Range(range_start - timedelta(days=1), range_end + timedelta(days=1), bounds="[)")
        for busy_dentist, slot in (
            await self.db.execute(
                select(Appointment.dentist_id, Appointment.slot).where(
                    Appointment.dentist_id.in_(ids),
                    Appointment.status.in_(ACTIVE_STATUSES),
                    Appointment.slot.overlaps(window),
                )
            )
        ).all():
            if slot.lower is None or slot.upper is None:
                continue
            busy[busy_dentist].append((slot.lower, slot.upper + buffer))

        earliest = now + timedelta(hours=rules.min_notice_hours) if enforce_rules else now
        today = self.local_date(now)

        for day in dates:
            if enforce_rules:
                if day > today + timedelta(days=rules.max_horizon_days):
                    continue
                if day == today and not rules.same_day_enabled:
                    continue
                if day < today:
                    continue
            for dentist in dentists:
                template = templates.get((dentist.id, day.weekday()))
                if template is None:
                    continue
                opening = local_to_utc(day, template.start_time, self.tz)
                closing = local_to_utc(day, template.end_time, self.tz)
                free: list[Interval] = [(opening, closing)]
                cuts = list(exceptions[dentist.id]) + busy[dentist.id]
                if template.break_start and template.break_end:
                    cuts.append(
                        (
                            local_to_utc(day, template.break_start, self.tz),
                            local_to_utc(day, template.break_end, self.tz),
                        )
                    )
                free = subtract_intervals(free, cuts)
                for start, end in generate_slots(
                    free,
                    duration=duration,
                    buffer=buffer,
                    grid_minutes=rules.grid_minutes,
                    earliest=earliest,
                ):
                    by_date[day].append(Slot(start, end, dentist.id, dentist.full_name))

        return [
            DayAvailability(d, sorted(by_date[d], key=lambda s: (s.start, s.dentist_name)))
            for d in dates
        ]

    async def _eligible_dentists(
        self, service_id: uuid.UUID, dentist_id: uuid.UUID | None
    ) -> list[Dentist]:
        if dentist_id is not None:
            exists = (
                await self.db.execute(
                    select(Dentist.id).where(Dentist.id == dentist_id, Dentist.is_active.is_(True))
                )
            ).scalar_one_or_none()
            if exists is None:
                raise AppError("not_found", "Dentist not found.", 404)
        stmt = (
            select(Dentist)
            .join(DentistService, DentistService.dentist_id == Dentist.id)
            .where(DentistService.service_id == service_id, Dentist.is_active.is_(True))
            .order_by(Dentist.full_name)
        )
        if dentist_id is not None:
            stmt = stmt.where(Dentist.id == dentist_id)
        return list((await self.db.execute(stmt)).scalars().all())

    async def _without_held(self, days: list[DayAvailability]) -> list[DayAvailability]:
        held = await holds.active_keys(self.redis)
        if not held:
            return days
        return [
            DayAvailability(
                d.date, [s for s in d.slots if holds.hold_key(s.dentist_id, s.start) not in held]
            )
            for d in days
        ]

    # --- cache serialization ---

    @staticmethod
    def _encode(days: list[DayAvailability]) -> list[dict[str, object]]:
        return [
            {
                "date": d.date.isoformat(),
                "slots": [
                    [s.start.isoformat(), s.end.isoformat(), str(s.dentist_id), s.dentist_name]
                    for s in d.slots
                ],
            }
            for d in days
        ]

    @staticmethod
    def _decode(raw: list[dict[str, object]]) -> list[DayAvailability]:
        return [
            DayAvailability(
                date.fromisoformat(str(item["date"])),
                [
                    Slot(
                        datetime.fromisoformat(s[0]),
                        datetime.fromisoformat(s[1]),
                        uuid.UUID(s[2]),
                        s[3],
                    )
                    for s in item["slots"]  # type: ignore[attr-defined]
                ],
            )
            for item in raw
        ]

    # --- helpers for booking ---

    async def is_available(
        self,
        service_id: uuid.UUID,
        dentist_id: uuid.UUID,
        start: datetime,
        *,
        enforce_rules: bool = True,
        now: datetime | None = None,
    ) -> bool:
        day = self.local_date(start)
        days = await self.search(
            service_id,
            day,
            day,
            dentist_id=dentist_id,
            now=now,
            enforce_rules=enforce_rules,
            hide_held=False,
        )
        return any(s.start == start for d in days for s in d.slots)

    async def alternatives(
        self,
        service_id: uuid.UUID,
        around: datetime,
        *,
        limit: int = 5,
        now: datetime | None = None,
    ) -> list[Slot]:
        """The slots nearest in time to a requested moment, across all eligible dentists."""
        centre = self.local_date(around)
        days = await self.search(
            service_id,
            centre - timedelta(days=2),
            centre + timedelta(days=10),
            now=now,
            enforce_rules=True,
        )
        flat = [s for d in days for s in d.slots if s.start != around]
        flat.sort(key=lambda s: abs((s.start - around).total_seconds()))
        return sorted(flat[:limit], key=lambda s: s.start)
