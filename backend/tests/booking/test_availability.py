import uuid
from datetime import UTC, datetime, time, timedelta

import pytest

from app.core.errors import AppError
from app.db.enums import AppointmentStatus, ExceptionReason
from app.db.models import DentistSchedule, ScheduleException
from app.services.availability import AvailabilityService
from tests.booking.conftest import NY, Practice, future_date, local_utc

LONG_AGO = datetime(2020, 1, 1, tzinfo=UTC)


async def search(practice: Practice, day, service=None, dentist=None, **kwargs):  # type: ignore[no-untyped-def]
    async with practice.ctx.session_factory() as db:
        engine = AvailabilityService(db, practice.ctx.settings, practice.ctx.redis)
        days = await engine.search(
            (service or practice.cleaning).id,
            day,
            kwargs.pop("to", day),
            dentist_id=dentist.id if dentist else None,
            **kwargs,
        )
        return days


def starts_local(days, dentist=None) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        s.start.astimezone(NY).strftime("%H:%M")
        for d in days
        for s in d.slots
        if dentist is None or s.dentist_id == dentist.id
    ]


async def test_slots_follow_the_weekly_template_break_and_buffer(practice: Practice) -> None:
    day = future_date(2)  # a Wednesday
    times = starts_local(
        await search(practice, day, dentist=practice.dentist_a), practice.dentist_a
    )

    assert times[0] == "08:00" and all(t[3:] in {"00", "15", "30", "45"} for t in times)
    # 45 minutes plus a 10 minute buffer must end by 12:30, so the last morning start is 11:30.
    assert "11:30" in times and "11:45" not in times
    assert not any("12:30" <= t < "13:30" for t in times)  # lunch break
    assert "13:30" in times
    # Same rule at closing: last start is 17:00 (ends 17:45, buffer to 17:55).
    assert times[-1] == "17:00"


async def test_slot_instants_are_utc_and_match_clinic_wall_clock(practice: Practice) -> None:
    day = future_date(2)
    [available] = await search(practice, day, dentist=practice.dentist_a)
    first = available.slots[0]
    assert first.start == local_utc(day, 8, 0)
    assert first.start.tzinfo is not None and first.start.utcoffset() == timedelta(0)
    assert first.end - first.start == timedelta(minutes=45)


async def test_each_day_is_returned_even_when_closed(practice: Practice) -> None:
    sunday = future_date(6)
    monday = sunday + timedelta(days=1)
    days = await search(practice, sunday, to=monday)
    assert [d.date for d in days] == [sunday, monday]
    assert days[0].slots == [] and days[1].slots


async def test_saturday_uses_the_half_day_template(practice: Practice) -> None:
    times = starts_local(await search(practice, future_date(5), dentist=practice.dentist_a))
    assert times[0] == "09:00" and times[-1] == "13:00"


async def test_only_dentists_offering_the_service_are_listed(practice: Practice) -> None:
    day = future_date(2)
    crown_days = await search(practice, day, service=practice.crown)
    assert {s.dentist_id for d in crown_days for s in d.slots} == {practice.dentist_a.id}
    cleaning_days = await search(practice, day)
    assert {s.dentist_id for d in cleaning_days for s in d.slots} == {
        practice.dentist_a.id,
        practice.dentist_b.id,
    }


async def test_dentist_filter_and_unknown_dentist(practice: Practice) -> None:
    day = future_date(2)
    only_b = await search(practice, day, dentist=practice.dentist_b)
    assert {s.dentist_id for d in only_b for s in d.slots} == {practice.dentist_b.id}

    async with practice.ctx.session_factory() as db:
        engine = AvailabilityService(db, practice.ctx.settings, practice.ctx.redis)
        with pytest.raises(AppError) as raised:
            await engine.search(practice.cleaning.id, day, day, dentist_id=uuid.uuid4())
    assert raised.value.status_code == 404


async def test_dentist_not_offering_the_service_has_no_slots(practice: Practice) -> None:
    days = await search(
        practice, future_date(2), service=practice.crown, dentist=practice.dentist_b
    )
    assert all(d.slots == [] for d in days)


async def test_longer_services_need_a_longer_window(practice: Practice) -> None:
    times = starts_local(
        await search(practice, future_date(2), service=practice.crown, dentist=practice.dentist_a)
    )
    # 90 + 10 minutes before 12:30 means the last morning start is 10:45.
    assert "10:45" in times and "11:00" not in times


async def test_existing_appointment_blocks_its_time_plus_the_buffer(practice: Practice) -> None:
    day = future_date(2)
    await practice.book_direct(practice.dentist_a, local_utc(day, 10, 0))  # 10:00 to 10:45
    times = starts_local(await search(practice, day, dentist=practice.dentist_a))

    # The latest start that finishes, with buffer, by 10:00 is 09:00.
    assert "09:00" in times and "09:15" not in times
    assert "10:00" not in times and "10:30" not in times
    assert "10:45" not in times and "10:55" not in times
    assert "11:00" in times  # 10:45 end + 10 buffer = 10:55, next grid point is 11:00


async def test_cancelled_and_no_show_appointments_release_their_time(practice: Practice) -> None:
    day = future_date(2)
    for status in (AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW):
        await practice.book_direct(practice.dentist_a, local_utc(day, 10, 0), status=status)
    assert "10:00" in starts_local(await search(practice, day, dentist=practice.dentist_a))


async def test_other_dentists_slots_are_unaffected_by_an_appointment(practice: Practice) -> None:
    day = future_date(2)
    await practice.book_direct(practice.dentist_a, local_utc(day, 10, 0))
    assert "10:00" in starts_local(await search(practice, day, dentist=practice.dentist_b))


async def test_schedule_exceptions_remove_availability(practice: Practice) -> None:
    day = future_date(2)
    async with practice.ctx.session_factory() as db:
        db.add(
            ScheduleException(
                dentist_id=practice.dentist_a.id,
                starts_at=local_utc(day, 15, 0),
                ends_at=local_utc(day, 16, 0),
                reason=ExceptionReason.TRAINING,
            )
        )
        await db.commit()
    times = starts_local(await search(practice, day, dentist=practice.dentist_a))
    assert "14:00" in times and "14:15" not in times  # must finish, with buffer, by 15:00
    assert not any("15:00" <= t < "16:00" for t in times) and "16:00" in times


async def test_full_day_leave_closes_the_dentist(practice: Practice) -> None:
    day = future_date(2)
    async with practice.ctx.session_factory() as db:
        db.add(
            ScheduleException(
                dentist_id=practice.dentist_a.id,
                starts_at=local_utc(day, 0, 0),
                ends_at=local_utc(day + timedelta(days=1), 0, 0),
                reason=ExceptionReason.LEAVE,
            )
        )
        await db.commit()
    assert starts_local(await search(practice, day, dentist=practice.dentist_a)) == []


# --- booking rules from app_settings ------------------------------------------------------


async def test_minimum_notice_hides_near_term_slots(practice: Practice) -> None:
    day = future_date(2)
    now = local_utc(day, 9, 0)  # pretend it is 09:00 on that day
    times = starts_local(
        await search(practice, day, dentist=practice.dentist_a, now=now), practice.dentist_a
    )
    assert times[0] == "11:00"  # two hours of notice


async def test_notice_rule_can_be_bypassed_for_staff(practice: Practice) -> None:
    day = future_date(2)
    now = local_utc(day, 9, 0)
    times = starts_local(
        await search(practice, day, dentist=practice.dentist_a, now=now, enforce_rules=False)
    )
    assert times[0] == "09:00"


async def test_notice_setting_is_read_from_the_database(practice: Practice) -> None:
    await practice.ctx.execute(
        "UPDATE app_settings SET value = '5'::jsonb WHERE key = 'booking_min_notice_hours'"
    )
    try:
        day = future_date(2)
        times = starts_local(
            await search(practice, day, dentist=practice.dentist_a, now=local_utc(day, 9, 0))
        )
        assert times[0] == "14:00"
    finally:
        await practice.ctx.execute(
            "UPDATE app_settings SET value = '2'::jsonb WHERE key = 'booking_min_notice_hours'"
        )


async def test_booking_horizon_limits_how_far_ahead_people_can_book(practice: Practice) -> None:
    today = datetime.now(NY).date()
    near = future_date(2, 5)
    far = near + timedelta(days=7 * 20)  # a Wednesday well beyond 90 days
    assert (far - today).days > 90
    assert starts_local(await search(practice, near, dentist=practice.dentist_a))
    assert starts_local(await search(practice, far, dentist=practice.dentist_a)) == []
    assert starts_local(
        await search(practice, far, dentist=practice.dentist_a, enforce_rules=False)
    )


async def test_same_day_booking_can_be_disabled(practice: Practice) -> None:
    day = future_date(2)
    now = local_utc(day, 6, 0)
    assert starts_local(await search(practice, day, dentist=practice.dentist_a, now=now))
    await practice.ctx.execute(
        "UPDATE app_settings SET value = 'false'::jsonb WHERE key = 'booking_same_day_enabled'"
    )
    try:
        assert starts_local(await search(practice, day, dentist=practice.dentist_a, now=now)) == []
    finally:
        await practice.ctx.execute(
            "UPDATE app_settings SET value = 'true'::jsonb WHERE key = 'booking_same_day_enabled'"
        )


async def test_past_days_have_no_slots(practice: Practice) -> None:
    yesterday = datetime.now(NY).date() - timedelta(days=1)
    assert starts_local(await search(practice, yesterday)) == []


# --- validation, holds and caching -----------------------------------------------------------


async def test_search_range_validation(practice: Practice) -> None:
    day = future_date(2)
    async with practice.ctx.session_factory() as db:
        engine = AvailabilityService(db, practice.ctx.settings, practice.ctx.redis)
        with pytest.raises(AppError) as reversed_range:
            await engine.search(practice.cleaning.id, day, day - timedelta(days=1))
        with pytest.raises(AppError) as too_long:
            await engine.search(practice.cleaning.id, day, day + timedelta(days=31))
        with pytest.raises(AppError) as unknown:
            await engine.search(uuid.uuid4(), day, day)
    assert reversed_range.value.status_code == 422
    assert too_long.value.status_code == 422
    assert unknown.value.status_code == 404


async def test_thirty_one_days_is_allowed(practice: Practice) -> None:
    day = future_date(2)
    days = await search(practice, day, to=day + timedelta(days=30))
    assert len(days) == 31


async def test_held_slots_are_hidden_from_everyone_else(practice: Practice) -> None:
    day = future_date(2)
    start = local_utc(day, 10, 0)
    await practice.hold(practice.dentist_a, start)
    visible = await search(practice, day, dentist=practice.dentist_a)
    assert "10:00" not in starts_local(visible)
    unfiltered = await search(practice, day, dentist=practice.dentist_a, hide_held=False)
    assert "10:00" in starts_local(unfiltered)


async def test_results_are_cached_and_the_cache_is_invalidated_by_new_bookings(
    practice: Practice,
) -> None:
    day = future_date(2)
    async with practice.ctx.session_factory() as db:
        engine = AvailabilityService(db, practice.ctx.settings, practice.ctx.redis)
        first = await engine.search(practice.cleaning.id, day, day, use_cache=True)
        await practice.book_direct(practice.dentist_a, local_utc(day, 10, 0))
        cached = await engine.search(practice.cleaning.id, day, day, use_cache=True)
        assert starts_local(cached, practice.dentist_a) == starts_local(first, practice.dentist_a)

        await engine.invalidate_cache()
        fresh = await engine.search(practice.cleaning.id, day, day, use_cache=True)
        assert "10:00" not in starts_local(fresh, practice.dentist_a)
        keys = [k async for k in practice.ctx.redis.scan_iter("avail:*")]
        assert any(k != "avail:version" for k in keys)
        ttl = await practice.ctx.redis.ttl(next(k for k in keys if k != "avail:version"))
        assert 0 < ttl <= 30


async def test_alternatives_are_the_nearest_open_slots(practice: Practice) -> None:
    day = future_date(2)
    target = local_utc(day, 10, 0)
    async with practice.ctx.session_factory() as db:
        engine = AvailabilityService(db, practice.ctx.settings, practice.ctx.redis)
        nearby = await engine.alternatives(practice.cleaning.id, target, limit=4)
    assert len(nearby) == 4
    assert target not in {s.start for s in nearby}
    distances = [abs((s.start - target).total_seconds()) for s in nearby]
    assert max(distances) <= 15 * 60


# --- daylight saving in the full pipeline -----------------------------------------------------


async def test_schedule_across_the_spring_forward_transition(practice: Practice) -> None:
    sunday = datetime(2027, 3, 14).date()
    async with practice.ctx.session_factory() as db:
        db.add(
            DentistSchedule(
                dentist_id=practice.dentist_a.id,
                weekday=6,
                start_time=time(1, 0),
                end_time=time(5, 0),
            )
        )
        await db.commit()
    days = await search(
        practice, sunday, dentist=practice.dentist_a, now=LONG_AGO, enforce_rules=False
    )
    locals_ = starts_local(days)
    assert locals_[0] == "01:00"
    assert not any(t.startswith("02:") for t in locals_)  # the hour that does not exist
    assert "03:00" in locals_
    first_utc = days[0].slots[0].start
    assert first_utc == datetime(2027, 3, 14, 6, 0, tzinfo=UTC)  # 01:00 EST


async def test_weekday_after_the_transition_keeps_clinic_hours(practice: Practice) -> None:
    before = await search(
        practice,
        datetime(2027, 3, 12).date(),
        dentist=practice.dentist_a,
        now=LONG_AGO,
        enforce_rules=False,
    )
    after = await search(
        practice,
        datetime(2027, 3, 16).date(),
        dentist=practice.dentist_a,
        now=LONG_AGO,
        enforce_rules=False,
    )
    assert starts_local(before)[0] == starts_local(after)[0] == "08:00"
    assert before[0].slots[0].start.hour == 13 and after[0].slots[0].start.hour == 12


async def test_schedule_across_the_fall_back_transition(practice: Practice) -> None:
    sunday = datetime(2027, 11, 7).date()
    async with practice.ctx.session_factory() as db:
        db.add(
            DentistSchedule(
                dentist_id=practice.dentist_a.id,
                weekday=6,
                start_time=time(0, 0),
                end_time=time(4, 0),
            )
        )
        await db.commit()
    days = await search(
        practice, sunday, dentist=practice.dentist_a, now=LONG_AGO, enforce_rules=False
    )
    instants = [s.start for d in days for s in d.slots]
    assert len(instants) == len(set(instants))
    span = days[0].slots[-1].end - days[0].slots[0].start
    assert span > timedelta(hours=4, minutes=30)  # five real hours, minus the final buffer
