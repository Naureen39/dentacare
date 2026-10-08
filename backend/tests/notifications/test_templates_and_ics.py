import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from jinja2 import UndefinedError

from app.core.config import Settings
from app.services.calendar_ics import build_ics
from app.services.email_templates import SUBJECTS, TEMPLATE_DIR, render_email
from tests.booking.conftest import Practice
from tests.notifications.helpers import appointment_in, book_via_api, calendar_of, events

SETTINGS = Settings(env="test")
URL = "https://clinic.example/appointments/cancel?token=abc"

CONTEXTS: dict[str, dict[str, Any]] = {
    "verify_email": {"action_url": URL, "hours": 24},
    "account_exists": {"action_url": URL},
    "password_reset": {"action_url": URL, "minutes": 30},
    "guest_code": {"first_name": "Jonas", "code": "123456", "minutes": 10},
    "confirmation": {
        "first_name": "Jonas",
        "service": "Routine Exam and Cleaning",
        "dentist": "Dr. Priya Raman",
        "when": "Wednesday, May 5, 2027 at 10:00 AM EDT",
        "short_date": "May 5",
        "cancel_policy": "You can cancel free of charge until May 4.",
        "cancel_url": URL,
        "manage_url": "https://clinic.example/portal/appointments",
    },
    "reminder": {
        "first_name": "Jonas",
        "service": "Routine Exam and Cleaning",
        "dentist": "Dr. Priya Raman",
        "when": "Wednesday, May 5, 2027 at 10:00 AM EDT",
        "headline": "Your appointment is tomorrow",
        "subject_hint": "Reminder: your appointment tomorrow, May 5",
        "cancel_policy": "Policy.",
        "confirm_url": "https://clinic.example/appointments/confirm?token=xyz",
        "cancel_url": URL,
    },
    "followup": {
        "first_name": "Jonas",
        "service": "Routine Exam and Cleaning",
        "dentist": "Dr. Priya Raman",
        "when": "May 5, 2027",
        "manage_url": "https://clinic.example/portal/appointments",
    },
    "recall": {
        "first_name": "Jonas",
        "when": "May 5, 2027",
        "book_url": "https://clinic.example/book",
    },
}


def test_every_template_has_an_html_and_a_text_version() -> None:
    names = {p.name for p in TEMPLATE_DIR.glob("*.j2") if not p.name.startswith("_")}
    for kind in SUBJECTS:
        assert f"{kind}.html.j2" in names and f"{kind}.txt.j2" in names
    assert set(CONTEXTS) == set(SUBJECTS)


@pytest.mark.parametrize("kind", sorted(CONTEXTS))
def test_each_email_renders_branded_html_and_text(kind: str) -> None:
    content = render_email(kind, to="jonas@example.com", settings=SETTINGS, **CONTEXTS[kind])

    assert content.to == "jonas@example.com" and content.subject
    assert content.html and content.text
    assert SETTINGS.clinic_name in content.html and SETTINGS.clinic_name in content.text
    assert "#0B2545" in content.html  # brand navy header
    for part in (content.html, content.text):
        assert SETTINGS.clinic_phone in part and SETTINGS.clinic_address in part
        assert "Demo environment, fictional clinic." in part


@pytest.mark.parametrize("kind", sorted(CONTEXTS))
def test_emails_contain_no_tracking_or_remote_resources(kind: str) -> None:
    html = render_email(kind, to="a@example.com", settings=SETTINGS, **CONTEXTS[kind]).html or ""
    assert "<img" not in html.lower() and "<script" not in html.lower()
    assert "<link" not in html.lower() and "url(" not in html.lower()
    allowed = {"https://clinic.example", "http://localhost:5173"}
    for address in re.findall(r"https?://[^\s\"'<>)]+", html):
        assert any(address.startswith(prefix) for prefix in allowed), address
    assert "pixel" not in html.lower() and "track" not in html.lower()


@pytest.mark.parametrize("kind", sorted(CONTEXTS))
def test_emails_never_contain_long_dashes(kind: str) -> None:
    content = render_email(kind, to="a@example.com", settings=SETTINGS, **CONTEXTS[kind])
    for part in (content.subject, content.text, content.html or ""):
        assert chr(0x2014) not in part and chr(0x2013) not in part


def test_names_are_escaped_in_html_but_not_in_text() -> None:
    context = {**CONTEXTS["guest_code"], "first_name": "<b>Mal</b> & Co"}
    content = render_email("guest_code", to="a@example.com", settings=SETTINGS, **context)
    assert "&lt;b&gt;Mal&lt;/b&gt; &amp; Co" in (content.html or "")
    assert "<b>Mal</b> & Co" not in (content.html or "")
    assert "<b>Mal</b> & Co" in content.text


def test_missing_context_is_an_error_not_a_blank() -> None:
    with pytest.raises(UndefinedError):
        render_email("guest_code", to="a@example.com", settings=SETTINGS, first_name="Jonas")


def test_unknown_template_is_rejected() -> None:
    with pytest.raises(ValueError):
        render_email("newsletter", to="a@example.com", settings=SETTINGS)


def test_reminder_without_a_confirm_link_offers_only_cancel() -> None:
    context = {**CONTEXTS["reminder"], "confirm_url": None}
    content = render_email("reminder", to="a@example.com", settings=SETTINGS, **context)
    assert "Confirm appointment" not in (content.html or "") and "Confirm:" not in content.text
    assert "Cancel appointment" in (content.html or "")


def test_guest_code_text_carries_the_code_in_a_stable_phrase() -> None:
    content = render_email(
        "guest_code", to="a@example.com", settings=SETTINGS, **CONTEXTS["guest_code"]
    )
    assert re.search(r"code is 123456", content.text)


# --- calendar files -------------------------------------------------------------------------


def test_ics_is_a_valid_calendar_with_one_utc_event() -> None:
    start = datetime(2027, 5, 5, 14, 0, tzinfo=UTC)
    now = datetime(2027, 4, 1, 9, 30, tzinfo=UTC)
    ics = build_ics(
        appointment_id="abc-123",
        start=start,
        end=start + timedelta(minutes=45),
        service_name="Routine Exam and Cleaning",
        dentist_name="Dr. Priya Raman",
        settings=SETTINGS,
        now=now,
    )
    assert ics.startswith(b"BEGIN:VCALENDAR") and b"END:VCALENDAR" in ics
    calendar = calendar_of(ics)
    [event] = events(ics)

    assert str(event["uid"]) == "abc-123@meridian.test"
    assert event["dtstart"].dt == start and event["dtend"].dt == start + timedelta(minutes=45)
    assert b"DTSTART:20270505T140000Z" in ics
    assert str(event["summary"]) == "Routine Exam and Cleaning at Meridian Dental Care"
    assert SETTINGS.clinic_address in str(event["location"])
    assert "Dr. Priya Raman" in str(event["description"])
    assert str(calendar["method"]) == "PUBLISH" and str(calendar["version"]) == "2.0"
    [alarm] = [c for c in event.walk() if c.name == "VALARM"]
    assert alarm["trigger"].dt == timedelta(hours=-2)


def test_ics_has_no_long_dashes() -> None:
    start = datetime(2027, 5, 5, 14, 0, tzinfo=UTC)
    ics = build_ics(
        appointment_id="x",
        start=start,
        end=start + timedelta(minutes=30),
        service_name="Exam",
        dentist_name="Dr. Raman",
        settings=SETTINGS,
    ).decode("utf-8")
    assert chr(0x2014) not in ics and chr(0x2013) not in ics


async def test_patient_downloads_the_calendar_file_for_their_own_appointment(
    practice: Practice,
) -> None:
    booked = await book_via_api(practice)
    headers = practice.ctx.auth(await practice.patient_token())
    response = await practice.ctx.client.get(
        f"/api/v1/me/appointments/{booked['id']}/ics", headers=headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert 'filename="appointment.ics"' in response.headers["content-disposition"]
    [event] = events(response.content)
    assert event["dtstart"].dt == datetime.fromisoformat(booked["start"])


async def test_calendar_files_are_private_to_the_patient(practice: Practice) -> None:
    from tests.auth.conftest import unique_email

    appointment = await appointment_in(practice, 72)
    stranger = unique_email("stranger")
    await practice.ctx.create_user(stranger)
    headers = practice.ctx.auth(await practice.ctx.access_token(stranger))
    assert (
        await practice.ctx.client.get(
            f"/api/v1/me/appointments/{appointment.id}/ics", headers=headers
        )
    ).status_code == 404
    assert (
        await practice.ctx.client.get(f"/api/v1/me/appointments/{appointment.id}/ics")
    ).status_code == 401
