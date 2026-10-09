"""Analytics endpoints: KPIs, trends, finance, forecast, no show risk and the chatbot."""

import csv
import io
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.analytics import filters as flt
from app.analytics.filters import Filters, Scope
from app.analytics.forecast import LEVEL, forecast_revenue
from app.analytics.noshow import model as noshow
from app.analytics.refresh import refresh_views
from app.analytics.service import AnalyticsService
from app.core.deps import AppSettings, Cipher, CurrentUser, RedisDep, Session, require_roles
from app.core.errors import AppError
from app.db.enums import UserRole
from app.schemas import analytics as out
from app.schemas.analytics import Granularity
from app.services import audit
from app.services.audit import AuditAction
from app.services.patients import dentist_id_for_user

router = APIRouter(prefix="/analytics", tags=["analytics"])

Staff = Annotated[
    CurrentUser,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST, UserRole.DENTIST)),
]
AdminUser = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]
CACHE_SECONDS = 300
VERSION_KEY = "analytics:version"


@dataclass
class Context:
    db: Any
    settings: Any
    redis: Any
    cipher: Any
    scope: Scope
    filters: Filters
    today: date
    now: datetime
    service: AnalyticsService
    user: CurrentUser


async def get_context(
    request: Request,
    current: Staff,
    db: Session,
    settings: AppSettings,
    redis: RedisDep,
    cipher: Cipher,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    granularity: Granularity = "month",
    dentist_id: Annotated[uuid.UUID | None, Query()] = None,
    service_id: Annotated[uuid.UUID | None, Query()] = None,
    payer_type: Literal["patient", "insurer"] | None = None,
    as_of: Annotated[date | None, Query(description="Treat this date as today.")] = None,
) -> Context:
    tz = ZoneInfo(settings.clinic_tz)
    real_now = datetime.now(UTC)
    today = as_of or real_now.astimezone(tz).date()
    now = datetime.combine(as_of, time(8, 0), tzinfo=tz).astimezone(UTC) if as_of else real_now
    scope = Scope(
        current.role,
        await dentist_id_for_user(db, current) if current.role is UserRole.DENTIST else None,
    )
    filters = flt.resolve(
        scope, today=today, date_from=date_from, date_to=date_to, granularity=granularity,
        dentist_id=dentist_id, service_id=service_id, payer_type=payer_type,
    )  # fmt: skip
    return Context(
        db,
        settings,
        redis,
        cipher,
        scope,
        filters,
        today,
        now,
        AnalyticsService(db, today),
        current,
    )


Ctx = Annotated[Context, Depends(get_context)]


async def cached[T: BaseModel](
    ctx: Context, name: str, model: type[T], compute: Callable[[], Awaitable[T]], extra: str = ""
) -> T:
    """Serve a stored response for five minutes. Keys include the caller's scope, so a dentist's
    figures are never served to someone else."""
    version = await ctx.redis.get(VERSION_KEY) or "0"
    scope = f"{ctx.scope.role.value}:{ctx.scope.dentist_id}"
    key = f"analytics:{version}:{name}:{ctx.filters.key()}:{ctx.today}:{scope}:{extra}"
    hit = await ctx.redis.get(key)
    if hit:
        value = model.model_validate_json(hit)
        value.meta.cached = True  # type: ignore[attr-defined]
        return value
    value = await compute()
    await ctx.redis.set(key, value.model_dump_json(), ex=CACHE_SECONDS)
    return value


# --- endpoints ----------------------------------------------------------------------------------------------------------


async def _summary(ctx: Context) -> out.Summary:
    ops = ctx.scope.role is UserRole.RECEPTIONIST
    return await cached(
        ctx, "summary", out.Summary, lambda: ctx.service.summary(ctx.filters, operations_only=ops)
    )


@router.get("/summary", response_model=out.Summary)
async def summary(ctx: Ctx) -> out.Summary:
    """KPI cards with the previous period, the change and a sparkline."""
    return await _summary(ctx)


@router.get("/revenue/trend", response_model=out.RevenueTrend)
async def revenue_trend(ctx: Ctx) -> out.RevenueTrend:
    flt.require(ctx.scope, flt.OWN_FINANCE)
    return await cached(
        ctx, "revenue_trend", out.RevenueTrend, lambda: ctx.service.revenue_trend(ctx.filters)
    )


@router.get("/revenue/by-service", response_model=out.RevenueBreakdown)
async def revenue_by_service(ctx: Ctx) -> out.RevenueBreakdown:
    flt.require(ctx.scope, flt.OWN_FINANCE)
    return await cached(
        ctx,
        "by_service",
        out.RevenueBreakdown,
        lambda: ctx.service.revenue_by(ctx.filters, "service"),
    )


@router.get("/revenue/by-dentist", response_model=out.RevenueBreakdown)
async def revenue_by_dentist(ctx: Ctx) -> out.RevenueBreakdown:
    flt.require(ctx.scope, flt.FINANCE)
    return await cached(
        ctx,
        "by_dentist",
        out.RevenueBreakdown,
        lambda: ctx.service.revenue_by(ctx.filters, "dentist"),
    )


@router.get("/revenue/by-payer", response_model=out.ByPayer)
async def revenue_by_payer(ctx: Ctx) -> out.ByPayer:
    flt.require(ctx.scope, flt.OWN_FINANCE)
    providers = ctx.scope.role is UserRole.ADMIN
    return await cached(
        ctx, "by_payer", out.ByPayer,
        lambda: ctx.service.revenue_by_payer(ctx.filters, with_providers=providers),
    )  # fmt: skip


@router.get("/appointments/status-trend", response_model=out.StatusTrend)
async def status_trend(ctx: Ctx) -> out.StatusTrend:
    return await cached(
        ctx, "status_trend", out.StatusTrend, lambda: ctx.service.status_trend(ctx.filters)
    )


@router.get("/appointments/heatmap", response_model=out.Heatmap)
async def heatmap(ctx: Ctx) -> out.Heatmap:
    return await cached(ctx, "heatmap", out.Heatmap, lambda: ctx.service.heatmap(ctx.filters))


@router.get("/appointments/lead-time", response_model=out.LeadTime)
async def lead_time(ctx: Ctx) -> out.LeadTime:
    return await cached(ctx, "lead_time", out.LeadTime, lambda: ctx.service.lead_time(ctx.filters))


@router.get("/patients/new-vs-returning", response_model=out.NewVsReturning)
async def new_vs_returning(ctx: Ctx) -> out.NewVsReturning:
    return await cached(
        ctx, "new_returning", out.NewVsReturning, lambda: ctx.service.new_vs_returning(ctx.filters)
    )


@router.get("/patients/retention-cohorts", response_model=out.RetentionCohorts)
async def retention_cohorts(ctx: Ctx) -> out.RetentionCohorts:
    flt.require(ctx.scope, flt.CLINIC)
    return await cached(
        ctx, "retention", out.RetentionCohorts, lambda: ctx.service.retention(ctx.filters)
    )


@router.get("/finance/ar-aging", response_model=out.ArAging)
async def ar_aging(ctx: Ctx) -> out.ArAging:
    flt.require(ctx.scope, flt.FINANCE)
    return await cached(
        ctx, "ar_aging", out.ArAging, lambda: ctx.service.ar_aging(ctx.filters, ctx.today)
    )


@router.get("/finance/collection-rate", response_model=out.CollectionRate)
async def collection_rate(ctx: Ctx) -> out.CollectionRate:
    flt.require(ctx.scope, flt.FINANCE)
    return await cached(
        ctx, "collection", out.CollectionRate, lambda: ctx.service.collection_rate(ctx.filters)
    )


async def _forecast(ctx: Context) -> out.RevenueForecast:
    history = await ctx.service.monthly_collected(ctx.filters)
    result = forecast_revenue(history)
    if result is None:
        raise AppError("no_data", "There is no revenue history to forecast from.", 404)
    return out.RevenueForecast(
        meta=await ctx.service.meta(ctx.filters),
        method=result.method,
        method_note=result.note,
        interval_level=LEVEL,
        history=[out.ForecastPoint(month=m, value=v) for m, v in history[-24:]],
        forecast=[out.ForecastPoint(month=p.month, value=round(p.value, 2), lower=round(p.lower, 2), upper=round(p.upper, 2)) for p in result.points],
    )  # fmt: skip


@router.get("/forecast/revenue", response_model=out.RevenueForecast)
async def forecast_endpoint(ctx: Ctx) -> out.RevenueForecast:
    """The next three months of collected revenue with an 80 percent interval."""
    flt.require(ctx.scope, flt.FINANCE)
    return await cached(ctx, "forecast", out.RevenueForecast, lambda: _forecast(ctx))


async def _risk(ctx: Context) -> out.UpcomingRisk:
    directory = Path(ctx.settings.model_dir)
    tz = ZoneInfo(ctx.settings.clinic_tz)
    db = ctx.db
    row = await noshow.active_model(db)
    meta = await ctx.service.meta(ctx.filters)
    if row is None:
        return out.UpcomingRisk(meta=meta, model_version=None, model_auc=None, base_rate=None, rows=[], note="No no show model has been trained yet. Run scripts/train_no_show.py.")  # fmt: skip
    missing = (
        await db.execute(
            text(
                """SELECT count(*) FROM appointments a
                   LEFT JOIN appointment_risk r ON r.appointment_id = a.id
                   WHERE a.status IN ('booked', 'confirmed') AND lower(a.slot) >= :now
                     AND lower(a.slot) < :end AND (r.appointment_id IS NULL OR r.model_version <> :v)"""
            ),
            {
                "now": ctx.now,
                "end": ctx.now.replace(microsecond=0) + timedelta(days=noshow.SCORING_DAYS),
                "v": row.version,
            },
        )
    ).scalar_one()
    if missing:
        await noshow.score_upcoming(db, ctx.cipher, directory, tz, now=ctx.now)
    clause = "AND a.dentist_id = :dentist_id" if ctx.filters.dentist_id else ""
    params: dict[str, Any] = {"now": ctx.now, "end": ctx.now + timedelta(days=noshow.SCORING_DAYS)}
    if ctx.filters.dentist_id:
        params["dentist_id"] = ctx.filters.dentist_id
    rows = (
        (
            await db.execute(
                text(
                    f"""SELECT a.id, lower(a.slot) AS start, p.first_name || ' ' || p.last_name AS patient,
                           s.name AS service, d.id AS dentist_id, d.full_name AS dentist,
                           a.status::text AS status, r.score, r.drivers
                    FROM appointment_risk r
                    JOIN appointments a ON a.id = r.appointment_id
                    JOIN patients p ON p.id = a.patient_id
                    JOIN services s ON s.id = a.service_id
                    JOIN dentists d ON d.id = a.dentist_id
                    WHERE a.status IN ('booked', 'confirmed') AND lower(a.slot) >= :now
                      AND lower(a.slot) < :end {clause}
                    ORDER BY r.score DESC, lower(a.slot)"""  # noqa: S608
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    thresholds = row.metrics["thresholds"]
    result = [
        out.RiskRow(
            appointment_id=r["id"], start=r["start"], patient_name=r["patient"], service_name=r["service"],
            dentist_id=r["dentist_id"], dentist_name=r["dentist"], status=r["status"], score=float(r["score"]),
            level=noshow.level(float(r["score"]), thresholds),
            drivers=[out.RiskDriver(**d) for d in r["drivers"]],
        )
        for r in rows
    ]  # fmt: skip
    return out.UpcomingRisk(
        meta=meta, model_version=row.version, model_auc=row.metrics.get("auc"),
        base_rate=row.metrics.get("base_rate"), rows=result, note=None,
    )  # fmt: skip


@router.get("/no-show/upcoming-risk", response_model=out.UpcomingRisk)
async def upcoming_risk(ctx: Ctx, request: Request) -> out.UpcomingRisk:
    """Appointments in the next seven days with a no show score and the top reasons."""
    result = await cached(ctx, "risk", out.UpcomingRisk, lambda: _risk(ctx))
    await audit.record(
        ctx.db,
        AuditAction.ANALYTICS_RISK_VIEW,
        request=request,
        actor_id=ctx.user.id,
        actor_role=ctx.user.role.value,
        entity="analytics",
    )
    await ctx.db.commit()
    return result


@router.get("/chatbot/summary", response_model=out.ChatbotSummary)
async def chatbot_summary(ctx: Ctx) -> out.ChatbotSummary:
    flt.require(ctx.scope, flt.FRONT_DESK)
    return await cached(
        ctx, "chatbot", out.ChatbotSummary, lambda: ctx.service.chatbot(ctx.filters)
    )


@router.get("/revenue/by-weekday", response_model=out.WeekdayRevenue)
async def revenue_by_weekday(ctx: Ctx) -> out.WeekdayRevenue:
    flt.require(ctx.scope, flt.OWN_FINANCE)
    return await cached(
        ctx, "by_weekday", out.WeekdayRevenue, lambda: ctx.service.revenue_by_weekday(ctx.filters)
    )


@router.get("/revenue/service-trends", response_model=out.ServiceTrends)
async def service_trends(ctx: Ctx) -> out.ServiceTrends:
    """Every service with its revenue, visits and revenue per chair hour; the top ten with a series."""
    flt.require(ctx.scope, flt.OWN_FINANCE)
    return await cached(
        ctx, "service_trends", out.ServiceTrends, lambda: ctx.service.service_trends(ctx.filters)
    )


@router.get("/revenue/dentist-services", response_model=out.DentistServiceMatrix)
async def dentist_services(ctx: Ctx) -> out.DentistServiceMatrix:
    flt.require(ctx.scope, flt.FINANCE)
    return await cached(
        ctx,
        "dentist_services",
        out.DentistServiceMatrix,
        lambda: ctx.service.dentist_services(ctx.filters),
    )


@router.get("/dentists/leaderboard", response_model=out.Leaderboard)
async def leaderboard(ctx: Ctx) -> out.Leaderboard:
    flt.require(ctx.scope, flt.CLINIC)
    return await cached(
        ctx, "leaderboard", out.Leaderboard, lambda: ctx.service.leaderboard(ctx.filters)
    )


@router.get("/patients/demographics", response_model=out.Demographics)
async def demographics(ctx: Ctx) -> out.Demographics:
    """Age bands and where patients came from, for patients with a completed visit in the range."""
    flt.require(ctx.scope, flt.FRONT_DESK)
    return await cached(
        ctx,
        "demographics",
        out.Demographics,
        lambda: ctx.service.demographics(ctx.filters, ctx.cipher),
    )


@router.get("/patients/top", response_model=out.TopPatients)
async def top_patients(ctx: Ctx) -> out.TopPatients:
    """Patients by lifetime billed amount. Receptionists see initials only."""
    flt.require(ctx.scope, flt.FRONT_DESK)
    masked = ctx.scope.role is UserRole.RECEPTIONIST
    return await cached(
        ctx,
        "top_patients",
        out.TopPatients,
        lambda: ctx.service.top_patients(ctx.filters, mask=masked),
        extra=str(masked),
    )


@router.get("/appointments/channels", response_model=out.Channels)
async def channels(ctx: Ctx) -> out.Channels:
    return await cached(ctx, "channels", out.Channels, lambda: ctx.service.channels(ctx.filters))


# --- refresh and export -------------------------------------------------------------------------------------------------


@router.post("/refresh", response_model=out.RefreshResult)
async def refresh(
    request: Request, current: AdminUser, db: Session, redis: RedisDep
) -> out.RefreshResult:
    """Refresh the materialized views now instead of waiting for the nightly job."""
    result = await refresh_views(request.app.state.engine)
    await redis.incr(VERSION_KEY)  # stored responses were built from the old figures
    await audit.record(db, AuditAction.ANALYTICS_REFRESH, request=request, actor_id=current.id, actor_role=current.role.value, entity="analytics", metadata=result)  # fmt: skip
    await db.commit()
    return out.RefreshResult(**result)


def _flat(value: Any) -> Any:
    if isinstance(value, list):
        if (
            value
            and isinstance(value[0], dict)
            and "label" in value[0]
            and "contribution" in value[0]
        ):
            return "; ".join(f"{d['label']} ({d['contribution']:+.2f})" for d in value)
        return json.dumps(value, default=str)
    return value


def _rows(model: BaseModel, dataset: str) -> list[dict[str, Any]]:
    data = json.loads(model.model_dump_json())
    if dataset == "retention":
        rows = []
        for cohort in data["cohorts"]:
            base = {k: v for k, v in cohort.items() if k != "retention"}
            rows.append({**base, **{f"month_{i}": v for i, v in enumerate(cohort["retention"])}})
        return rows
    if dataset == "forecast":
        return [{"kind": "history", **p} for p in data["history"]] + [
            {"kind": "forecast", **p} for p in data["forecast"]
        ]
    if dataset == "by_payer":
        return [{"group": "payer_type", **r} for r in data["by_payer_type"]] + [
            {"group": "provider", **r} for r in data["by_provider"]
        ]
    if dataset == "chatbot":
        return [
            {k: v for k, v in data.items() if k not in ("meta", "providers", "days", "unanswered")}
        ]
    if dataset == "demographics":
        return [{"group": "age", **r} for r in data["age_bands"]] + [
            {"group": "source", **r} for r in data["sources"]
        ]
    if dataset == "service_trends":
        return [{k: v for k, v in row.items() if k != "series"} for row in data["rows"]]
    for key in ("points", "rows", "cells", "buckets"):
        if key in data:
            return [{k: _flat(v) for k, v in row.items()} for row in data[key]]
    if dataset == "summary":
        return [{k: v for k, v in kpi.items() if k != "sparkline"} for kpi in data["kpis"]]
    return []


def _safe(value: Any) -> Any:
    """Stop a spreadsheet from running a cell that starts like a formula."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return "" if value is None else value


@router.get("/export/csv")
async def export_csv(
    ctx: Ctx,
    request: Request,
    dataset: Literal[
        "summary",
        "revenue_trend",
        "by_service",
        "by_dentist",
        "by_payer",
        "status_trend",
        "heatmap",
        "lead_time",
        "new_returning",
        "retention",
        "ar_aging",
        "collection",
        "forecast",
        "risk",
        "chatbot",
        "by_weekday",
        "service_trends",
        "dentist_services",
        "leaderboard",
        "demographics",
        "top_patients",
        "channels",
    ],
) -> Response:
    """Any table view as CSV. The same filters and the same permissions as the screen."""
    handlers: dict[str, Callable[[], Awaitable[BaseModel]]] = {
        "summary": lambda: _summary(ctx),
        "revenue_trend": lambda: revenue_trend(ctx),
        "by_service": lambda: revenue_by_service(ctx),
        "by_dentist": lambda: revenue_by_dentist(ctx),
        "by_payer": lambda: revenue_by_payer(ctx),
        "status_trend": lambda: status_trend(ctx),
        "heatmap": lambda: heatmap(ctx),
        "lead_time": lambda: lead_time(ctx),
        "new_returning": lambda: new_vs_returning(ctx),
        "retention": lambda: retention_cohorts(ctx),
        "ar_aging": lambda: ar_aging(ctx),
        "collection": lambda: collection_rate(ctx),
        "forecast": lambda: forecast_endpoint(ctx),
        "risk": lambda: upcoming_risk(ctx, request),
        "chatbot": lambda: chatbot_summary(ctx),
        "by_weekday": lambda: revenue_by_weekday(ctx),
        "service_trends": lambda: service_trends(ctx),
        "dentist_services": lambda: dentist_services(ctx),
        "leaderboard": lambda: leaderboard(ctx),
        "demographics": lambda: demographics(ctx),
        "top_patients": lambda: top_patients(ctx),
        "channels": lambda: channels(ctx),
    }
    model = await handlers[dataset]()
    rows = _rows(model, dataset)
    buffer = io.StringIO()
    if rows:
        columns = list(rows[0])
        writer = csv.writer(buffer)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_safe(row.get(c)) for c in columns])
    await audit.record(ctx.db, AuditAction.EXPORT, request=request, actor_id=ctx.user.id, actor_role=ctx.user.role.value, entity="analytics", metadata={"dataset": dataset, "rows": len(rows)})  # fmt: skip
    await ctx.db.commit()
    filename = f"{dataset}-{ctx.filters.date_from}-{ctx.filters.date_to}.csv"
    return Response(
        buffer.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )  # fmt: skip
