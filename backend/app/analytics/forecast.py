"""Revenue forecast: Holt-Winters on monthly collected revenue, with a seasonal naive fallback."""

import warnings
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist, pstdev

import numpy as np
from statsmodels.tsa.holtwinters import ExponentialSmoothing

HORIZON = 3
SEASON = 12
MIN_HISTORY = 24  # two full seasons are needed to estimate the seasonal pattern
LEVEL = 0.80
SIMULATIONS = 1000
SEED = 20260101
FITTED_PARAMETERS = 16  # level, trend, 11 seasonal terms and 3 smoothing weights


@dataclass(frozen=True)
class Point:
    month: date
    value: float
    lower: float
    upper: float


@dataclass(frozen=True)
class Forecast:
    method: str
    note: str
    points: list[Point]


def add_months(month: date, n: int) -> date:
    index = month.year * 12 + month.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def forecast_revenue(history: list[tuple[date, float]], horizon: int = HORIZON) -> Forecast | None:
    """Forecast the next ``horizon`` months. ``history`` is consecutive complete months, oldest
    first. Returns None when there is nothing to base a forecast on."""
    if not history:
        return None
    months = [m for m, _ in history]
    values = [v for _, v in history]
    # Missing months inside the range would shift the seasonal pattern, so require a clean run.
    expected = [add_months(months[0], i) for i in range(len(months))]
    if months != expected:
        values = _fill_gaps(history)
    last = add_months(months[-1], 1)
    future = [add_months(last, i) for i in range(horizon)]
    if len(values) >= MIN_HISTORY:
        return _holt_winters(values, future)
    if len(values) >= SEASON:
        return _seasonal_naive(values, future)
    return _naive(values, future)


def _fill_gaps(history: list[tuple[date, float]]) -> list[float]:
    by_month = dict(history)
    first, last = history[0][0], history[-1][0]
    out = []
    month = first
    while month <= last:
        out.append(by_month.get(month, 0.0))
        month = add_months(month, 1)
    return out


def _holt_winters(values: list[float], future: list[date]) -> Forecast:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ExponentialSmoothing(
            np.asarray(values, dtype=float),
            trend="add",
            seasonal="add",
            seasonal_periods=SEASON,
            initialization_method="estimated",
        ).fit()
        point = np.asarray(model.forecast(len(future)))
        # The fit estimates about 16 numbers from 24 or more points, so the in sample residuals
        # understate the real error. Correct the spread for the degrees of freedom used.
        dof = max(len(values) - FITTED_PARAMETERS, 4)
        sigma = float(np.sqrt(model.sse / dof))
        errors = np.random.default_rng(SEED).normal(0.0, sigma, size=(len(future), SIMULATIONS))
        paths = np.asarray(
            model.simulate(
                len(future),
                repetitions=SIMULATIONS,
                error="add",
                random_errors=errors,
                random_state=SEED,
            )
        )
    paths = paths.reshape(len(future), -1)
    lower = np.quantile(paths, (1 - LEVEL) / 2, axis=1)
    upper = np.quantile(paths, 1 - (1 - LEVEL) / 2, axis=1)
    points = [
        Point(m, max(float(p), 0.0), max(float(lo), 0.0), max(float(hi), 0.0))
        for m, p, lo, hi in zip(future, point, lower, upper, strict=True)
    ]
    return Forecast(
        "holt_winters",
        "Holt-Winters with additive trend and seasonality (12 months) on monthly collected revenue.",
        points,
    )


def _seasonal_naive(values: list[float], future: list[date]) -> Forecast:
    """The same month a year earlier. The interval comes from how much months differ from the
    same month a year before, so it is wide when the history is short."""
    changes = [values[i] - values[i - SEASON] for i in range(SEASON, len(values))]
    spread = pstdev(changes) if len(changes) > 1 else 0.2 * (sum(values) / len(values))
    z = NormalDist().inv_cdf(0.5 + LEVEL / 2)
    points = []
    n = len(values)
    for i, month in enumerate(future):
        base = values[n - SEASON + i] if n - SEASON + i < n else values[-1]
        points.append(Point(month, base, max(base - z * spread, 0.0), base + z * spread))
    return Forecast(
        "seasonal_naive",
        f"Less than {MIN_HISTORY} months of history, so each month repeats the same month last year.",
        points,
    )


def _naive(values: list[float], future: list[date]) -> Forecast:
    base = values[-1]
    spread = pstdev(values) if len(values) > 2 else 0.25 * base
    z = NormalDist().inv_cdf(0.5 + LEVEL / 2)
    points = [Point(m, base, max(base - z * spread, 0.0), base + z * spread) for m in future]
    return Forecast(
        "naive",
        f"Less than {SEASON} months of history, so the last month is repeated with a wide interval.",
        points,
    )
