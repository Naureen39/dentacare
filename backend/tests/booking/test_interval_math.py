from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.availability import (
    ceil_to_grid,
    generate_slots,
    local_to_utc,
    subtract_intervals,
)

NY = ZoneInfo("America/New_York")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2027, 6, 1, hour, minute, tzinfo=UTC)


# --- subtract_intervals ----------------------------------------------------------------


def test_subtract_nothing_returns_the_base() -> None:
    assert subtract_intervals([(at(8), at(12))], []) == [(at(8), at(12))]


def test_subtract_from_the_middle_splits_the_window() -> None:
    assert subtract_intervals([(at(8), at(18))], [(at(12), at(13))]) == [
        (at(8), at(12)),
        (at(13), at(18)),
    ]


def test_subtract_from_the_edges_trims_the_window() -> None:
    assert subtract_intervals([(at(8), at(12))], [(at(7), at(9)), (at(11), at(13))]) == [
        (at(9), at(11))
    ]


def test_subtract_everything_leaves_nothing() -> None:
    assert subtract_intervals([(at(8), at(12))], [(at(7), at(13))]) == []


def test_adjacent_cut_does_not_change_the_window() -> None:
    assert subtract_intervals([(at(8), at(12))], [(at(12), at(13)), (at(6), at(8))]) == [
        (at(8), at(12))
    ]


def test_overlapping_and_unsorted_cuts_are_handled() -> None:
    result = subtract_intervals(
        [(at(8), at(18))], [(at(14), at(15)), (at(9), at(11)), (at(10), at(12))]
    )
    assert result == [(at(8), at(9)), (at(12), at(14)), (at(15), at(18))]


# --- grid and slot generation ----------------------------------------------------------


@pytest.mark.parametrize(
    ("minute", "expected"), [(0, 0), (1, 15), (14, 15), (15, 15), (16, 30), (46, 60)]
)
def test_ceil_to_grid(minute: int, expected: int) -> None:
    result = ceil_to_grid(at(9, 0) + timedelta(minutes=minute), 15)
    assert result == at(9, 0) + timedelta(minutes=expected)


def test_slots_fit_duration_plus_buffer_inside_the_window() -> None:
    slots = generate_slots(
        [(at(8), at(10))],
        duration=timedelta(minutes=45),
        buffer=timedelta(minutes=10),
        grid_minutes=15,
        earliest=at(0),
    )
    starts = [s[0] for s in slots]
    # 45 + 10 = 55 minutes must fit before 10:00, so the last start is 09:00 (ends 09:45, +10).
    assert starts[0] == at(8) and starts[-1] == at(9, 0)
    assert all(end - start == timedelta(minutes=45) for start, end in slots)
    assert len(starts) == 5  # 08:00, 08:15, 08:30, 08:45, 09:00


def test_window_too_short_for_buffer_yields_no_slot() -> None:
    slots = generate_slots(
        [(at(8), at(8, 50))],
        duration=timedelta(minutes=45),
        buffer=timedelta(minutes=10),
        grid_minutes=15,
        earliest=at(0),
    )
    assert slots == []


def test_earliest_start_is_respected_and_rounded_up_to_the_grid() -> None:
    slots = generate_slots(
        [(at(8), at(12))],
        duration=timedelta(minutes=30),
        buffer=timedelta(0),
        grid_minutes=15,
        earliest=at(9, 7),
    )
    assert slots[0][0] == at(9, 15)


def test_window_starting_off_grid_starts_on_the_next_grid_point() -> None:
    slots = generate_slots(
        [(at(8, 5), at(10))],
        duration=timedelta(minutes=30),
        buffer=timedelta(0),
        grid_minutes=15,
        earliest=at(0),
    )
    assert slots[0][0] == at(8, 15)


# --- daylight saving -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected_utc_hour"),
    [
        (date(2027, 3, 13), 13),  # Saturday before the change: EST, UTC-5
        (date(2027, 3, 15), 12),  # Monday after the change: EDT, UTC-4
        (date(2027, 11, 6), 12),  # Saturday before the change back: EDT
        (date(2027, 11, 8), 13),  # Monday after the change back: EST
    ],
)
def test_eight_oclock_local_maps_to_the_right_utc_hour(day: date, expected_utc_hour: int) -> None:
    assert local_to_utc(day, time(8, 0), NY) == datetime(
        day.year, day.month, day.day, expected_utc_hour, 0, tzinfo=UTC
    )


def test_spring_forward_day_is_one_hour_shorter() -> None:
    start = local_to_utc(date(2027, 3, 14), time(1, 0), NY)
    end = local_to_utc(date(2027, 3, 14), time(5, 0), NY)
    assert end - start == timedelta(hours=3)


def test_fall_back_day_is_one_hour_longer() -> None:
    start = local_to_utc(date(2027, 11, 7), time(0, 0), NY)
    end = local_to_utc(date(2027, 11, 7), time(4, 0), NY)
    assert end - start == timedelta(hours=5)


def test_slots_on_the_spring_forward_day_never_fall_in_the_missing_hour() -> None:
    day = date(2027, 3, 14)
    window = (local_to_utc(day, time(1, 0), NY), local_to_utc(day, time(5, 0), NY))
    slots = generate_slots(
        [window],
        duration=timedelta(minutes=30),
        buffer=timedelta(0),
        grid_minutes=15,
        earliest=window[0] - timedelta(days=1),
    )
    local_hours = {s[0].astimezone(NY).hour for s in slots}
    assert 2 not in local_hours  # 02:00 to 02:59 does not exist that day
    assert local_hours == {1, 3, 4}
    assert len(slots) == 11  # 3 real hours, last 30 minute slot starts at 04:30 local


def test_slots_on_the_fall_back_day_cover_the_repeated_hour() -> None:
    day = date(2027, 11, 7)
    window = (local_to_utc(day, time(0, 0), NY), local_to_utc(day, time(4, 0), NY))
    slots = generate_slots(
        [window],
        duration=timedelta(hours=1),
        buffer=timedelta(0),
        grid_minutes=60,
        earliest=window[0] - timedelta(days=1),
    )
    assert len(slots) == 5  # five real hours between midnight and 04:00 EST
    assert len({s[0] for s in slots}) == 5
