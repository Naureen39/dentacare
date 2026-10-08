from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import AppointmentChannel, AppointmentStatus, ChatRole
from app.db.models import Appointment, ChatMessage, ChatSession, Dentist, Patient, Service
from app.services.retention import (
    anonymize_cancelled_guests,
    purge_chat_messages,
    run_retention,
)
from tests.auth.conftest import Ctx

NOW = datetime(2027, 6, 1, 12, 0, tzinfo=UTC)


async def test_chat_messages_older_than_the_retention_period_are_purged(ctx: Ctx) -> None:
    async with ctx.session_factory() as db:
        old, recent, empty = ChatSession(), ChatSession(), ChatSession()
        db.add_all([old, recent, empty])
        await db.flush()
        db.add_all(
            [
                ChatMessage(
                    session_id=old.id,
                    role=ChatRole.USER,
                    content="old",
                    created_at=NOW - timedelta(days=91),
                ),
                ChatMessage(
                    session_id=old.id,
                    role=ChatRole.ASSISTANT,
                    content="old2",
                    created_at=NOW - timedelta(days=120),
                ),
                ChatMessage(
                    session_id=recent.id,
                    role=ChatRole.USER,
                    content="new",
                    created_at=NOW - timedelta(days=89),
                ),
            ]
        )
        empty.created_at = NOW - timedelta(days=200)
        old.created_at = NOW - timedelta(days=120)
        await db.commit()

        purged = await purge_chat_messages(db, 90, now=NOW)
        await db.commit()

        assert purged == 2
        remaining = (await db.execute(select(ChatMessage.content))).scalars().all()
        assert remaining == ["new"]
        sessions = (await db.execute(select(ChatSession.id))).scalars().all()
        assert set(sessions) == {recent.id}  # emptied and stale sessions are removed too


async def _guest_with_appointments(
    db: AsyncSession, ctx: Ctx, name: str, statuses: list[AppointmentStatus], days_ago: int
) -> Patient:
    patient = Patient(
        first_name=name,
        last_name="Visitor",
        email=f"{name.lower()}@example.com",
        phone_enc="dev:cipher",
        dob_enc="dev:cipher",
        address_enc="dev:cipher",
        marketing_consent=True,
    )
    db.add(patient)
    dentist = (await db.execute(select(Dentist).limit(1))).scalar_one_or_none()
    if dentist is None:
        dentist = Dentist(full_name="Dr. Retention", specialty="general")
        db.add(dentist)
    service = (await db.execute(select(Service).limit(1))).scalar_one_or_none()
    if service is None:
        from decimal import Decimal

        service = Service(
            code="RET1",
            name="Exam",
            category="preventive",
            duration_min=30,
            base_price=Decimal("50.00"),
        )
        db.add(service)
    await db.flush()
    for index, status in enumerate(statuses):
        start = NOW - timedelta(days=days_ago, hours=index * 2)
        db.add(
            Appointment(
                patient_id=patient.id,
                dentist_id=dentist.id,
                service_id=service.id,
                slot=Range(start, start + timedelta(minutes=30), bounds="[)"),
                status=status,
                channel=AppointmentChannel.WEB,
            )
        )
    await db.flush()
    return patient


async def test_stale_cancelled_guests_are_anonymized_and_others_are_kept(ctx: Ctx) -> None:
    async with ctx.session_factory() as db:
        stale = await _guest_with_appointments(db, ctx, "Stale", [AppointmentStatus.CANCELLED], 400)
        recent = await _guest_with_appointments(
            db, ctx, "Recent", [AppointmentStatus.CANCELLED], 100
        )
        visited = await _guest_with_appointments(
            db, ctx, "Visited", [AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED], 400
        )
        account = await ctx.create_user("holder@example.com")
        await db.commit()

        count = await anonymize_cancelled_guests(db, 12, now=NOW)
        await db.commit()

        assert count == 1
        rows = {p.id: p for p in (await db.execute(select(Patient))).scalars().all()}
        gone = rows[stale.id]
        assert (gone.first_name, gone.last_name) == ("Anonymized", "Guest")
        assert gone.email is None and gone.phone_enc is None and gone.dob_enc is None
        assert gone.address_enc is None and gone.marketing_consent is False
        assert gone.anonymized_at is not None
        assert rows[recent.id].first_name == "Recent"
        assert rows[visited.id].first_name == "Visited"
        registered = [p for p in rows.values() if p.user_id == account.id]
        assert registered and registered[0].anonymized_at is None


async def test_anonymization_is_idempotent_and_keeps_the_appointments(ctx: Ctx) -> None:
    async with ctx.session_factory() as db:
        await _guest_with_appointments(db, ctx, "Once", [AppointmentStatus.CANCELLED], 500)
        await db.commit()
        assert await anonymize_cancelled_guests(db, 12, now=NOW) == 1
        assert await anonymize_cancelled_guests(db, 12, now=NOW) == 0
        assert len((await db.execute(select(Appointment))).scalars().all()) == 1


async def test_registered_patients_with_only_cancelled_visits_are_never_anonymized(
    ctx: Ctx,
) -> None:
    user = await ctx.create_user("member@example.com")
    async with ctx.session_factory() as db:
        patient = (await db.execute(select(Patient).where(Patient.user_id == user.id))).scalar_one()
        dentist = Dentist(full_name="Dr. Member", specialty="general")
        from decimal import Decimal

        service = Service(
            code="MEM1",
            name="Exam",
            category="preventive",
            duration_min=30,
            base_price=Decimal("50.00"),
        )
        db.add_all([dentist, service])
        await db.flush()
        start = NOW - timedelta(days=900)
        db.add(
            Appointment(
                patient_id=patient.id,
                dentist_id=dentist.id,
                service_id=service.id,
                slot=Range(start, start + timedelta(minutes=30), bounds="[)"),
                status=AppointmentStatus.CANCELLED,
                channel=AppointmentChannel.WEB,
            )
        )
        await db.commit()
        assert await anonymize_cancelled_guests(db, 12, now=NOW) == 0


async def test_run_retention_reads_periods_from_app_settings(ctx: Ctx) -> None:
    await ctx.execute(
        "UPDATE app_settings SET value = '30'::jsonb WHERE key = 'chat_retention_days'"
    )
    async with ctx.session_factory() as db:
        session = ChatSession()
        db.add(session)
        await db.flush()
        db.add(
            ChatMessage(
                session_id=session.id,
                role=ChatRole.USER,
                content="x",
                created_at=datetime.now(UTC) - timedelta(days=45),
            )
        )
        await db.commit()
        result = await run_retention(db)
    await ctx.execute(
        "UPDATE app_settings SET value = '90'::jsonb WHERE key = 'chat_retention_days'"
    )
    assert result["chat_messages_purged"] == 1
