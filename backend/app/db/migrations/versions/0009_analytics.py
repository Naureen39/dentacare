"""analytics

Materialized views for the analytics endpoints, the model registry, and the stored no show
scores. Calendar days in the views follow the clinic's own time zone, taken from CLINIC_TZ at
the time the migration runs. Changing the time zone later means recreating the views.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-11
"""

import os
from collections.abc import Sequence
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = str(ZoneInfo(os.environ.get("CLINIC_TZ", "America/New_York")))

# Appointments that occupy the schedule: the same statuses the double booking constraint guards.
OCCUPYING = "('booked', 'confirmed', 'checked_in', 'completed')"

VIEWS: list[tuple[str, str, str]] = [
    # (name, select statement, unique index columns)
    (
        "mv_daily_revenue",
        f"""
        WITH inv AS (
            SELECT i.id, clinic_date(i.issued_at) AS day, a.dentist_id, a.service_id,
                   i.total, LEAST(i.insurance_expected, i.total) AS insurer_part
            FROM invoices i JOIN appointments a ON a.id = i.appointment_id
            WHERE i.status NOT IN ('draft', 'void')
        ),
        paid AS (
            SELECT invoice_id, payer_type, sum(amount) AS amount FROM payments GROUP BY 1, 2
        )
        SELECT day, dentist_id, service_id, payer_type,
               sum(billed)::numeric(14,2) AS billed,
               sum(collected)::numeric(14,2) AS collected,
               sum(cohort_collected)::numeric(14,2) AS cohort_collected,
               sum(invoices)::int AS invoices
        FROM (
            SELECT inv.day, inv.dentist_id, inv.service_id, 'insurer'::payer_type AS payer_type,
                   inv.insurer_part AS billed, 0::numeric AS collected,
                   COALESCE(pi.amount, 0) AS cohort_collected, 1 AS invoices
            FROM inv LEFT JOIN paid pi ON pi.invoice_id = inv.id AND pi.payer_type = 'insurer'
            UNION ALL
            SELECT inv.day, inv.dentist_id, inv.service_id, 'patient'::payer_type,
                   inv.total - inv.insurer_part, 0::numeric,
                   COALESCE(pp.amount, 0), 0
            FROM inv LEFT JOIN paid pp ON pp.invoice_id = inv.id AND pp.payer_type = 'patient'
            UNION ALL
            SELECT clinic_date(p.paid_at), a.dentist_id, a.service_id, p.payer_type,
                   0::numeric, p.amount, 0::numeric, 0
            FROM payments p
            JOIN invoices i ON i.id = p.invoice_id
            JOIN appointments a ON a.id = i.appointment_id
        ) x
        GROUP BY day, dentist_id, service_id, payer_type
        """,
        "day, dentist_id, service_id, payer_type",
    ),
    (
        "mv_monthly_revenue",
        """
        SELECT date_trunc('month', day)::date AS month, dentist_id, service_id, payer_type,
               sum(billed)::numeric(14,2) AS billed,
               sum(collected)::numeric(14,2) AS collected,
               sum(cohort_collected)::numeric(14,2) AS cohort_collected,
               sum(invoices)::int AS invoices
        FROM mv_daily_revenue
        GROUP BY 1, 2, 3, 4
        """,
        "month, dentist_id, service_id, payer_type",
    ),
    (
        "mv_service_mix",
        f"""
        SELECT clinic_date(lower(slot)) AS day, dentist_id, service_id,
               count(*) FILTER (WHERE status = 'completed')::int AS completed,
               count(*) FILTER (WHERE status <> 'cancelled')::int AS scheduled,
               COALESCE(sum(EXTRACT(epoch FROM upper(slot) - lower(slot)) / 60)
                        FILTER (WHERE status = 'completed'), 0)::int AS minutes
        FROM appointments
        GROUP BY 1, 2, 3
        """,
        "day, dentist_id, service_id",
    ),
    (
        "mv_dentist_performance",
        f"""
        SELECT clinic_date(lower(slot)) AS day, dentist_id, service_id,
               count(*)::int AS total,
               count(*) FILTER (WHERE status = 'completed')::int AS completed,
               count(*) FILTER (WHERE status = 'cancelled')::int AS cancelled,
               count(*) FILTER (WHERE status = 'no_show')::int AS no_show,
               count(*) FILTER (WHERE status = 'cancelled' AND late_cancel)::int AS late_cancel,
               count(*) FILTER (WHERE status IN ('booked', 'confirmed', 'checked_in'))::int AS open,
               COALESCE(sum(EXTRACT(epoch FROM upper(slot) - lower(slot)) / 60)
                        FILTER (WHERE status IN {OCCUPYING}), 0)::int AS booked_minutes
        FROM appointments
        GROUP BY 1, 2, 3
        """,
        "day, dentist_id, service_id",
    ),
    (
        "mv_utilization_daily",
        f"""
        WITH bounds AS (
            SELECT LEAST(min(clinic_date(lower(slot))), clinic_date(now())) AS first_day,
                   GREATEST(max(clinic_date(lower(slot))), clinic_date(now())) AS last_day
            FROM appointments
        ),
        days AS (
            SELECT d::date AS day
            FROM bounds, generate_series(bounds.first_day, bounds.last_day, interval '1 day') AS d
        ),
        windows AS (
            SELECT d.day, s.dentist_id,
                   CASE WHEN s.break_start IS NOT NULL AND s.break_end IS NOT NULL THEN
                       tstzmultirange(
                           tstzrange((d.day + s.start_time) AT TIME ZONE '{TZ}',
                                     (d.day + s.break_start) AT TIME ZONE '{TZ}'),
                           tstzrange((d.day + s.break_end) AT TIME ZONE '{TZ}',
                                     (d.day + s.end_time) AT TIME ZONE '{TZ}'))
                   ELSE tstzmultirange(
                           tstzrange((d.day + s.start_time) AT TIME ZONE '{TZ}',
                                     (d.day + s.end_time) AT TIME ZONE '{TZ}'))
                   END AS open_hours
            FROM days d
            JOIN dentist_schedules s ON s.weekday = EXTRACT(isodow FROM d.day)::int - 1
            JOIN dentists dn ON dn.id = s.dentist_id AND d.day >= clinic_date(dn.created_at)
        ),
        free AS (
            SELECT w.day, w.dentist_id,
                   w.open_hours - COALESCE((
                       SELECT range_agg(tstzrange(e.starts_at, e.ends_at))
                       FROM schedule_exceptions e
                       WHERE e.dentist_id = w.dentist_id
                         AND tstzrange(e.starts_at, e.ends_at)
                             && tstzrange(lower(w.open_hours), upper(w.open_hours))
                   ), '{{}}'::tstzmultirange) AS hours
            FROM windows w
        ),
        available AS (
            SELECT f.day, f.dentist_id,
                   COALESCE(sum(EXTRACT(epoch FROM upper(r) - lower(r)) / 60), 0) AS minutes
            FROM free f LEFT JOIN LATERAL unnest(f.hours) AS r ON true
            GROUP BY 1, 2
        ),
        booked AS (
            SELECT clinic_date(lower(slot)) AS day, dentist_id,
                   sum(EXTRACT(epoch FROM upper(slot) - lower(slot)) / 60) AS minutes
            FROM appointments WHERE status IN {OCCUPYING}
            GROUP BY 1, 2
        )
        SELECT COALESCE(a.day, b.day) AS day,
               COALESCE(a.dentist_id, b.dentist_id) AS dentist_id,
               COALESCE(a.minutes, 0)::int AS available_minutes,
               COALESCE(b.minutes, 0)::int AS booked_minutes
        FROM available a
        FULL JOIN booked b ON b.day = a.day AND b.dentist_id = a.dentist_id
        """,
        "day, dentist_id",
    ),
    (
        "mv_hourly_heatmap",
        f"""
        SELECT clinic_date(lower(slot)) AS day,
               EXTRACT(hour FROM lower(slot) AT TIME ZONE '{TZ}')::int AS hour,
               dentist_id,
               count(*) FILTER (WHERE status <> 'cancelled')::int AS appointments,
               count(*) FILTER (WHERE status = 'completed')::int AS completed,
               count(*) FILTER (WHERE status = 'no_show')::int AS no_show
        FROM appointments
        GROUP BY 1, 2, 3
        """,
        "day, hour, dentist_id",
    ),
    (
        "mv_payer_mix",
        """
        WITH paid AS (SELECT invoice_id, sum(amount) AS amount FROM payments GROUP BY 1)
        SELECT clinic_date(i.issued_at) AS day,
               CASE WHEN p.insurance_provider_id IS NULL THEN 'self_pay' ELSE 'insurance' END
                   AS payer_class,
               COALESCE(p.insurance_provider_id::text, 'self_pay') AS provider_key,
               p.insurance_provider_id,
               count(*)::int AS invoices,
               sum(i.total)::numeric(14,2) AS billed,
               sum(LEAST(i.insurance_expected, i.total))::numeric(14,2) AS insurer_expected,
               sum(COALESCE(paid.amount, 0))::numeric(14,2) AS collected_to_date
        FROM invoices i
        JOIN patients p ON p.id = i.patient_id
        LEFT JOIN paid ON paid.invoice_id = i.id
        WHERE i.status NOT IN ('draft', 'void')
        GROUP BY 1, 2, 3, 4
        """,
        "day, payer_class, provider_key",
    ),
    (
        "mv_ar_aging",
        """
        WITH paid AS (
            SELECT invoice_id,
                   sum(amount) FILTER (WHERE payer_type = 'insurer') AS insurer_paid,
                   sum(amount) FILTER (WHERE payer_type = 'patient') AS patient_paid
            FROM payments GROUP BY 1
        )
        SELECT i.id AS invoice_id, i.patient_id, a.dentist_id,
               clinic_date(i.issued_at) AS issued_day, i.total,
               GREATEST(LEAST(i.insurance_expected, i.total) - COALESCE(paid.insurer_paid, 0), 0)
                   ::numeric(14,2) AS insurer_balance,
               GREATEST(i.total - LEAST(i.insurance_expected, i.total)
                        - COALESCE(paid.patient_paid, 0), 0)::numeric(14,2) AS patient_balance
        FROM invoices i
        JOIN appointments a ON a.id = i.appointment_id
        LEFT JOIN paid ON paid.invoice_id = i.id
        WHERE i.status IN ('issued', 'partially_paid')
          AND i.total > COALESCE(paid.insurer_paid, 0) + COALESCE(paid.patient_paid, 0)
        """,
        "invoice_id",
    ),
    (
        "mv_cohort_retention",
        """
        WITH visits AS (
            SELECT patient_id, clinic_date(lower(slot)) AS vday,
                   date_trunc('month', clinic_date(lower(slot)))::date AS vmonth
            FROM appointments WHERE status = 'completed'
        ),
        -- Only patients registered after the data begins have a known first visit. Patients who
        -- were already in the practice would otherwise all appear as one early cohort.
        first_visit AS (
            SELECT v.patient_id, min(v.vday) AS first_day,
                   date_trunc('month', min(v.vday))::date AS cohort_month
            FROM visits v JOIN patients p ON p.id = v.patient_id
            WHERE p.created_at >= (SELECT min(lower(slot)) FROM appointments)
            GROUP BY 1
        ),
        returned AS (
            SELECT f.patient_id, f.cohort_month,
                   bool_or(v.vday > f.first_day AND v.vday <= f.first_day + 210) AS returned_6m
            FROM first_visit f JOIN visits v ON v.patient_id = f.patient_id
            GROUP BY 1, 2
        ),
        sizes AS (
            SELECT cohort_month, count(*)::int AS cohort_size,
                   count(*) FILTER (WHERE returned_6m)::int AS returned_6m
            FROM returned GROUP BY 1
        ),
        active AS (
            SELECT f.cohort_month,
                   ((EXTRACT(year FROM v.vmonth) - EXTRACT(year FROM f.cohort_month)) * 12
                    + EXTRACT(month FROM v.vmonth) - EXTRACT(month FROM f.cohort_month))::int
                       AS month_offset,
                   count(DISTINCT v.patient_id)::int AS active_patients
            FROM first_visit f JOIN visits v ON v.patient_id = f.patient_id
            GROUP BY 1, 2
        )
        SELECT a.cohort_month, a.month_offset, a.active_patients, s.cohort_size, s.returned_6m
        FROM active a JOIN sizes s USING (cohort_month)
        """,
        "cohort_month, month_offset",
    ),
    (
        "mv_chatbot_daily",
        """
        WITH msg AS (
            SELECT session_id,
                   count(*) FILTER (WHERE role = 'user') AS user_turns,
                   count(*) FILTER (WHERE role = 'assistant'
                                    AND COALESCE(intent, '') <> 'session_open') AS turns,
                   count(*) FILTER (WHERE role = 'assistant'
                                    AND COALESCE(intent, '') <> 'session_open'
                                    AND llm_calls = 0) AS zero_llm_turns,
                   COALESCE(sum(llm_calls), 0) AS llm_calls,
                   COALESCE(bool_or(route = 'handoff'), false) AS handoff,
                   count(*) FILTER (WHERE feedback = 1) AS feedback_up,
                   count(*) FILTER (WHERE feedback = -1) AS feedback_down
            FROM chat_messages GROUP BY 1
        ),
        sess AS (
            SELECT s.id, clinic_date(s.created_at) AS day,
                   COALESCE((s.state #>> '{funnel,started}')::boolean, false) AS started,
                   COALESCE((s.state #>> '{funnel,slot_chosen}')::boolean, false) AS slot_chosen,
                   COALESCE((s.state #>> '{funnel,confirmed}')::boolean, false) AS confirmed
            FROM chat_sessions s
        )
        SELECT s.day,
               count(*)::int AS sessions,
               count(*) FILTER (WHERE COALESCE(m.user_turns, 0) > 0)::int AS conversations,
               COALESCE(sum(m.turns), 0)::int AS turns,
               COALESCE(sum(m.zero_llm_turns), 0)::int AS zero_llm_turns,
               COALESCE(sum(m.llm_calls), 0)::int AS llm_calls,
               count(*) FILTER (WHERE s.started)::int AS booking_started,
               count(*) FILTER (WHERE s.slot_chosen)::int AS booking_slot_chosen,
               count(*) FILTER (WHERE s.confirmed)::int AS booking_confirmed,
               count(*) FILTER (WHERE m.handoff)::int AS handoffs,
               COALESCE(sum(m.feedback_up), 0)::int AS feedback_up,
               COALESCE(sum(m.feedback_down), 0)::int AS feedback_down,
               COALESCE((
                   SELECT jsonb_object_agg(p.provider, jsonb_build_object(
                              'calls', p.calls, 'tokens', p.tokens, 'failovers', p.failovers))
                   FROM (
                       SELECT u.provider, count(*) AS calls,
                              sum(u.prompt_tokens + u.completion_tokens) AS tokens,
                              count(*) FILTER (WHERE u.status = 'ok'
                                               AND u.fallback_from IS NOT NULL) AS failovers
                       FROM llm_usage u JOIN sess s2 ON s2.id = u.session_id
                       WHERE s2.day = s.day GROUP BY u.provider
                   ) p
               ), '{}'::jsonb) AS provider_usage
        FROM sess s LEFT JOIN msg m ON m.session_id = s.id
        GROUP BY s.day
        """,
        "day",
    ),
]


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("algorithm", sa.String(60), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.Column("train_rows", sa.Integer(), nullable=False),
        sa.Column("test_rows", sa.Integer(), nullable=False),
        sa.Column("data_through", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_registry")),
        sa.UniqueConstraint("name", "version", name="uq_model_registry_name_version"),
    )
    op.create_index(
        "uq_model_registry_active",
        "model_registry",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "appointment_risk",
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("drivers", postgresql.JSONB(), nullable=False),
        sa.Column("model_version", sa.String(40), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("fk_appointment_risk_appointment_id_appointments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("appointment_id", name=op.f("pk_appointment_risk")),
    )

    op.execute(
        f"""
        CREATE FUNCTION clinic_date(moment timestamptz) RETURNS date
        LANGUAGE sql IMMUTABLE PARALLEL SAFE
        AS $$ SELECT (moment AT TIME ZONE '{TZ}')::date $$
        """
    )
    for name, select, columns in VIEWS:
        op.execute(f"CREATE MATERIALIZED VIEW {name} AS {select} WITH DATA")
        op.execute(f"CREATE UNIQUE INDEX uq_{name} ON {name} ({columns})")
    op.execute("CREATE INDEX ix_mv_daily_revenue_day ON mv_daily_revenue (day)")
    op.execute("CREATE INDEX ix_mv_monthly_revenue_month ON mv_monthly_revenue (month)")
    op.execute("CREATE INDEX ix_mv_dentist_performance_day ON mv_dentist_performance (day)")
    op.execute("CREATE INDEX ix_mv_utilization_daily_day ON mv_utilization_daily (day)")
    op.execute("CREATE INDEX ix_mv_hourly_heatmap_day ON mv_hourly_heatmap (day)")
    op.execute("CREATE INDEX ix_mv_service_mix_day ON mv_service_mix (day)")


def downgrade() -> None:
    for name, _, _ in reversed(VIEWS):
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name}")
    op.execute("DROP FUNCTION IF EXISTS clinic_date(timestamptz)")
    op.drop_table("appointment_risk")
    op.drop_index("uq_model_registry_active", table_name="model_registry")
    op.drop_table("model_registry")
