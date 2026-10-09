"""The numbers behind the analytics endpoints.

Most figures come from the materialized views, which hold one row per day (and dentist, service
or payer). Totals are sums over a date range, so the same view answers any granularity. A few
figures need individual rows and read the base tables. Definitions are in docs/metrics.md.
"""

import statistics
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.filters import Filters, Granularity
from app.analytics.refresh import refreshed_at
from app.schemas import analytics as out

ZERO = Decimal("0.00")
LEAD_BUCKETS = [
    ("Same day", 0, 1),
    ("1 to 2 days", 1, 3),
    ("3 to 7 days", 3, 8),
    ("8 to 14 days", 8, 15),
    ("15 to 30 days", 15, 31),
    ("31 days or more", 31, 100_000),
]
AGING = [
    ("0 to 30 days", 0, 30),
    ("31 to 60 days", 31, 60),
    ("61 to 90 days", 61, 90),
    ("Over 90 days", 91, 100_000),
]

# The first completed visit of each patient whose record was created after the data begins.
# Patients who were already in the practice have unknown history, so they are never "new".
FIRST_VISITS = """
    first_visits AS (
        SELECT DISTINCT ON (a.patient_id) a.patient_id, a.dentist_id, a.service_id,
               clinic_date(lower(a.slot)) AS day
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE a.status = 'completed'
          AND p.created_at >= (SELECT min(lower(slot)) FROM appointments)
        ORDER BY a.patient_id, lower(a.slot)
    )
"""


def ratio(num: float | Decimal | None, den: float | Decimal | None) -> float | None:
    if not den:
        return None
    return float(num or 0) / float(den)


def bucket(granularity: str, column: str = "day") -> str:
    if granularity not in ("day", "week", "month", "quarter"):
        raise ValueError(f"unknown granularity {granularity!r}")  # never reached: validated earlier
    return f"date_trunc('{granularity}', {column})::date"


def spark_granularity(days: int) -> Granularity:
    if days <= 45:
        return "day"
    if days <= 200:
        return "week"
    return "month"


class AnalyticsService:
    def __init__(self, db: AsyncSession, today: date) -> None:
        self.db = db
        self.today = today

    # --- plumbing ---

    async def rows(self, sql: str, **params: Any) -> list[Any]:
        return list((await self.db.execute(text(sql), params)).mappings().all())

    async def meta(self, f: Filters) -> out.Meta:
        return out.Meta(
            date_from=f.date_from,
            date_to=f.date_to,
            granularity=f.granularity,
            data_as_of=await refreshed_at(self.db),
        )

    @staticmethod
    def where(
        f: Filters,
        *,
        dentist: bool = True,
        service: bool = True,
        payer: bool = False,
        lo: str = "f",
        hi: str = "t",
        prefix: str = "",
    ) -> tuple[str, dict[str, Any]]:
        clauses = [f"{prefix}day BETWEEN :{lo} AND :{hi}"]
        params: dict[str, Any] = {lo: f.date_from, hi: f.date_to}
        if dentist and f.dentist_id:
            clauses.append(f"{prefix}dentist_id = :dentist_id")
            params["dentist_id"] = f.dentist_id
        if service and f.service_id:
            clauses.append(f"{prefix}service_id = :service_id")
            params["service_id"] = f.service_id
        if payer and f.payer_type:
            clauses.append(f"{prefix}payer_type = CAST(:payer_type AS payer_type)")
            params["payer_type"] = f.payer_type
        return " AND ".join(clauses), params

    @staticmethod
    def visit_filter(f: Filters, alias: str = "a") -> tuple[str, dict[str, Any]]:
        clauses, params = "", {}
        if f.dentist_id:
            clauses += f" AND {alias}.dentist_id = :dentist_id"
            params["dentist_id"] = f.dentist_id
        if f.service_id:
            clauses += f" AND {alias}.service_id = :service_id"
            params["service_id"] = f.service_id
        return clauses, params

    # --- summary ---

    async def summary(self, f: Filters, *, operations_only: bool) -> out.Summary:
        prev = f.previous()
        window = {"f": f.date_from, "t": f.date_to, "pf": prev.date_from, "pt": prev.date_to}
        spark = Filters(
            f.date_from,
            f.date_to,
            spark_granularity(f.days),
            f.dentist_id,
            f.service_id,
            f.payer_type,
        )

        w, p = self.where(f, payer=True, lo="pf", hi="t")
        revenue = (
            await self.rows(
                f"""
                SELECT
                  COALESCE(sum(billed) FILTER (WHERE day BETWEEN :f AND :t), 0) AS billed,
                  COALESCE(sum(billed) FILTER (WHERE day BETWEEN :pf AND :pt), 0) AS p_billed,
                  COALESCE(sum(collected) FILTER (WHERE day BETWEEN :f AND :t), 0) AS collected,
                  COALESCE(sum(collected) FILTER (WHERE day BETWEEN :pf AND :pt), 0) AS p_collected,
                  COALESCE(sum(cohort_collected) FILTER (WHERE day BETWEEN :f AND :t), 0) AS cohort,
                  COALESCE(sum(cohort_collected) FILTER (WHERE day BETWEEN :pf AND :pt), 0) AS p_cohort
                FROM mv_daily_revenue WHERE {w}
                """,
                **{**p, **window},
            )
        )[0]

        w, p = self.where(f, lo="pf", hi="t")
        perf = (
            await self.rows(
                f"""
                SELECT
                  COALESCE(sum(completed) FILTER (WHERE day BETWEEN :f AND :t), 0) AS completed,
                  COALESCE(sum(completed) FILTER (WHERE day BETWEEN :pf AND :pt), 0) AS p_completed,
                  COALESCE(sum(no_show) FILTER (WHERE day BETWEEN :f AND :t), 0) AS no_show,
                  COALESCE(sum(no_show) FILTER (WHERE day BETWEEN :pf AND :pt), 0) AS p_no_show
                FROM mv_dentist_performance WHERE {w}
                """,
                **{**p, **window},
            )
        )[0]

        w, p = self.where(f, service=False, lo="pf", hi="t")
        util = (
            await self.rows(
                f"""
                SELECT
                  COALESCE(sum(booked_minutes) FILTER (WHERE day BETWEEN :f AND :t), 0) AS booked,
                  COALESCE(sum(available_minutes) FILTER (WHERE day BETWEEN :f AND :t), 0) AS avail,
                  COALESCE(sum(booked_minutes) FILTER (WHERE day BETWEEN :pf AND :pt), 0) AS p_booked,
                  COALESCE(sum(available_minutes) FILTER (WHERE day BETWEEN :pf AND :pt), 0) AS p_avail
                FROM mv_utilization_daily WHERE {w}
                """,
                **{**p, **window},
            )
        )[0]

        clause, vp = self.visit_filter(f, "f")
        new = (
            await self.rows(
                f"""
                WITH {FIRST_VISITS.replace("first_visits AS", "fv AS")}
                SELECT
                  count(*) FILTER (WHERE day BETWEEN :f AND :t) AS cur,
                  count(*) FILTER (WHERE day BETWEEN :pf AND :pt) AS prev
                FROM fv f WHERE day BETWEEN :pf AND :t {clause}
                """,
                **{**vp, **window},
            )
        )[0]

        series = await self._sparklines(spark)

        def kpi(
            key: str, label: str, unit: str, value: float | None, previous: float | None,
            *, higher_is_better: bool = True, points: bool = False,
        ) -> out.Kpi:  # fmt: skip
            if value is None or previous is None:
                change = None
            elif points:
                change = (value - previous) * 100
            else:
                change = ratio(value - previous, previous) if previous else None
                change = change * 100 if change is not None else None
            return out.Kpi(
                key=key,
                label=label,
                unit=unit,
                value=value,
                previous=previous,
                change_percent=round(change, 2) if change is not None else None,
                change_kind="points" if points else "relative",
                higher_is_better=higher_is_better,
                sparkline=[out.SparkPoint(period=d, value=v) for d, v in series.get(key, [])],
            )

        completed, p_completed = float(perf["completed"]), float(perf["p_completed"])
        billed, p_billed = float(revenue["billed"]), float(revenue["p_billed"])
        attended = completed + float(perf["no_show"])
        p_attended = p_completed + float(perf["p_no_show"])
        financial = [
            kpi("billed", "Gross billed revenue", "usd", billed, p_billed),
            kpi("collected", "Collected revenue", "usd", float(revenue["collected"]), float(revenue["p_collected"])),
            kpi("collection_rate", "Collection rate", "percent", ratio(revenue["cohort"], revenue["billed"]), ratio(revenue["p_cohort"], revenue["p_billed"]), points=True),
        ]  # fmt: skip
        operations = [
            kpi("completed", "Completed visits", "count", completed, p_completed),
            kpi("revenue_per_visit", "Average revenue per visit", "usd", ratio(billed, completed), ratio(p_billed, p_completed)),
            kpi("utilization", "Utilization", "percent", ratio(util["booked"], util["avail"]), ratio(util["p_booked"], util["p_avail"]), points=True),
            kpi("no_show_rate", "No show rate", "percent", ratio(perf["no_show"], attended), ratio(perf["p_no_show"], p_attended), higher_is_better=False, points=True),
            kpi("new_patients", "New patients", "count", float(new["cur"]), float(new["prev"])),
        ]  # fmt: skip
        if operations_only:
            operations = [k for k in operations if k.key != "revenue_per_visit"]
        return out.Summary(
            meta=await self.meta(f),
            previous_from=prev.date_from,
            previous_to=prev.date_to,
            kpis=operations if operations_only else [*financial, *operations],
        )

    async def _sparklines(self, f: Filters) -> dict[str, list[tuple[date, float | None]]]:
        g = bucket(f.granularity)
        w, p = self.where(f, payer=True)
        rev = await self.rows(
            f"""SELECT {g} AS period, sum(billed) AS billed, sum(collected) AS collected,
                       sum(cohort_collected) AS cohort
                FROM mv_daily_revenue WHERE {w} GROUP BY 1 ORDER BY 1""",
            **p,
        )
        w, p = self.where(f)
        perf = await self.rows(
            f"""SELECT {g} AS period, sum(completed) AS completed, sum(no_show) AS no_show
                FROM mv_dentist_performance WHERE {w} GROUP BY 1 ORDER BY 1""",
            **p,
        )
        w, p = self.where(f, service=False)
        util = await self.rows(
            f"""SELECT {g} AS period, sum(booked_minutes) AS booked, sum(available_minutes) AS avail
                FROM mv_utilization_daily WHERE {w} GROUP BY 1 ORDER BY 1""",
            **p,
        )
        clause, vp = self.visit_filter(f, "f")
        new = await self.rows(
            f"""WITH {FIRST_VISITS.replace("first_visits AS", "fv AS")}
                SELECT {bucket(f.granularity, "f.day")} AS period, count(*) AS n
                FROM fv f WHERE f.day BETWEEN :f AND :t {clause} GROUP BY 1 ORDER BY 1""",
            f=f.date_from, t=f.date_to, **vp,
        )  # fmt: skip
        performance = {r["period"]: r for r in perf}
        out_series: dict[str, list[tuple[date, float | None]]] = defaultdict(list)
        for r in rev:
            period = r["period"]
            out_series["billed"].append((period, float(r["billed"])))
            out_series["collected"].append((period, float(r["collected"])))
            out_series["collection_rate"].append((period, ratio(r["cohort"], r["billed"])))
            done = performance.get(period)
            out_series["revenue_per_visit"].append(
                (period, ratio(r["billed"], done["completed"]) if done else None)
            )
        for r in perf:
            out_series["completed"].append((r["period"], float(r["completed"])))
            out_series["no_show_rate"].append(
                (r["period"], ratio(r["no_show"], r["completed"] + r["no_show"]))
            )
        for r in util:
            out_series["utilization"].append((r["period"], ratio(r["booked"], r["avail"])))
        for r in new:
            out_series["new_patients"].append((r["period"], float(r["n"])))
        return out_series

    # --- revenue ---

    async def revenue_trend(self, f: Filters) -> out.RevenueTrend:
        g = bucket(f.granularity)
        shifted = bucket(f.granularity, "(day + interval '1 year')")
        w, p = self.where(f, payer=True)
        current = await self.rows(
            f"""SELECT {g} AS period, sum(billed) AS billed, sum(collected) AS collected
                FROM mv_daily_revenue WHERE {w} GROUP BY 1""",
            **p,
        )
        prior_from, prior_to = f.date_from - timedelta(days=365), f.date_to - timedelta(days=365)
        w2, p2 = self.where(
            Filters(prior_from, prior_to, f.granularity, f.dentist_id, f.service_id, f.payer_type), payer=True,
        )  # fmt: skip
        prior = await self.rows(
            f"""SELECT {shifted} AS period, sum(billed) AS billed, sum(collected) AS collected
                FROM mv_daily_revenue WHERE {w2} GROUP BY 1""",
            **p2,
        )
        by_period: dict[date, dict[str, Decimal]] = defaultdict(
            lambda: {"b": ZERO, "c": ZERO, "pb": ZERO, "pc": ZERO}
        )
        for r in current:
            by_period[r["period"]].update(b=r["billed"], c=r["collected"])
        for r in prior:
            if r["period"] in by_period:
                by_period[r["period"]].update(pb=r["billed"], pc=r["collected"])
        points = [
            out.RevenuePoint(period=d, billed=v["b"], collected=v["c"], prior_year_billed=v["pb"], prior_year_collected=v["pc"])
            for d, v in sorted(by_period.items())
        ]  # fmt: skip
        return out.RevenueTrend(meta=await self.meta(f), points=points)

    async def revenue_by(self, f: Filters, dimension: str) -> out.RevenueBreakdown:
        column, table, label = {
            "service": ("service_id", "services", "name"),
            "dentist": ("dentist_id", "dentists", "full_name"),
        }[dimension]
        w, p = self.where(f, payer=True, prefix="r.")
        rows = await self.rows(
            f"""SELECT r.{column}::text AS key, d.{label} AS label,
                       sum(r.billed) AS billed, sum(r.collected) AS collected, sum(r.invoices) AS invoices
                FROM mv_daily_revenue r JOIN {table} d ON d.id = r.{column}
                WHERE {w}
                GROUP BY 1, 2 ORDER BY sum(r.billed) DESC, 2""",
            **p,
        )  # fmt: skip
        return out.RevenueBreakdown(meta=await self.meta(f), rows=self._revenue_rows(rows))

    @staticmethod
    def _revenue_rows(rows: Sequence[Any]) -> list[out.RevenueRow]:
        total = sum((r["billed"] for r in rows), ZERO)
        return [
            out.RevenueRow(
                key=r["key"], label=r["label"], billed=r["billed"], collected=r["collected"],
                invoices=int(r["invoices"]), share_of_billed=ratio(r["billed"], total),
            )
            for r in rows
        ]  # fmt: skip

    async def revenue_by_payer(self, f: Filters, *, with_providers: bool) -> out.ByPayer:
        w, p = self.where(f, payer=True)
        types = await self.rows(
            f"""SELECT payer_type::text AS key, initcap(payer_type::text) AS label,
                       sum(billed) AS billed, sum(collected) AS collected, sum(invoices) AS invoices
                FROM mv_daily_revenue WHERE {w} GROUP BY 1, 2 ORDER BY sum(billed) DESC""",
            **p,
        )
        providers: list[Any] = []
        if with_providers:
            providers = await self.rows(
                """SELECT m.provider_key AS key, COALESCE(i.name, 'Self pay') AS label,
                          sum(m.billed) AS billed, sum(m.collected_to_date) AS collected,
                          sum(m.invoices) AS invoices
                   FROM mv_payer_mix m LEFT JOIN insurance_providers i ON i.id = m.insurance_provider_id
                   WHERE m.day BETWEEN :f AND :t GROUP BY 1, 2 ORDER BY sum(m.billed) DESC""",
                f=f.date_from, t=f.date_to,
            )  # fmt: skip
        return out.ByPayer(
            meta=await self.meta(f),
            by_payer_type=self._revenue_rows(types),
            by_provider=self._revenue_rows(providers),
        )

    # --- appointments ---

    async def status_trend(self, f: Filters) -> out.StatusTrend:
        w, p = self.where(f)
        rows = await self.rows(
            f"""SELECT {bucket(f.granularity)} AS period, sum(total) AS total,
                       sum(completed) AS completed, sum(cancelled) AS cancelled,
                       sum(late_cancel) AS late_cancel, sum(no_show) AS no_show, sum(open) AS open
                FROM mv_dentist_performance WHERE {w} GROUP BY 1 ORDER BY 1""",
            **p,
        )
        points = [
            out.StatusPoint(
                period=r["period"], total=int(r["total"]), completed=int(r["completed"]),
                cancelled=int(r["cancelled"]), late_cancelled=int(r["late_cancel"]),
                no_show=int(r["no_show"]), open=int(r["open"]),
                no_show_rate=ratio(r["no_show"], r["completed"] + r["no_show"]),
                cancellation_rate=ratio(r["cancelled"], r["total"]),
            )
            for r in rows
        ]  # fmt: skip
        return out.StatusTrend(meta=await self.meta(f), points=points)

    async def heatmap(self, f: Filters) -> out.Heatmap:
        w, p = self.where(f, service=False)
        rows = await self.rows(
            f"""SELECT (EXTRACT(isodow FROM day)::int - 1) AS weekday, hour,
                       sum(appointments) AS appointments, sum(no_show) AS no_show,
                       sum(completed) AS completed
                FROM mv_hourly_heatmap WHERE {w} GROUP BY 1, 2
                HAVING sum(appointments) > 0 ORDER BY 1, 2""",
            **p,
        )
        cells = [
            out.HeatCell(
                weekday=r["weekday"], hour=r["hour"], appointments=int(r["appointments"]),
                no_show=int(r["no_show"]),
                no_show_rate=ratio(r["no_show"], r["completed"] + r["no_show"]),
            )
            for r in rows
        ]  # fmt: skip
        return out.Heatmap(
            meta=await self.meta(f), cells=cells,
            max_appointments=max((c.appointments for c in cells), default=0),
        )  # fmt: skip

    async def lead_time(self, f: Filters) -> out.LeadTime:
        clause, params = self.visit_filter(f)
        rows = await self.rows(
            f"""SELECT EXTRACT(epoch FROM (lower(a.slot) - a.created_at)) / 86400.0 AS days
                FROM appointments a
                WHERE clinic_date(lower(a.slot)) BETWEEN :f AND :t {clause}""",
            f=f.date_from, t=f.date_to, **params,
        )  # fmt: skip
        days = [max(float(r["days"]), 0.0) for r in rows]
        counts = [sum(1 for d in days if lo <= d < hi) for _, lo, hi in LEAD_BUCKETS]
        return out.LeadTime(
            meta=await self.meta(f),
            buckets=[
                out.LeadBucket(label=name, appointments=n, share=ratio(n, len(days)))
                for (name, _, _), n in zip(LEAD_BUCKETS, counts, strict=True)
            ],
            average_days=round(statistics.fmean(days), 2) if days else None,
            median_days=round(statistics.median(days), 2) if days else None,
            appointments=len(days),
        )

    # --- patients ---

    async def new_vs_returning(self, f: Filters) -> out.NewVsReturning:
        clause, params = self.visit_filter(f)
        rows = await self.rows(
            f"""WITH {FIRST_VISITS},
                visits AS (
                    SELECT a.patient_id, clinic_date(lower(a.slot)) AS day,
                           (fv.patient_id IS NOT NULL
                            AND lower(a.slot) = (SELECT min(lower(x.slot)) FROM appointments x
                                                 WHERE x.patient_id = a.patient_id
                                                   AND x.status = 'completed')) AS is_new
                    FROM appointments a LEFT JOIN first_visits fv ON fv.patient_id = a.patient_id
                    WHERE a.status = 'completed'
                      AND clinic_date(lower(a.slot)) BETWEEN :f AND :t {clause}
                )
                SELECT {bucket(f.granularity)} AS period,
                       count(DISTINCT patient_id) FILTER (WHERE is_new) AS new_patients,
                       count(DISTINCT patient_id) FILTER (WHERE NOT is_new) AS returning_patients,
                       count(*) FILTER (WHERE is_new) AS new_visits,
                       count(*) FILTER (WHERE NOT is_new) AS returning_visits
                FROM visits GROUP BY 1 ORDER BY 1""",
            f=f.date_from, t=f.date_to, **params,
        )  # fmt: skip
        total = (
            await self.rows(
                f"""WITH {FIRST_VISITS},
                    v AS (
                        SELECT a.patient_id, (fv.patient_id IS NOT NULL
                               AND clinic_date(lower(a.slot)) = fv.day) AS is_new
                        FROM appointments a LEFT JOIN first_visits fv ON fv.patient_id = a.patient_id
                        WHERE a.status = 'completed'
                          AND clinic_date(lower(a.slot)) BETWEEN :f AND :t {clause}
                    )
                    SELECT count(DISTINCT patient_id) FILTER (WHERE is_new) AS n,
                           count(DISTINCT patient_id) FILTER (WHERE NOT is_new) AS r FROM v""",
                f=f.date_from, t=f.date_to, **params,
            )
        )[0]  # fmt: skip
        points = [
            out.NewReturningPoint(
                period=r["period"], new_patients=int(r["new_patients"]),
                returning_patients=int(r["returning_patients"]),
                new_visits=int(r["new_visits"]), returning_visits=int(r["returning_visits"]),
            )
            for r in rows
        ]  # fmt: skip
        return out.NewVsReturning(
            meta=await self.meta(f), points=points,
            new_patients=int(total["n"]), returning_patients=int(total["r"]),
        )  # fmt: skip

    async def retention(self, f: Filters, months: int = 12) -> out.RetentionCohorts:
        first_month = f.date_from.replace(day=1)
        rows = await self.rows(
            """SELECT cohort_month, month_offset, active_patients, cohort_size, returned_6m
               FROM mv_cohort_retention
               WHERE cohort_month BETWEEN :f AND :t AND month_offset <= :m
               ORDER BY cohort_month, month_offset""",
            f=first_month, t=f.date_to, m=months,
        )  # fmt: skip
        by_cohort: dict[date, dict[str, Any]] = {}
        for r in rows:
            c = by_cohort.setdefault(
                r["cohort_month"],
                {"size": r["cohort_size"], "returned": r["returned_6m"], "active": {}},
            )
            c["active"][r["month_offset"]] = r["active_patients"]
        this_month = self.today.replace(day=1)
        cohorts: list[out.CohortRow] = []
        mature_size = mature_returned = mature = 0
        for month, c in sorted(by_cohort.items()):
            elapsed = (this_month.year - month.year) * 12 + this_month.month - month.month
            retention = [
                (c["active"].get(k, 0) / c["size"]) if k <= elapsed else None
                for k in range(months + 1)
            ]
            is_mature = (self.today - month).days >= 210 + 31
            if is_mature:
                mature += 1
                mature_size += c["size"]
                mature_returned += c["returned"]
            cohorts.append(
                out.CohortRow(
                    cohort_month=month, cohort_size=c["size"], retention=retention,
                    returned_within_6_months=ratio(c["returned"], c["size"]) if is_mature else None,
                )
            )  # fmt: skip
        return out.RetentionCohorts(
            meta=await self.meta(f), cohorts=cohorts,
            six_month_retention=ratio(mature_returned, mature_size), mature_cohorts=mature,
        )  # fmt: skip

    # --- finance ---

    async def ar_aging(self, f: Filters, as_of: date) -> out.ArAging:
        clause = "AND dentist_id = :dentist_id" if f.dentist_id else ""
        params: dict[str, Any] = {"as_of": as_of}
        if f.dentist_id:
            params["dentist_id"] = f.dentist_id
        rows = await self.rows(
            f"""SELECT :as_of - issued_day AS age, insurer_balance, patient_balance
                FROM mv_ar_aging WHERE issued_day <= :as_of {clause}""",
            **params,
        )
        buckets = []
        for name, lo, hi in AGING:
            chosen = [r for r in rows if lo <= r["age"] <= hi]
            insurer = sum((r["insurer_balance"] for r in chosen), ZERO)
            patient = sum((r["patient_balance"] for r in chosen), ZERO)
            buckets.append(out.AgingBucket(label=name, invoices=len(chosen), insurer=insurer, patient=patient, total=insurer + patient))  # fmt: skip
        total = sum((b.total for b in buckets), ZERO)
        return out.ArAging(
            meta=await self.meta(f), as_of=as_of, buckets=buckets, total_outstanding=total,
            over_90_share=ratio(buckets[-1].total, total),
        )  # fmt: skip

    async def collection_rate(self, f: Filters) -> out.CollectionRate:
        w, p = self.where(f, payer=True)
        rows = await self.rows(
            f"""SELECT {bucket(f.granularity)} AS period, sum(billed) AS billed,
                       sum(cohort_collected) AS collected
                FROM mv_daily_revenue WHERE {w} GROUP BY 1 ORDER BY 1""",
            **p,
        )
        points = [
            out.CollectionPoint(
                period=r["period"], billed=r["billed"], collected_to_date=r["collected"],
                rate=ratio(r["collected"], r["billed"]),
            )
            for r in rows
        ]  # fmt: skip
        billed = sum((r["billed"] for r in rows), ZERO)
        collected = sum((r["collected"] for r in rows), ZERO)
        clause = "AND a.dentist_id = :dentist_id" if f.dentist_id else ""
        extra: dict[str, Any] = {"dentist_id": f.dentist_id} if f.dentist_id else {}
        days_row = (
            await self.rows(
                f"""SELECT avg(EXTRACT(epoch FROM (lp.last_paid - i.issued_at)) / 86400.0) AS days
                    FROM invoices i
                    JOIN appointments a ON a.id = i.appointment_id
                    JOIN LATERAL (SELECT max(paid_at) AS last_paid FROM payments
                                  WHERE invoice_id = i.id) lp ON true
                    WHERE i.status = 'paid' AND clinic_date(i.issued_at) BETWEEN :f AND :t {clause}""",
                f=f.date_from, t=f.date_to, **extra,
            )
        )[0]  # fmt: skip
        average = days_row["days"]
        return out.CollectionRate(
            meta=await self.meta(f), points=points, overall_rate=ratio(collected, billed),
            average_days_to_collect=round(max(float(average), 0.0), 1) if average is not None else None,
        )  # fmt: skip

    async def monthly_collected(self, f: Filters) -> list[tuple[date, float]]:
        """Collected revenue for each complete calendar month before the current one."""
        this_month = self.today.replace(day=1)
        w, p = self.where(
            Filters(date(1970, 1, 1), this_month - timedelta(days=1), "month", f.dentist_id, f.service_id, f.payer_type),
            payer=True,
        )  # fmt: skip
        rows = await self.rows(
            f"""SELECT date_trunc('month', day)::date AS month, sum(collected) AS collected
                FROM mv_daily_revenue WHERE {w} GROUP BY 1 ORDER BY 1""",
            **p,
        )
        return [(r["month"], float(r["collected"])) for r in rows]

    # --- chatbot ---

    async def chatbot(self, f: Filters) -> out.ChatbotSummary:
        rows = await self.rows(
            "SELECT * FROM mv_chatbot_daily WHERE day BETWEEN :f AND :t", f=f.date_from, t=f.date_to
        )

        def total(column: str) -> int:
            return sum(int(r[column]) for r in rows)

        providers: dict[str, dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "tokens": 0, "failovers": 0}
        )
        for r in rows:
            for name, usage in (r["provider_usage"] or {}).items():
                for key in ("calls", "tokens", "failovers"):
                    providers[name][key] += int(usage.get(key) or 0)
        conversations = total("conversations")
        tokens = sum(v["tokens"] for v in providers.values())
        up, down = total("feedback_up"), total("feedback_down")
        days = [
            out.ChatDay(
                day=r["day"], conversations=int(r["conversations"]), turns=int(r["turns"]),
                zero_llm_turns=int(r["zero_llm_turns"]),
                tokens=sum(int(u.get("tokens") or 0) for u in (r["provider_usage"] or {}).values()),
            )
            for r in sorted(rows, key=lambda r: r["day"])
        ]  # fmt: skip
        return out.ChatbotSummary(
            days=days, unanswered=await self.unanswered(f),
            meta=await self.meta(f), conversations=conversations, turns=total("turns"),
            zero_llm_turns=total("zero_llm_turns"),
            zero_llm_share=ratio(total("zero_llm_turns"), total("turns")),
            resolved_without_human=(1 - total("handoffs") / conversations) if conversations else None,
            booking_started=total("booking_started"), booking_slot_chosen=total("booking_slot_chosen"),
            booking_confirmed=total("booking_confirmed"),
            booking_conversion=ratio(total("booking_confirmed"), total("booking_started")),
            handoffs=total("handoffs"),
            providers=[
                out.ProviderTokens(provider=n, calls=v["calls"], tokens=v["tokens"], failovers=v["failovers"])
                for n, v in sorted(providers.items())
            ],
            failovers=sum(v["failovers"] for v in providers.values()),
            feedback_up=up, feedback_down=down, feedback_score=ratio(up, up + down),
            tokens_per_conversation=ratio(tokens, conversations),
        )  # fmt: skip

    async def unanswered(self, f: Filters, limit: int = 10) -> list[out.Unanswered]:
        """User messages whose reply was a hand over to staff or got a thumbs down."""
        from app.services.pii import mask_text

        rows = await self.rows(
            """WITH flagged AS (
                   SELECT (SELECT u.content FROM chat_messages u
                           WHERE u.session_id = m.session_id AND u.role = 'user'
                             AND u.created_at <= m.created_at
                           ORDER BY u.created_at DESC LIMIT 1) AS question
                   FROM chat_messages m
                   WHERE m.role = 'assistant' AND (m.route = 'handoff' OR m.feedback = -1)
                     AND clinic_date(m.created_at) BETWEEN :f AND :t
               )
               SELECT lower(trim(question)) AS question, count(*) AS n FROM flagged
               WHERE question IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 LIMIT :limit""",
            f=f.date_from, t=f.date_to, limit=limit,
        )  # fmt: skip
        return [
            out.Unanswered(question=mask_text(r["question"])[:200], count=int(r["n"])) for r in rows
        ]

    # --- dashboard additions ---

    async def revenue_by_weekday(self, f: Filters) -> out.WeekdayRevenue:
        w, p = self.where(f, payer=True)
        rows = await self.rows(
            f"""SELECT (EXTRACT(isodow FROM day)::int - 1) AS weekday, sum(billed) AS billed,
                       sum(collected) AS collected, sum(invoices) AS invoices
                FROM mv_daily_revenue WHERE {w} GROUP BY 1""",
            **p,
        )
        by_day = {r["weekday"]: r for r in rows}
        counts = [0] * 7
        for n in range(f.days):
            counts[(f.date_from + timedelta(days=n)).weekday()] += 1
        return out.WeekdayRevenue(
            meta=await self.meta(f),
            rows=[
                out.WeekdayRow(
                    weekday=d,
                    billed=by_day[d]["billed"] if d in by_day else ZERO,
                    collected=by_day[d]["collected"] if d in by_day else ZERO,
                    invoices=int(by_day[d]["invoices"]) if d in by_day else 0,
                    days=counts[d],
                )
                for d in range(7)
            ],
        )

    async def service_trends(self, f: Filters, top: int = 10) -> out.ServiceTrends:
        w, p = self.where(f, payer=True, prefix="r.")
        revenue = await self.rows(
            f"""SELECT r.service_id::text AS key, s.name AS label, s.category,
                       sum(r.billed) AS billed, sum(r.collected) AS collected,
                       sum(r.invoices) AS invoices
                FROM mv_daily_revenue r JOIN services s ON s.id = r.service_id
                WHERE {w} GROUP BY 1, 2, 3 ORDER BY sum(r.billed) DESC, 2""",
            **p,
        )
        w2, p2 = self.where(f, prefix="m.")
        mix = {
            r["key"]: r
            for r in await self.rows(
                f"""SELECT m.service_id::text AS key, sum(m.completed) AS visits,
                           sum(m.minutes) AS minutes
                    FROM mv_service_mix m WHERE {w2} GROUP BY 1""",
                **p2,
            )
        }
        leaders = [r["key"] for r in revenue[:top]]
        series: dict[str, list[out.SeriesPoint]] = defaultdict(list)
        if leaders:
            w3, p3 = self.where(f, payer=True)
            for r in await self.rows(
                f"""SELECT service_id::text AS key, {bucket(f.granularity)} AS period,
                           sum(billed) AS billed
                    FROM mv_daily_revenue WHERE {w3} AND service_id::text = ANY(:keys)
                    GROUP BY 1, 2 ORDER BY 2""",
                keys=leaders, **p3,
            ):  # fmt: skip
                series[r["key"]].append(
                    out.SeriesPoint(period=r["period"], value=float(r["billed"]))
                )
        rows = []
        for r in revenue:
            visits = int(mix[r["key"]]["visits"]) if r["key"] in mix else 0
            minutes = int(mix[r["key"]]["minutes"]) if r["key"] in mix else 0
            rows.append(
                out.ServiceRow(
                    key=r["key"], label=r["label"], category=r["category"], billed=r["billed"],
                    collected=r["collected"], invoices=int(r["invoices"]), visits=visits,
                    minutes=minutes,
                    revenue_per_hour=ratio(r["billed"], minutes / 60) if minutes else None,
                    series=series.get(r["key"], []),
                )
            )  # fmt: skip
        return out.ServiceTrends(meta=await self.meta(f), rows=rows)

    async def dentist_services(self, f: Filters) -> out.DentistServiceMatrix:
        w, p = self.where(f, payer=True, prefix="r.")
        rows = await self.rows(
            f"""SELECT r.dentist_id::text AS dentist_id, d.full_name AS dentist,
                       r.service_id::text AS service_id, s.name AS service, sum(r.billed) AS billed
                FROM mv_daily_revenue r
                JOIN dentists d ON d.id = r.dentist_id JOIN services s ON s.id = r.service_id
                WHERE {w} GROUP BY 1, 2, 3, 4 HAVING sum(r.billed) > 0 ORDER BY 2, 4""",
            **p,
        )
        return out.DentistServiceMatrix(
            meta=await self.meta(f), cells=[out.DentistServiceCell(**dict(r)) for r in rows]
        )

    async def leaderboard(self, f: Filters) -> out.Leaderboard:
        w, p = self.where(f, payer=True)
        revenue = {
            r["key"]: r
            for r in await self.rows(
                f"""SELECT dentist_id::text AS key, sum(billed) AS billed,
                           sum(collected) AS collected
                    FROM mv_daily_revenue WHERE {w} GROUP BY 1""",
                **p,
            )
        }
        w, p = self.where(f)
        perf = {
            r["key"]: r
            for r in await self.rows(
                f"""SELECT dentist_id::text AS key, sum(completed) AS completed,
                           sum(no_show) AS no_show
                    FROM mv_dentist_performance WHERE {w} GROUP BY 1""",
                **p,
            )
        }
        w, p = self.where(f, service=False)
        util = {
            r["key"]: r
            for r in await self.rows(
                f"""SELECT dentist_id::text AS key, sum(booked_minutes) AS booked,
                           sum(available_minutes) AS avail
                    FROM mv_utilization_daily WHERE {w} GROUP BY 1""",
                **p,
            )
        }
        names = {
            r["key"]: r["name"]
            for r in await self.rows("SELECT id::text AS key, full_name AS name FROM dentists")
        }
        rows = []
        for key in set(revenue) | set(perf) | set(util):
            rev, pf, ut = revenue.get(key), perf.get(key), util.get(key)
            completed = int(pf["completed"]) if pf else 0
            no_show = int(pf["no_show"]) if pf else 0
            billed = rev["billed"] if rev else ZERO
            rows.append(
                out.LeaderRow(
                    dentist_id=key, dentist=names.get(key, "Unknown"), billed=billed,
                    collected=rev["collected"] if rev else ZERO, visits=completed,
                    no_shows=no_show, no_show_rate=ratio(no_show, completed + no_show),
                    booked_hours=round(float(ut["booked"]) / 60, 1) if ut else 0.0,
                    available_hours=round(float(ut["avail"]) / 60, 1) if ut else 0.0,
                    utilization=ratio(ut["booked"], ut["avail"]) if ut else None,
                    revenue_per_visit=ratio(billed, completed),
                )
            )  # fmt: skip
        rows.sort(key=lambda r: (-r.billed, r.dentist))
        return out.Leaderboard(meta=await self.meta(f), rows=rows)

    async def demographics(self, f: Filters, cipher: Any) -> out.Demographics:
        clause, params = self.visit_filter(f)
        rows = await self.rows(
            f"""SELECT DISTINCT p.id, p.dob_enc, p.source::text AS source
                FROM appointments a JOIN patients p ON p.id = a.patient_id
                WHERE a.status = 'completed' AND p.anonymized_at IS NULL
                  AND clinic_date(lower(a.slot)) BETWEEN :f AND :t {clause}""",
            f=f.date_from, t=f.date_to, **params,
        )  # fmt: skip
        bands = [
            ("0 to 17", 0, 17),
            ("18 to 34", 18, 34),
            ("35 to 49", 35, 49),
            ("50 to 64", 50, 64),
            ("65 and over", 65, 200),
        ]
        counts: dict[str, int] = {name: 0 for name, _, _ in bands} | {"Unknown": 0}
        sources: dict[str, int] = defaultdict(int)
        for r in rows:
            sources[r["source"]] += 1
            raw = cipher.decrypt_optional(r["dob_enc"], "patients.dob") if r["dob_enc"] else None
            if not raw:
                counts["Unknown"] += 1
                continue
            born = date.fromisoformat(raw)
            end = f.date_to
            age = end.year - born.year - ((end.month, end.day) < (born.month, born.day))
            counts[next((n for n, lo, hi in bands if lo <= age <= hi), "Unknown")] += 1
        total = len(rows)
        labels = {
            "web": "Website",
            "chatbot": "Assistant",
            "walk_in": "Walk in",
            "referral": "Referral",
        }
        return out.Demographics(
            meta=await self.meta(f),
            patients=total,
            age_bands=[
                out.Slice(key=n, label=n, patients=c, share=ratio(c, total))
                for n, c in counts.items()
                if c or n != "Unknown"
            ],
            sources=[
                out.Slice(key=k, label=labels.get(k, k), patients=c, share=ratio(c, total))
                for k, c in sorted(sources.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        )

    async def top_patients(self, f: Filters, *, mask: bool, limit: int = 10) -> out.TopPatients:
        clause = "AND a.dentist_id = :dentist_id" if f.dentist_id else ""
        params: dict[str, Any] = {"limit": limit}
        if f.dentist_id:
            params["dentist_id"] = f.dentist_id
        rows = await self.rows(
            f"""SELECT p.id, p.first_name, p.last_name, sum(i.total) AS lifetime,
                       count(DISTINCT a.id) AS visits, max(clinic_date(lower(a.slot))) AS last_visit
                FROM invoices i
                JOIN appointments a ON a.id = i.appointment_id
                JOIN patients p ON p.id = i.patient_id
                WHERE i.status NOT IN ('draft', 'void') AND p.anonymized_at IS NULL {clause}
                GROUP BY p.id ORDER BY sum(i.total) DESC, p.id LIMIT :limit""",
            **params,
        )

        def name(first: str, last: str) -> str:
            return f"{first[:1]}. {last[:1]}." if mask else f"{first} {last}"

        return out.TopPatients(
            meta=await self.meta(f),
            rows=[
                out.TopPatient(
                    patient_id=r["id"], name=name(r["first_name"], r["last_name"]),
                    lifetime_value=r["lifetime"], visits=int(r["visits"]),
                    last_visit=r["last_visit"], masked=mask,
                )
                for r in rows
            ],
        )  # fmt: skip

    async def channels(self, f: Filters) -> out.Channels:
        clause, params = self.visit_filter(f)
        rows = await self.rows(
            f"""SELECT a.channel::text AS key, count(*) AS n,
                       count(*) FILTER (WHERE a.status = 'completed') AS completed
                FROM appointments a
                WHERE a.status <> 'cancelled'
                  AND clinic_date(lower(a.slot)) BETWEEN :f AND :t {clause}
                GROUP BY 1 ORDER BY 2 DESC, 1""",
            f=f.date_from, t=f.date_to, **params,
        )  # fmt: skip
        total = sum(int(r["n"]) for r in rows)
        labels = {"web": "Website", "chatbot": "Assistant", "staff": "Front desk"}
        return out.Channels(
            meta=await self.meta(f),
            rows=[
                out.ChannelRow(
                    key=r["key"], label=labels.get(r["key"], r["key"]),
                    appointments=int(r["n"]), completed=int(r["completed"]),
                    share=ratio(r["n"], total),
                )
                for r in rows
            ],
        )  # fmt: skip
