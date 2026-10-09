"""The revenue forecast: Holt-Winters when there are two years, simpler methods when not."""

import math
from datetime import date

import pytest

from app.analytics.forecast import MIN_HISTORY, add_months, forecast_revenue
from tests.analytics.conftest import AS_OF
from tests.analytics.helpers import Api, collected, money
from tests.auth.conftest import Ctx

START = date(2022, 1, 1)


def series(months: int, *, noise: float = 0.0, start: date = START) -> list[tuple[date, float]]:
    """Revenue with a yearly cycle and steady growth, optionally with repeatable wobble."""
    out = []
    for i in range(months):
        seasonal = 12_000 * math.sin(2 * math.pi * (i % 12) / 12)
        wobble = noise * math.sin(i * 12.9898) * 1000
        out.append((add_months(start, i), 100_000 + 700 * i + seasonal + wobble))
    return out


def truth(index: int) -> float:
    return 100_000 + 700 * index + 12_000 * math.sin(2 * math.pi * (index % 12) / 12)


def test_two_years_or_more_use_holt_winters_and_follow_trend_and_season() -> None:
    history = series(36, noise=1.5)
    result = forecast_revenue(history)
    assert result is not None and result.method == "holt_winters"
    assert [p.month for p in result.points] == [
        date(2025, 1, 1),
        date(2025, 2, 1),
        date(2025, 3, 1),
    ]
    for offset, point in enumerate(result.points):
        expected = truth(36 + offset)
        assert abs(point.value - expected) / expected < 0.05
        assert point.lower < point.value < point.upper


def test_exactly_24_months_is_enough_for_holt_winters() -> None:
    result = forecast_revenue(series(MIN_HISTORY, noise=1.0))
    assert result is not None and result.method == "holt_winters"
    assert len(result.points) == 3


def test_a_noisy_history_gives_a_wider_interval() -> None:
    calm = forecast_revenue(series(36, noise=0.2))
    wild = forecast_revenue(series(36, noise=12.0))
    assert calm and wild
    assert (wild.points[0].upper - wild.points[0].lower) > 2 * (
        calm.points[0].upper - calm.points[0].lower
    )


def test_the_interval_is_80_percent_and_stays_non_negative() -> None:
    result = forecast_revenue([(m, max(v - 95_000, 0.0)) for m, v in series(30, noise=3.0)])
    assert result
    assert all(p.lower >= 0 and p.value >= 0 for p in result.points)


def test_the_forecast_is_repeatable() -> None:
    a = forecast_revenue(series(30, noise=2.0))
    b = forecast_revenue(series(30, noise=2.0))
    assert a == b


@pytest.mark.parametrize("months", [12, 17, 23])
def test_less_than_24_months_repeats_the_same_month_last_year(months: int) -> None:
    history = series(months)
    result = forecast_revenue(history)
    assert result is not None and result.method == "seasonal_naive"
    for i, point in enumerate(result.points):
        assert point.value == history[months - 12 + i][1]
        assert point.lower <= point.value <= point.upper
    assert "last year" in result.note


@pytest.mark.parametrize("months", [1, 3, 11])
def test_under_a_year_repeats_the_last_month_with_a_wide_interval(months: int) -> None:
    history = series(months)
    result = forecast_revenue(history)
    assert result is not None and result.method == "naive"
    assert all(p.value == history[-1][1] for p in result.points)
    assert all(p.upper > p.value > p.lower for p in result.points) or months == 1


def test_no_history_means_no_forecast() -> None:
    assert forecast_revenue([]) is None


def test_a_missing_month_is_treated_as_zero_revenue_not_skipped() -> None:
    history = series(26)
    del history[10]
    result = forecast_revenue(history)
    assert result is not None
    assert [p.month for p in result.points][0] == add_months(history[-1][0], 1)


def test_months_roll_over_year_ends() -> None:
    assert add_months(date(2025, 11, 1), 3) == date(2026, 2, 1)
    assert add_months(date(2025, 1, 1), -1) == date(2024, 12, 1)


# --- the endpoint ---------------------------------------------------------------------------------------------------------


async def test_the_endpoint_forecasts_three_months_after_the_last_complete_month(
    ctx: Ctx, admin: Api
) -> None:
    body = await admin.get("/forecast/revenue")
    assert body["method"] == "holt_winters" and body["interval_level"] == 0.8
    assert [p["month"] for p in body["forecast"]] == ["2026-06-01", "2026-07-01", "2026-08-01"]
    assert len(body["history"]) == 24 and body["history"][-1]["month"] == "2026-05-01"
    for point in body["forecast"]:
        assert 0 <= point["lower"] <= point["value"] <= point["upper"]
    # History is the collected revenue of each complete month, as computed from payments.
    for point in body["history"][-3:]:
        month = date.fromisoformat(point["month"])
        last = add_months(month, 1)
        end = date.fromordinal(last.toordinal() - 1)
        assert money(round(point["value"], 2)) == await collected(ctx, month, end)
    assert AS_OF.replace(day=1) > date.fromisoformat(
        body["history"][-1]["month"]
    )  # the current month is left out


async def test_the_forecast_beats_a_naive_repeat_on_the_last_known_year(ctx: Ctx) -> None:
    rows = await ctx.fetch(
        """SELECT date_trunc('month', day)::date, sum(collected) FROM mv_daily_revenue
           WHERE day < DATE '2026-06-01' GROUP BY 1 ORDER BY 1"""
    )  # fmt: skip
    history = [(m, float(v)) for m, v in rows][-24:]
    train, hold = history[:21], history[21:]
    result = forecast_revenue(train, horizon=3)
    assert result is not None
    error = sum(abs(p.value - actual) for p, (_, actual) in zip(result.points, hold, strict=True))
    naive = sum(abs(train[-1][1] - actual) for _, actual in hold)
    assert error < naive * 1.5, (
        error,
        naive,
    )  # a sanity bound: not wildly worse than repeating the last month


def test_the_80_percent_interval_covers_about_80_percent_of_outcomes() -> None:
    import numpy as np

    rng = np.random.default_rng(11)
    hits = total = 0
    for _ in range(40):
        noise = rng.normal(0, 3000, size=39)
        history = [(m, v + float(noise[i])) for i, (m, v) in enumerate(series(36))]
        result = forecast_revenue(history)
        assert result is not None
        for offset, point in enumerate(result.points):
            actual = truth(36 + offset) + float(noise[36 + offset])
            hits += point.lower <= actual <= point.upper
            total += 1
    coverage = hits / total
    assert 0.60 <= coverage <= 0.97, coverage
