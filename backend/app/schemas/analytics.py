import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

Granularity = Literal["day", "week", "month", "quarter"]
PayerFilter = Literal["patient", "insurer"]


class Out(BaseModel):
    """Responses are built by the server, so extra fields are a programming error."""

    model_config = ConfigDict(extra="forbid")


class Meta(Out):
    date_from: date
    date_to: date
    granularity: Granularity
    # When the materialized views were last refreshed. A dashboard shows a badge when stale.
    data_as_of: datetime | None
    cached: bool = False


# --- summary ----------------------------------------------------------------------------------------------


class SparkPoint(Out):
    period: date
    value: float | None


class Kpi(Out):
    key: str
    label: str
    unit: Literal["usd", "percent", "count", "days"]
    value: float | None
    previous: float | None
    change_percent: float | None
    # For a percentage KPI the change is a difference in points, not a relative change.
    change_kind: Literal["relative", "points"]
    higher_is_better: bool
    sparkline: list[SparkPoint]


class Summary(Out):
    meta: Meta
    previous_from: date
    previous_to: date
    kpis: list[Kpi]


# --- revenue -------------------------------------------------------------------------------------------------


class RevenuePoint(Out):
    period: date
    billed: Decimal
    collected: Decimal
    prior_year_billed: Decimal
    prior_year_collected: Decimal


class RevenueTrend(Out):
    meta: Meta
    points: list[RevenuePoint]


class RevenueRow(Out):
    key: str
    label: str
    billed: Decimal
    collected: Decimal
    invoices: int
    share_of_billed: float | None


class RevenueBreakdown(Out):
    meta: Meta
    rows: list[RevenueRow]


class ByPayer(Out):
    meta: Meta
    by_payer_type: list[RevenueRow]
    by_provider: list[RevenueRow]


# --- appointments ----------------------------------------------------------------------------------------------


class StatusPoint(Out):
    period: date
    total: int
    completed: int
    cancelled: int
    late_cancelled: int
    no_show: int
    open: int
    no_show_rate: float | None
    cancellation_rate: float | None


class StatusTrend(Out):
    meta: Meta
    points: list[StatusPoint]


class HeatCell(Out):
    weekday: int  # 0 = Monday
    hour: int
    appointments: int
    no_show: int
    no_show_rate: float | None


class Heatmap(Out):
    meta: Meta
    cells: list[HeatCell]
    max_appointments: int


class LeadBucket(Out):
    label: str
    appointments: int
    share: float | None


class LeadTime(Out):
    meta: Meta
    buckets: list[LeadBucket]
    average_days: float | None
    median_days: float | None
    appointments: int


# --- patients ---------------------------------------------------------------------------------------------------


class NewReturningPoint(Out):
    period: date
    new_patients: int
    returning_patients: int
    new_visits: int
    returning_visits: int


class NewVsReturning(Out):
    meta: Meta
    points: list[NewReturningPoint]
    new_patients: int
    returning_patients: int


class CohortRow(Out):
    cohort_month: date
    cohort_size: int
    # Share of the cohort with a completed visit in each month after the first, month 0 first.
    retention: list[float | None]
    returned_within_6_months: float | None


class RetentionCohorts(Out):
    meta: Meta
    cohorts: list[CohortRow]
    six_month_retention: float | None
    mature_cohorts: int


# --- finance ----------------------------------------------------------------------------------------------------------


class AgingBucket(Out):
    label: str
    invoices: int
    insurer: Decimal
    patient: Decimal
    total: Decimal


class ArAging(Out):
    meta: Meta
    as_of: date
    buckets: list[AgingBucket]
    total_outstanding: Decimal
    over_90_share: float | None


class CollectionPoint(Out):
    period: date
    billed: Decimal
    collected_to_date: Decimal
    rate: float | None


class CollectionRate(Out):
    meta: Meta
    points: list[CollectionPoint]
    overall_rate: float | None
    # Days from issuing an invoice to its last payment, for invoices in the range that are paid.
    average_days_to_collect: float | None = None


# --- forecast ------------------------------------------------------------------------------------------------------------


class ForecastPoint(Out):
    month: date
    value: float
    lower: float | None = None
    upper: float | None = None


class RevenueForecast(Out):
    meta: Meta
    method: Literal["holt_winters", "seasonal_naive", "naive"]
    method_note: str
    interval_level: float
    history: list[ForecastPoint]
    forecast: list[ForecastPoint]


# --- no show -------------------------------------------------------------------------------------------------------------


class RiskDriver(Out):
    feature: str
    label: str
    contribution: float


class RiskRow(Out):
    appointment_id: uuid.UUID
    start: datetime
    patient_name: str
    service_name: str
    dentist_id: uuid.UUID
    dentist_name: str
    status: str
    score: float
    level: Literal["high", "medium", "low"]
    drivers: list[RiskDriver]


class UpcomingRisk(Out):
    meta: Meta
    model_version: str | None
    model_auc: float | None
    base_rate: float | None
    rows: list[RiskRow]
    note: str | None


# --- chatbot -----------------------------------------------------------------------------------------------------------------


class ProviderTokens(Out):
    provider: str
    calls: int
    tokens: int
    failovers: int


class ChatDay(Out):
    day: date
    conversations: int
    turns: int
    zero_llm_turns: int
    tokens: int


class Unanswered(Out):
    question: str
    count: int


class ChatbotSummary(Out):
    meta: Meta
    conversations: int
    turns: int
    zero_llm_turns: int
    zero_llm_share: float | None
    resolved_without_human: float | None
    booking_started: int
    booking_slot_chosen: int
    booking_confirmed: int
    booking_conversion: float | None
    handoffs: int
    providers: list[ProviderTokens]
    failovers: int
    feedback_up: int
    feedback_down: int
    feedback_score: float | None
    tokens_per_conversation: float | None
    days: list[ChatDay] = []
    # Questions that ended in a hand over or a thumbs down, most frequent first, personal
    # details hidden.
    unanswered: list[Unanswered] = []


class RefreshResult(Out):
    refreshed: int
    failed: int


# --- dashboard additions ---------------------------------------------------------------------------------------


class WeekdayRow(Out):
    weekday: int  # 0 = Monday
    billed: Decimal
    collected: Decimal
    invoices: int
    days: int  # how many of this weekday fall in the range


class WeekdayRevenue(Out):
    meta: Meta
    rows: list[WeekdayRow]


class SeriesPoint(Out):
    period: date
    value: float


class ServiceRow(Out):
    key: str
    label: str
    category: str
    billed: Decimal
    collected: Decimal
    invoices: int
    visits: int
    minutes: int
    revenue_per_hour: float | None
    series: list[SeriesPoint]  # filled for the top services only


class ServiceTrends(Out):
    meta: Meta
    rows: list[ServiceRow]


class DentistServiceCell(Out):
    dentist_id: str
    dentist: str
    service_id: str
    service: str
    billed: Decimal


class DentistServiceMatrix(Out):
    meta: Meta
    cells: list[DentistServiceCell]


class LeaderRow(Out):
    dentist_id: str
    dentist: str
    billed: Decimal
    collected: Decimal
    visits: int
    no_shows: int
    no_show_rate: float | None
    booked_hours: float
    available_hours: float
    utilization: float | None
    revenue_per_visit: float | None


class Leaderboard(Out):
    meta: Meta
    rows: list[LeaderRow]


class Slice(Out):
    key: str
    label: str
    patients: int
    share: float | None


class Demographics(Out):
    meta: Meta
    patients: int
    age_bands: list[Slice]
    sources: list[Slice]


class TopPatient(Out):
    patient_id: uuid.UUID
    name: str
    lifetime_value: Decimal
    visits: int
    last_visit: date | None
    masked: bool


class TopPatients(Out):
    meta: Meta
    rows: list[TopPatient]


class ChannelRow(Out):
    key: str
    label: str
    appointments: int
    completed: int
    share: float | None


class Channels(Out):
    meta: Meta
    rows: list[ChannelRow]


class ReminderResult(Out):
    message: str
