import re
import uuid
from datetime import datetime

from httpx import Response

from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice, future_date, local_utc

VERIFY = "/api/v1/public/appointments/verification"
BOOK = "/api/v1/public/appointments"


async def request_code(practice: Practice, email: str) -> tuple[str, str]:
    """Ask for a code and read it from the captured email. Returns verification id and code."""
    response = await practice.ctx.client.post(VERIFY, json={"email": email, "first_name": "Jonas"})
    assert response.status_code == 202, response.text
    body = practice.ctx.mailer.outbox[-1].body
    code = re.search(r"code is (\d{6})", body)
    assert code
    return response.json()["verification_id"], code.group(1)


def guest_payload(
    practice: Practice, email: str, vid: str, otp: str, hold: str, start: datetime, **extra: object
) -> dict[str, object]:
    return {
        "verification_id": vid,
        "otp": otp,
        "hold_token": hold,
        "service_id": str(practice.cleaning.id),
        "dentist_id": str(practice.dentist_a.id),
        "start": start.isoformat(),
        "first_name": "Jonas",
        "last_name": "Weber",
        "email": email,
        "phone": "+1 555 0123",
        "consent": True,
        **extra,
    }


async def full_guest_booking(
    practice: Practice, email: str | None = None, hour: int = 10
) -> tuple[Response, str]:
    email = email or unique_email("guest")
    start = local_utc(future_date(2), hour, 0)
    vid, code = await request_code(practice, email)
    hold = await practice.hold(practice.dentist_a, start)
    response = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, code, hold, start)
    )
    return response, email


async def test_guest_books_after_verifying_their_email(practice: Practice) -> None:
    response, email = await full_guest_booking(practice)

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "booked"
    patients = await practice.ctx.fetch(
        "SELECT first_name, last_name, user_id IS NULL, source::text FROM patients WHERE email = :e",
        e=email,
    )
    assert patients == [("Jonas", "Weber", True, "web")]
    [(phone,)] = await practice.ctx.fetch(
        "SELECT phone_enc FROM patients WHERE email = :e", e=email
    )
    assert phone and "555" not in phone


async def test_verification_code_is_six_digits_hashed_and_expires_in_ten_minutes(
    practice: Practice,
) -> None:
    email = unique_email("guest")
    vid, code = await request_code(practice, email)
    assert re.fullmatch(r"\d{6}", code)
    [(stored, minutes)] = await practice.ctx.fetch(
        "SELECT code_hash, round(extract(epoch FROM (expires_at - created_at)) / 60) FROM guest_verifications"
    )
    assert code not in stored and len(stored) == 64
    assert minutes == 10


async def test_wrong_code_is_rejected_and_counts_attempts(practice: Practice) -> None:
    email = unique_email("guest")
    start = local_utc(future_date(2), 10, 0)
    vid, code = await request_code(practice, email)
    hold = await practice.hold(practice.dentist_a, start)
    wrong = "000000" if code != "000000" else "111111"

    response = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, wrong, hold, start)
    )
    assert response.status_code == 400 and response.json()["code"] == "otp_invalid"
    assert response.json()["details"]["attempts_remaining"] == 4
    assert await practice.ctx.fetch("SELECT count(*) FROM appointments") == [(0,)]


async def test_code_is_locked_after_five_wrong_attempts_even_if_then_correct(
    practice: Practice,
) -> None:
    email = unique_email("guest")
    start = local_utc(future_date(2), 10, 0)
    vid, code = await request_code(practice, email)
    hold = await practice.hold(practice.dentist_a, start)
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(5):
        await practice.ctx.client.post(
            BOOK, json=guest_payload(practice, email, vid, wrong, hold, start)
        )
    locked = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, code, hold, start)
    )
    assert locked.status_code == 400 and locked.json()["code"] == "otp_locked"
    assert await practice.ctx.fetch("SELECT count(*) FROM appointments") == [(0,)]


async def test_expired_code_is_rejected(practice: Practice) -> None:
    email = unique_email("guest")
    start = local_utc(future_date(2), 10, 0)
    vid, code = await request_code(practice, email)
    hold = await practice.hold(practice.dentist_a, start)
    await practice.ctx.execute(
        "UPDATE guest_verifications SET expires_at = now() - interval '1 second'"
    )
    response = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, code, hold, start)
    )
    assert response.status_code == 400 and response.json()["code"] == "otp_invalid"


async def test_code_is_single_use(practice: Practice) -> None:
    email = unique_email("guest")
    day = future_date(2)
    vid, code = await request_code(practice, email)
    first_start, second_start = local_utc(day, 10, 0), local_utc(day, 14, 0)
    first_hold = await practice.hold(practice.dentist_a, first_start)
    second_hold = await practice.hold(practice.dentist_a, second_start)

    ok = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, code, first_hold, first_start)
    )
    reuse = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, code, second_hold, second_start)
    )
    assert ok.status_code == 201
    assert reuse.status_code == 400


async def test_code_is_bound_to_the_email_address(practice: Practice) -> None:
    start = local_utc(future_date(2), 10, 0)
    vid, code = await request_code(practice, unique_email("owner"))
    hold = await practice.hold(practice.dentist_a, start)
    response = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, unique_email("thief"), vid, code, hold, start)
    )
    assert response.status_code == 400


async def test_unknown_verification_id_is_rejected(practice: Practice) -> None:
    start = local_utc(future_date(2), 10, 0)
    hold = await practice.hold(practice.dentist_a, start)
    response = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, unique_email(), str(uuid.uuid4()), "123456", hold, start)
    )
    assert response.status_code == 400


async def test_requesting_a_new_code_invalidates_the_previous_one(practice: Practice) -> None:
    email = unique_email("guest")
    start = local_utc(future_date(2), 10, 0)
    old_id, old_code = await request_code(practice, email)
    await request_code(practice, email)
    hold = await practice.hold(practice.dentist_a, start)
    response = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, old_id, old_code, hold, start)
    )
    assert response.status_code == 400


async def test_consent_is_required(practice: Practice) -> None:
    email = unique_email("guest")
    start = local_utc(future_date(2), 10, 0)
    vid, code = await request_code(practice, email)
    hold = await practice.hold(practice.dentist_a, start)
    response = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, code, hold, start, consent=False)
    )
    assert response.status_code == 422 and response.json()["code"] == "consent_required"


async def test_otp_must_be_exactly_six_digits(practice: Practice) -> None:
    email = unique_email("guest")
    start = local_utc(future_date(2), 10, 0)
    vid, _ = await request_code(practice, email)
    hold = await practice.hold(practice.dentist_a, start)
    for bad in ("12345", "1234567", "abcdef", "12 456"):
        response = await practice.ctx.client.post(
            BOOK, json=guest_payload(practice, email, vid, bad, hold, start)
        )
        assert response.status_code == 422


async def test_a_failed_booking_does_not_consume_the_code_or_create_a_patient(
    practice: Practice,
) -> None:
    email = unique_email("guest")
    day = future_date(2)
    taken, free = local_utc(day, 10, 0), local_utc(day, 14, 0)
    vid, code = await request_code(practice, email)
    hold = await practice.hold(practice.dentist_a, taken)
    await practice.book_direct(practice.dentist_a, taken)

    failed = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, code, hold, taken)
    )
    assert failed.status_code == 409
    assert await practice.ctx.fetch("SELECT count(*) FROM patients WHERE email = :e", e=email) == [
        (0,)
    ]

    hold2 = await practice.hold(practice.dentist_a, free)
    retry = await practice.ctx.client.post(
        BOOK, json=guest_payload(practice, email, vid, code, hold2, free)
    )
    assert retry.status_code == 201


async def test_second_booking_by_the_same_guest_reuses_the_patient_record(
    practice: Practice,
) -> None:
    email = unique_email("guest")
    await full_guest_booking(practice, email, hour=10)
    again, _ = await full_guest_booking(practice, email, hour=14)
    assert again.status_code == 201
    assert await practice.ctx.fetch("SELECT count(*) FROM patients WHERE email = :e", e=email) == [
        (1,)
    ]


async def test_guest_booking_is_audited_as_a_guest_action(practice: Practice) -> None:
    await full_guest_booking(practice)
    rows = await practice.ctx.fetch(
        "SELECT actor_role, actor_id IS NULL FROM audit_logs WHERE action = 'appointment.create'"
    )
    assert rows == [("guest", True)]


async def test_verification_requests_are_limited_per_address(practice: Practice) -> None:
    practice.ctx.set_settings(rate_limit_account_email_per_hour=2)
    email = unique_email("guest")
    codes = []
    for _ in range(3):
        response = await practice.ctx.client.post(
            VERIFY, json={"email": email, "first_name": "Jonas"}
        )
        codes.append(response.status_code)
    assert codes == [202, 202, 429]


async def test_guest_booking_endpoints_are_rate_limited_per_ip(practice: Practice) -> None:
    practice.ctx.set_settings(rate_limit_public_booking_per_hour=3)
    statuses = []
    for _ in range(5):
        response = await practice.ctx.client.post(
            VERIFY, json={"email": unique_email(), "first_name": "Jonas"}
        )
        statuses.append(response.status_code)
    assert statuses == [202, 202, 202, 429, 429]
    assert response.headers["retry-after"]
