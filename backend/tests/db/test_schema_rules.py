"""Constraints, defaults and indexes other than the double booking guard."""

from datetime import time
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import InvoiceStatus, PayerType, PaymentMethod
from app.db.models import (
    Dentist,
    DentistSchedule,
    IntentExample,
    InvoiceItem,
    KbChunk,
    KbDocument,
    NewsletterSubscriber,
    Patient,
    Payment,
)
from tests.db.conftest import Clinic, make_appointment, make_invoice, make_slot, make_user

CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"


async def _expect_sqlstate(session: AsyncSession, row: object, sqlstate: str) -> None:
    with pytest.raises(IntegrityError) as raised:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    assert raised.value.orig.sqlstate == sqlstate  # type: ignore[union-attr]


# --- identity -----------------------------------------------------------------------


async def test_user_email_is_unique_regardless_of_case(session: AsyncSession) -> None:
    session.add(make_user("Patient@Example.com"))
    await session.flush()
    await _expect_sqlstate(session, make_user("patient@example.COM"), UNIQUE_VIOLATION)


async def test_newsletter_email_is_case_insensitive_unique(session: AsyncSession) -> None:
    session.add(NewsletterSubscriber(email="News@Example.com"))
    await session.flush()
    await _expect_sqlstate(
        session, NewsletterSubscriber(email="news@example.com"), UNIQUE_VIOLATION
    )


async def test_primary_keys_and_timestamps_are_generated_by_the_database(
    session: AsyncSession,
) -> None:
    user = make_user("generated@example.com")
    session.add(user)
    await session.flush()
    await session.refresh(user)

    assert user.id is not None
    assert user.created_at.tzinfo is not None
    assert user.is_active is True
    assert user.failed_logins == 0


# --- schedules ----------------------------------------------------------------------


async def test_schedule_rejects_break_outside_working_hours(
    session: AsyncSession, clinic: Clinic
) -> None:
    row = DentistSchedule(
        dentist_id=clinic.dentist.id,
        weekday=1,
        start_time=time(8, 0),
        end_time=time(18, 0),
        break_start=time(17, 30),
        break_end=time(19, 0),
    )
    await _expect_sqlstate(session, row, CHECK_VIOLATION)


async def test_schedule_requires_both_break_bounds(session: AsyncSession, clinic: Clinic) -> None:
    row = DentistSchedule(
        dentist_id=clinic.dentist.id,
        weekday=1,
        start_time=time(8, 0),
        end_time=time(18, 0),
        break_start=time(12, 30),
    )
    await _expect_sqlstate(session, row, CHECK_VIOLATION)


async def test_schedule_weekday_is_limited_to_zero_through_six(
    session: AsyncSession, clinic: Clinic
) -> None:
    row = DentistSchedule(
        dentist_id=clinic.dentist.id, weekday=7, start_time=time(8, 0), end_time=time(18, 0)
    )
    await _expect_sqlstate(session, row, CHECK_VIOLATION)


async def test_one_schedule_row_per_dentist_and_weekday(
    session: AsyncSession, clinic: Clinic
) -> None:
    session.add(
        DentistSchedule(
            dentist_id=clinic.dentist.id, weekday=2, start_time=time(8, 0), end_time=time(18, 0)
        )
    )
    await session.flush()
    duplicate = DentistSchedule(
        dentist_id=clinic.dentist.id, weekday=2, start_time=time(9, 0), end_time=time(17, 0)
    )
    await _expect_sqlstate(session, duplicate, UNIQUE_VIOLATION)


# --- appointments -------------------------------------------------------------------


async def test_unbounded_or_empty_slots_are_rejected(session: AsyncSession, clinic: Clinic) -> None:
    unbounded = make_appointment(clinic)
    unbounded.slot = Range(make_slot().lower, None, bounds="[)")
    await _expect_sqlstate(session, unbounded, CHECK_VIOLATION)

    empty = make_appointment(clinic, offset_minutes=300)
    empty.slot = Range(empty_bound := make_slot(300).lower, empty_bound, bounds="[)")
    await _expect_sqlstate(session, empty, CHECK_VIOLATION)


async def test_appointment_cannot_be_deleted_while_invoiced(
    session: AsyncSession, clinic: Clinic
) -> None:
    appointment = make_appointment(clinic)
    session.add(appointment)
    await session.flush()
    session.add(make_invoice(appointment))
    await session.flush()

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.delete(appointment)
            await session.flush()


# --- billing ------------------------------------------------------------------------


async def test_invoice_numbers_are_sequential_and_start_at_one_thousand(
    session: AsyncSession, clinic: Clinic
) -> None:
    first_appt = make_appointment(clinic)
    second_appt = make_appointment(clinic, offset_minutes=120)
    session.add_all([first_appt, second_appt])
    await session.flush()

    first, second = make_invoice(first_appt), make_invoice(second_appt)
    session.add_all([first, second])
    await session.flush()
    await session.refresh(first)
    await session.refresh(second)

    assert first.number >= 1000
    assert second.number == first.number + 1


async def test_invoice_total_must_equal_subtotal_minus_discount_plus_tax(
    session: AsyncSession, clinic: Clinic
) -> None:
    appointment = make_appointment(clinic)
    session.add(appointment)
    await session.flush()

    good = make_invoice(appointment, subtotal="100.00", discount="10.00", tax="7.20", total="97.20")
    session.add(good)
    await session.flush()

    other = make_appointment(clinic, offset_minutes=240)
    session.add(other)
    await session.flush()
    bad = make_invoice(other, subtotal="100.00", discount="10.00", tax="7.20", total="97.19")
    await _expect_sqlstate(session, bad, CHECK_VIOLATION)


async def test_invoice_discount_cannot_exceed_subtotal(
    session: AsyncSession, clinic: Clinic
) -> None:
    appointment = make_appointment(clinic)
    session.add(appointment)
    await session.flush()
    bad = make_invoice(appointment, subtotal="50.00", discount="60.00", total="-10.00")
    await _expect_sqlstate(session, bad, CHECK_VIOLATION)


async def test_only_one_live_invoice_per_appointment_but_void_can_be_replaced(
    session: AsyncSession, clinic: Clinic
) -> None:
    appointment = make_appointment(clinic)
    session.add(appointment)
    await session.flush()

    session.add(make_invoice(appointment, status=InvoiceStatus.ISSUED))
    await session.flush()
    await _expect_sqlstate(session, make_invoice(appointment), UNIQUE_VIOLATION)

    voided = make_appointment(clinic, offset_minutes=300)
    session.add(voided)
    await session.flush()
    session.add(make_invoice(voided, status=InvoiceStatus.VOID))
    session.add(make_invoice(voided, status=InvoiceStatus.ISSUED))
    await session.flush()


async def test_invoice_item_amount_must_match_quantity_times_price_to_the_cent(
    session: AsyncSession, clinic: Clinic
) -> None:
    appointment = make_appointment(clinic)
    session.add(appointment)
    await session.flush()
    invoice = make_invoice(appointment)
    session.add(invoice)
    await session.flush()

    ok = InvoiceItem(
        invoice_id=invoice.id,
        description="Cleaning",
        qty=3,
        unit_price=Decimal("33.33"),
        amount=Decimal("99.99"),
    )
    session.add(ok)
    await session.flush()

    bad = InvoiceItem(
        invoice_id=invoice.id,
        description="Cleaning",
        qty=3,
        unit_price=Decimal("33.33"),
        amount=Decimal("100.00"),
    )
    await _expect_sqlstate(session, bad, CHECK_VIOLATION)


async def test_payment_amount_must_be_positive(session: AsyncSession, clinic: Clinic) -> None:
    appointment = make_appointment(clinic)
    session.add(appointment)
    await session.flush()
    invoice = make_invoice(appointment)
    session.add(invoice)
    await session.flush()

    bad = Payment(
        invoice_id=invoice.id,
        amount=Decimal("0.00"),
        method=PaymentMethod.CASH,
        payer_type=PayerType.PATIENT,
    )
    await _expect_sqlstate(session, bad, CHECK_VIOLATION)


async def test_money_is_stored_with_two_decimal_places(
    session: AsyncSession, clinic: Clinic
) -> None:
    row = (
        await session.execute(
            text(
                "SELECT numeric_precision, numeric_scale FROM information_schema.columns "
                "WHERE table_name = 'invoices' AND column_name = 'total'"
            )
        )
    ).one()
    assert (row.numeric_precision, row.numeric_scale) == (12, 2)


# --- search and vectors -------------------------------------------------------------


async def test_trigram_search_finds_patient_with_misspelled_name(
    session: AsyncSession, clinic: Clinic
) -> None:
    await session.execute(text("SET LOCAL pg_trgm.similarity_threshold = 0.3"))
    result = await session.execute(
        select(Patient.last_name).where(Patient.last_name.op("%")("Hartwel"))
    )
    assert "Hartwell" in result.scalars().all()


async def test_patient_name_trigram_indexes_exist(session: AsyncSession) -> None:
    result = await session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'patients'")
    )
    definitions = " ".join(result.scalars().all())
    assert "gin_trgm_ops" in definitions


def _vector(*leading: float, dims: int = 384) -> list[float]:
    return [*leading, *([0.0] * (dims - len(leading)))]


async def test_embedding_dimension_is_enforced(session: AsyncSession) -> None:
    row = IntentExample(intent="greeting", text="hello", embedding=_vector(1.0, dims=383))
    with pytest.raises(DBAPIError):
        async with session.begin_nested():
            session.add(row)
            await session.flush()


async def test_cosine_search_orders_chunks_by_similarity(session: AsyncSession) -> None:
    document = KbDocument(
        slug="hours",
        title="Opening hours",
        category="general",
        body="Open weekdays.",
        short_answer="Open weekdays.",
        content_hash="a" * 64,
    )
    session.add(document)
    await session.flush()
    session.add_all(
        [
            KbChunk(
                document_id=document.id,
                chunk_index=0,
                text="near",
                token_count=1,
                embedding=_vector(1.0, 0.1),
            ),
            KbChunk(
                document_id=document.id,
                chunk_index=1,
                text="far",
                token_count=1,
                embedding=_vector(0.0, 1.0),
            ),
            KbChunk(
                document_id=document.id,
                chunk_index=2,
                text="middle",
                token_count=1,
                embedding=_vector(1.0, 1.0),
            ),
        ]
    )
    await session.flush()

    query = _vector(1.0, 0.0)
    result = await session.execute(
        select(KbChunk.text).order_by(KbChunk.embedding.cosine_distance(query)).limit(3)
    )
    assert result.scalars().all() == ["near", "middle", "far"]


async def test_chunk_index_is_unique_per_document(session: AsyncSession) -> None:
    document = KbDocument(
        slug="parking",
        title="Parking",
        category="general",
        body="Free parking.",
        content_hash="b" * 64,
    )
    session.add(document)
    await session.flush()
    session.add(
        KbChunk(
            document_id=document.id, chunk_index=0, text="a", token_count=1, embedding=_vector(1.0)
        )
    )
    await session.flush()
    duplicate = KbChunk(
        document_id=document.id, chunk_index=0, text="b", token_count=1, embedding=_vector(1.0)
    )
    await _expect_sqlstate(session, duplicate, UNIQUE_VIOLATION)


async def test_vector_indexes_use_hnsw_with_cosine_ops(session: AsyncSession) -> None:
    result = await session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname LIKE '%embedding_hnsw'")
    )
    definitions = result.scalars().all()
    assert len(definitions) == 2
    assert all("hnsw" in d and "vector_cosine_ops" in d for d in definitions)


# --- referential rules --------------------------------------------------------------


async def test_deleting_a_user_keeps_the_patient_record(session: AsyncSession) -> None:
    user = make_user("owner@example.com")
    session.add(user)
    await session.flush()
    patient = Patient(first_name="Lena", last_name="Fischer", user_id=user.id)
    session.add(patient)
    await session.flush()

    await session.delete(user)
    await session.flush()
    await session.refresh(patient)
    assert patient.user_id is None


async def test_dentist_defaults(session: AsyncSession) -> None:
    dentist = Dentist(full_name="Dr. Test Person", specialty="general")
    session.add(dentist)
    await session.flush()
    await session.refresh(dentist)
    assert dentist.is_active is True
    assert dentist.color == "#13A3A1"
