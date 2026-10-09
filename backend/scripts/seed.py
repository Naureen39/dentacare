"""Load the synthetic clinic dataset into PostgreSQL.

    python -m scripts.seed                 # seed an empty database
    python -m scripts.seed --reset         # remove the clinic data first, then seed again
    python -m scripts.seed --csv           # also write CSV copies to data/generated/

Running it twice never duplicates data: a marker row records that the dataset is loaded, and
a second run without ``--reset`` stops there. Demo accounts get random passwords that are
printed once, because they are not stored anywhere else. Use them in development only.
"""

import argparse
import asyncio
import csv
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analytics.refresh import refresh_views
from app.core.config import Settings, get_settings
from app.core.crypto import FieldCipher
from app.core.security import PasswordService
from app.db.enums import UserRole
from app.db.models import (
    Appointment,
    AppointmentStatusHistory,
    AppSetting,
    Dentist,
    DentistSchedule,
    DentistService,
    InsuranceProvider,
    Invoice,
    InvoiceItem,
    Patient,
    Payment,
    ScheduleException,
    Service,
    Testimonial,
    User,
)
from app.db.session import create_engine, create_session_factory
from scripts.generate_data import DATASET_VERSION, Dataset, GenConfig, generate, summarize

MARKER_KEY = "seed_dataset"
CHUNK = 1000
DEMO_DOMAIN = "@meridian.test"
CSV_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"

# Children first, so foreign keys never block the delete.
CLEAR_ORDER = [
    "llm_usage", "chat_messages", "chat_sessions", "payments", "invoice_items", "invoices",
    "appointment_action_tokens", "reminders", "appointment_risk", "appointment_status_history",
    "appointments", "dentist_services", "dentist_schedules", "schedule_exceptions", "patients",
    "dentists", "services", "insurance_providers", "testimonials",
]  # fmt: skip

TESTIMONIALS = [
    ("Rachel", "M", "Routine Exam and Cleaning", 5, "The whole visit felt calm and unhurried. The hygienist explained everything she was doing."),
    ("Omar", "K", "Porcelain Crown", 5, "My crown was ready in two short visits and fits perfectly. The team kept me informed at every step."),
    ("Elena", "S", "Clear Aligner Treatment", 5, "Straightforward planning and honest advice about how long treatment would take."),
    ("James", "T", "Root Canal Therapy", 4, "I was nervous, but the procedure was far more comfortable than I expected."),
    ("Priya", "N", "Emergency Visit", 5, "They found a place for me the same morning when I broke a tooth. I am grateful."),
    ("Daniel", "L", "Professional Teeth Whitening", 5, "A noticeable difference in one hour, and no sensitivity afterwards."),
]  # fmt: skip


def _chunks(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [rows[i : i + CHUNK] for i in range(0, len(rows), CHUNK)]


async def _bulk(db: AsyncSession, model: Any, rows: list[dict[str, Any]]) -> None:
    for chunk in _chunks(rows):
        await db.execute(insert(model), chunk)


async def clear(db: AsyncSession) -> None:
    for table in CLEAR_ORDER:
        await db.execute(text(f"DELETE FROM {table}"))  # noqa: S608
    demo = select(User.id).where(User.email.like(f"%{DEMO_DOMAIN}"))
    for table in ("refresh_tokens", "auth_tokens", "mfa_recovery_codes"):
        await db.execute(
            text(
                f"DELETE FROM {table} WHERE user_id IN (SELECT id FROM users WHERE email LIKE :p)"  # noqa: S608
            ),
            {"p": f"%{DEMO_DOMAIN}"},
        )  # noqa: S608
    await db.execute(delete(User).where(User.id.in_(demo)))
    await db.execute(delete(AppSetting).where(AppSetting.key == MARKER_KEY))
    await db.commit()


def _rows(data: Dataset) -> dict[str, list[dict[str, Any]]]:
    appointments = []
    for row in data.appointments:
        start, end = row["slot"]
        appointments.append({**row, "slot": Range(start, end, bounds="[)")})
    return {"appointments": appointments}


async def load(db: AsyncSession, data: Dataset) -> None:
    await _bulk(db, InsuranceProvider, data.insurance_providers)
    await _bulk(db, Service, data.services)
    await _bulk(db, Dentist, data.dentists)
    await _bulk(db, DentistService, data.dentist_services)
    await _bulk(db, DentistSchedule, data.dentist_schedules)
    await _bulk(db, ScheduleException, data.schedule_exceptions)
    await _bulk(db, Patient, data.patients)
    await db.commit()
    await _bulk(db, Appointment, _rows(data)["appointments"])
    await db.commit()
    await _bulk(db, AppointmentStatusHistory, data.status_history)
    await db.commit()
    await _bulk(db, Invoice, data.invoices)
    await _bulk(db, InvoiceItem, data.invoice_items)
    await _bulk(db, Payment, data.payments)
    await db.commit()
    await db.execute(
        insert(Testimonial),
        [
            {"first_name": first, "last_initial": initial, "treatment": treatment, "rating": rating,
             "body": body, "is_published": True}
            for first, initial, treatment, rating, body in TESTIMONIALS
        ],
    )  # fmt: skip
    await db.commit()


async def demo_accounts(
    db: AsyncSession, settings: Settings, passwords: PasswordService
) -> dict[str, str]:
    """Four development accounts with random passwords, returned so they can be printed once."""
    out: dict[str, str] = {}
    roles = [
        ("admin", UserRole.ADMIN), ("reception", UserRole.RECEPTIONIST),
        ("dentist", UserRole.DENTIST), ("patient", UserRole.PATIENT),
    ]  # fmt: skip
    now = datetime.now(UTC)
    for local, role in roles:
        password = secrets.token_urlsafe(14)
        email = f"{local}{DEMO_DOMAIN}"
        user = User(
            email=email, password_hash=passwords.hash(password), role=role,
            email_verified_at=now, password_changed_at=now,
        )  # fmt: skip
        db.add(user)
        await db.flush()
        out[email] = password
        if role is UserRole.DENTIST:
            dentist = (
                (await db.execute(select(Dentist).order_by(Dentist.full_name))).scalars().first()
            )
            if dentist is not None:
                dentist.user_id = user.id
        if role is UserRole.PATIENT:
            busiest = (
                await db.execute(
                    select(Appointment.patient_id)
                    .group_by(Appointment.patient_id)
                    .order_by(func.count().desc(), Appointment.patient_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            patient = await db.get(Patient, busiest) if busiest else None
            if patient is not None:
                patient.user_id = user.id
                patient.email = email
    await db.commit()
    return out


def write_csv(data: Dataset, directory: Path) -> list[Path]:
    """Copies for review. Encrypted columns are left out, nothing here is personal data."""
    directory.mkdir(parents=True, exist_ok=True)
    skip = {"dob_enc", "phone_enc", "address_enc", "insurance_member_id_enc"}
    tables: dict[str, list[dict[str, Any]]] = {
        "patients": data.patients, "appointments": data.appointments,
        "invoices": data.invoices, "payments": data.payments, "services": data.services,
        "dentists": data.dentists,
    }  # fmt: skip
    written = []
    for name, rows in tables.items():
        if not rows:
            continue
        columns = [c for c in rows[0] if c not in skip]
        path = directory / f"{name}.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([_cell(row[c]) for c in columns])
        written.append(path)
    return written


def _cell(value: Any) -> Any:
    if isinstance(value, tuple):
        return f"[{value[0].isoformat()},{value[1].isoformat()})"
    if isinstance(value, datetime):
        return value.isoformat()
    return "" if value is None else value


async def seed(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: datetime | None = None,
    reset: bool = False,
    patients: int = 4500,
    demo: bool = True,
    seed_value: int = 20260101,
    csv_dir: Path | None = None,
    engine: Any = None,
) -> dict[str, Any]:
    """Seed the database. Returns a report; ``skipped`` is set when nothing was done."""
    async with factory() as db:
        marker = (
            await db.execute(select(AppSetting.value).where(AppSetting.key == MARKER_KEY))
        ).scalar_one_or_none()
        if marker is not None and not reset:
            return {"skipped": "already seeded", "marker": marker}
        if reset:
            await clear(db)
        elif (await db.execute(select(func.count()).select_from(Service))).scalar_one():
            raise SystemExit("The database already has clinic data. Use --reset to replace it.")

        cipher = FieldCipher.from_settings(
            settings.field_encryption_key, settings.field_encryption_old_keys, settings.jwt_secret
        )
        config = GenConfig(
            now=now or datetime.now(UTC), seed=seed_value, patients=patients,
            clinic_tz=settings.clinic_tz,
        )  # fmt: skip
        data = generate(config, cipher.encrypt)
        await load(db, data)
        accounts = await demo_accounts(db, settings, PasswordService(settings)) if demo else {}
        report = summarize(data)
        statement = pg_insert(AppSetting).values(
            key=MARKER_KEY,
            value={"version": DATASET_VERSION, "seed": seed_value, "patients": patients,
                   "end_date": config.end_date.isoformat(), "appointments": report["appointments"]},
        )  # fmt: skip
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[AppSetting.key], set_={"value": statement.excluded.value}
            )
        )
        await db.commit()
    if csv_dir is not None:
        write_csv(data, csv_dir)
    if engine is not None:
        await refresh_views(engine, concurrently=False)
    report["accounts"] = accounts
    return report


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--reset", action="store_true", help="remove existing clinic data first")
    parser.add_argument("--csv", action="store_true", help="write CSV copies to data/generated/")
    parser.add_argument("--patients", type=int, default=4500)
    parser.add_argument("--seed", type=int, default=20260101)
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = create_engine(settings)
    try:
        report = await seed(
            create_session_factory(engine), settings, reset=args.reset, patients=args.patients,
            seed_value=args.seed, csv_dir=CSV_DIR if args.csv else None, engine=engine,
        )  # fmt: skip
    finally:
        await engine.dispose()
    if "skipped" in report:
        print(f"Nothing to do: {report['skipped']}. Use --reset to load it again.")
        return 0
    accounts = report.pop("accounts")
    monthly = report.pop("monthly_completed")
    report.pop("mix")
    print("Seeded the demo dataset:")
    for key, value in report.items():
        print(f"  {key}: {value}")
    print(f"  months with completed visits: {len(monthly)}")
    if accounts:
        print("\nDevelopment accounts (shown once, change them before any real use):")
        for email, password in accounts.items():
            print(f"  {email}  {password}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
