"""The staff and admin console: who may call what, and what the new endpoints do."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.db.enums import AppointmentStatus, UserRole
from tests.auth.conftest import unique_email
from tests.booking.conftest import Practice, future_date, local_utc

API = "/api/v1"


async def token_for(practice: Practice, role: UserRole) -> str:
    return await practice.staff_token(role)


async def headers_for(practice: Practice, role: UserRole) -> dict[str, str]:
    return practice.ctx.auth(await token_for(practice, role))


async def dentist_login(practice: Practice) -> tuple[dict[str, str], str]:
    """A signed in dentist with a dentist record of their own. Returns headers and dentist id."""
    email = unique_email("dentist")
    await practice.ctx.create_user(email, UserRole.DENTIST, last_name="Okafor")
    token = await practice.ctx.access_token(email)
    rows = await practice.ctx.fetch(
        "SELECT d.id FROM dentists d JOIN users u ON u.id = d.user_id WHERE u.email = :e", e=email
    )
    return practice.ctx.auth(token), str(rows[0][0])


# --- who may call what ---------------------------------------------------------------------------

ADMIN_ONLY = [
    ("GET", "/admin/users"),
    ("POST", "/admin/users"),
    ("GET", "/admin/services"),
    ("POST", "/admin/services"),
    ("GET", "/admin/dentists"),
    ("GET", "/admin/kb/intents"),
    ("GET", "/admin/chat/sessions"),
    ("GET", "/admin/settings"),
    ("PUT", "/admin/settings"),
    ("GET", "/admin/audit-logs/export.csv"),
]
FRONT_DESK_OR_ADMIN = [
    ("GET", "/staff/alerts"),
]
EVERY_ID = "00000000-0000-4000-8000-000000000000"
PER_RECORD_ADMIN = [
    ("PATCH", f"/admin/users/{EVERY_ID}"),
    ("POST", f"/admin/users/{EVERY_ID}/reset-mfa"),
    ("PATCH", f"/admin/services/{EVERY_ID}"),
    ("PATCH", f"/admin/dentists/{EVERY_ID}"),
    ("GET", f"/admin/dentists/{EVERY_ID}/schedule"),
    ("PUT", f"/admin/dentists/{EVERY_ID}/schedule"),
    ("POST", f"/admin/dentists/{EVERY_ID}/time-off"),
    ("DELETE", f"/admin/time-off/{EVERY_ID}"),
    ("DELETE", f"/admin/kb/intents/{EVERY_ID}"),
    ("GET", f"/admin/chat/sessions/{EVERY_ID}"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY + PER_RECORD_ADMIN)
async def test_admin_endpoints_refuse_everyone_but_admins(
    practice: Practice, method: str, path: str
) -> None:
    client = practice.ctx.client
    assert (await client.request(method, f"{API}{path}", json={})).status_code == 401
    patient = practice.ctx.auth(await practice.patient_token())
    for headers in (
        patient,
        await headers_for(practice, UserRole.RECEPTIONIST),
        await headers_for(practice, UserRole.DENTIST),
    ):
        response = await client.request(method, f"{API}{path}", headers=headers, json={})
        assert response.status_code == 403, (method, path)


@pytest.mark.parametrize(("method", "path"), FRONT_DESK_OR_ADMIN)
async def test_front_desk_endpoints_refuse_patients_and_dentists(
    practice: Practice, method: str, path: str
) -> None:
    for headers in (
        practice.ctx.auth(await practice.patient_token()),
        await headers_for(practice, UserRole.DENTIST),
    ):
        assert (
            await practice.ctx.client.request(method, f"{API}{path}", headers=headers)
        ).status_code == 403
    ok = await practice.ctx.client.request(
        method, f"{API}{path}", headers=await headers_for(practice, UserRole.RECEPTIONIST)
    )
    assert ok.status_code == 200


async def test_clinical_and_money_screens_are_limited_by_role(practice: Practice) -> None:
    start = local_utc(future_date(2), 10)
    appointment = await practice.book_direct(practice.dentist_a, start)
    receptionist = await headers_for(practice, UserRole.RECEPTIONIST)
    client = practice.ctx.client
    note = {"note": "Private."}
    url = f"{API}/staff/appointments/{appointment.id}/clinical-note"
    for headers in (receptionist, await headers_for(practice, UserRole.ADMIN)):
        assert (await client.put(url, headers=headers, json=note)).status_code == 403
    # Front desk notes are not for dentists to write.
    body = {"body": "Call back after 5."}
    notes = f"{API}/patients/{practice.patient.id}/notes"
    assert (
        await client.post(notes, headers=await headers_for(practice, UserRole.DENTIST), json=body)
    ).status_code == 403
    assert (await client.post(notes, headers=receptionist, json=body)).status_code == 201
    # Reordering the schedule is front desk work, not the dentist's.
    move = f"{API}/staff/appointments/{appointment.id}/reschedule"
    dentist, _ = await dentist_login(practice)
    assert (
        await client.patch(move, headers=dentist, json={"start": start.isoformat()})
    ).status_code == 403


# --- staff accounts ---------------------------------------------------------------------------------


async def test_admin_creates_a_dentist_who_receives_a_set_password_link(practice: Practice) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    email = unique_email("newdoc")
    response = await practice.ctx.client.post(
        f"{API}/admin/users",
        headers=admin,
        json={
            "email": email,
            "role": "dentist",
            "full_name": "Dr. Ada Quill",
            "specialty": "Endodontics",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["dentist_name"] == "Dr. Ada Quill"
    assert re.search(r"/reset-password\?token=", practice.ctx.mailer.outbox[-1].body)
    # The same address cannot be used twice, and a dentist needs a name.
    again = await practice.ctx.client.post(
        f"{API}/admin/users", headers=admin, json={"email": email, "role": "receptionist"}
    )
    assert again.status_code == 409
    nameless = await practice.ctx.client.post(
        f"{API}/admin/users", headers=admin, json={"email": unique_email(), "role": "dentist"}
    )
    assert nameless.status_code == 422


async def test_deactivating_ends_sessions_and_mfa_can_be_reset(practice: Practice) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    email = unique_email("desk")
    user = await practice.ctx.create_user(email, UserRole.RECEPTIONIST)
    await practice.ctx.access_token(email)  # signs in and enrols two step verification
    client = practice.ctx.client

    reset = await client.post(f"{API}/admin/users/{user.id}/reset-mfa", headers=admin)
    assert reset.status_code == 200
    rows = await practice.ctx.fetch(
        "SELECT mfa_enabled, mfa_secret_enc IS NULL FROM users WHERE id = :i", i=user.id
    )
    assert rows == [(False, True)]

    off = await client.patch(
        f"{API}/admin/users/{user.id}", headers=admin, json={"is_active": False}
    )
    assert off.status_code == 200 and off.json()["is_active"] is False
    live = await practice.ctx.fetch(
        "SELECT count(*) FROM refresh_tokens WHERE user_id = :i AND revoked_at IS NULL", i=user.id
    )
    assert live == [(0,)]
    login = await practice.ctx.login(email)
    assert login.status_code in (401, 403)


async def test_an_admin_cannot_change_their_own_account_or_a_patient(practice: Practice) -> None:
    email = unique_email("boss")
    boss = await practice.ctx.create_user(email, UserRole.ADMIN)
    headers = practice.ctx.auth(await practice.ctx.access_token(email))
    client = practice.ctx.client
    assert (
        await client.patch(
            f"{API}/admin/users/{boss.id}", headers=headers, json={"is_active": False}
        )
    ).status_code == 403
    patient_user = (
        await practice.ctx.fetch(
            "SELECT user_id FROM patients WHERE id = :i", i=practice.patient.id
        )
    )[0][0]
    assert (
        await client.post(f"{API}/admin/users/{patient_user}/reset-mfa", headers=headers)
    ).status_code == 404
    listed = (await client.get(f"{API}/admin/users", headers=headers)).json()
    assert all(u["role"] != "patient" for u in listed)


# --- services and dated prices -----------------------------------------------------------------------


async def test_a_future_price_waits_for_its_day_and_today_applies_at_once(
    practice: Practice,
) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    client = practice.ctx.client
    sid = str(practice.cleaning.id)
    tomorrow = (datetime.now(UTC).date() + timedelta(days=3)).isoformat()

    later = await client.post(
        f"{API}/admin/services/{sid}/price-changes",
        headers=admin,
        json={"price": "150.00", "effective_from": tomorrow},
    )
    assert later.status_code == 201
    assert later.json()["base_price"] == "120.00"
    assert later.json()["price_changes"][0]["applied_at"] is None

    now = await client.post(
        f"{API}/admin/services/{sid}/price-changes",
        headers=admin,
        json={"price": "130.00", "effective_from": "2020-01-01"},
    )
    assert now.json()["base_price"] == "130.00"
    public = (await client.get(f"{API}/public/services")).json()
    assert next(s for s in public if s["code"] == "SV02")["base_price"] == "130.00"

    # The waiting change can be withdrawn; one that took effect cannot.
    waiting = next(c for c in now.json()["price_changes"] if c["applied_at"] is None)
    assert (
        await client.delete(
            f"{API}/admin/services/{sid}/price-changes/{waiting['id']}", headers=admin
        )
    ).status_code == 204
    applied = next(
        c
        for c in (await client.get(f"{API}/admin/services", headers=admin)).json()[0][
            "price_changes"
        ]
        if c["applied_at"]
    )
    assert (
        await client.delete(
            f"{API}/admin/services/{sid}/price-changes/{applied['id']}", headers=admin
        )
    ).status_code == 409


async def test_a_price_that_falls_due_later_is_applied_when_read(practice: Practice) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    sid = practice.crown.id
    await practice.ctx.execute(
        "INSERT INTO service_price_changes (service_id, price, effective_from) VALUES (:s, 999.00, current_date - 1)",
        s=sid,
    )
    listed = (await practice.ctx.client.get(f"{API}/admin/services", headers=admin)).json()
    assert next(s for s in listed if s["code"] == "SV05")["base_price"] == "999.00"


async def test_services_can_be_created_edited_and_hidden(practice: Practice) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    client = practice.ctx.client
    body = {
        "code": "SV99",
        "name": "Night Guard",
        "category": "restorative",
        "duration_min": 30,
        "base_price": "300.00",
    }
    created = await client.post(f"{API}/admin/services", headers=admin, json=body)
    assert created.status_code == 201
    assert (await client.post(f"{API}/admin/services", headers=admin, json=body)).status_code == 409
    sid = created.json()["id"]
    hidden = await client.patch(
        f"{API}/admin/services/{sid}", headers=admin, json={"is_active": False, "duration_min": 40}
    )
    assert hidden.json()["duration_min"] == 40
    codes = [s["code"] for s in (await client.get(f"{API}/public/services")).json()]
    assert "SV99" not in codes
    bad = await client.patch(f"{API}/admin/services/{sid}", headers=admin, json={"duration_min": 1})
    assert bad.status_code == 422


# --- dentists, hours and time off ------------------------------------------------------------------


async def test_working_hours_are_validated_and_replaced(practice: Practice) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    client = practice.ctx.client
    url = f"{API}/admin/dentists/{practice.dentist_a.id}/schedule"
    day = {
        "weekday": 0,
        "start_time": "09:00:00",
        "end_time": "17:00:00",
        "break_start": "12:00:00",
        "break_end": "13:00:00",
    }
    ok = await client.put(
        url,
        headers=admin,
        json={"days": [day, {**day, "weekday": 2, "break_start": None, "break_end": None}]},
    )
    assert ok.status_code == 200
    assert [d["weekday"] for d in (await client.get(url, headers=admin)).json()] == [0, 2]
    for bad in (
        [day, day],
        [{**day, "end_time": "08:00:00"}],
        [{**day, "break_end": None}],
        [{**day, "break_start": "07:00:00"}],
    ):
        assert (await client.put(url, headers=admin, json={"days": bad})).status_code == 422


async def test_time_off_reports_the_visits_it_affects_and_closes_the_day(
    practice: Practice,
) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    day = future_date(2)
    await practice.book_direct(practice.dentist_a, local_utc(day, 10))
    off = await practice.ctx.client.post(
        f"{API}/admin/dentists/{practice.dentist_a.id}/time-off",
        headers=admin,
        json={
            "starts_at": local_utc(day, 7).isoformat(),
            "ends_at": local_utc(day, 19).isoformat(),
            "reason": "leave",
        },
    )
    assert off.status_code == 201
    assert off.json()["affected_appointments"] == 1
    backwards = await practice.ctx.client.post(
        f"{API}/admin/dentists/{practice.dentist_a.id}/time-off",
        headers=admin,
        json={
            "starts_at": local_utc(day, 9).isoformat(),
            "ends_at": local_utc(day, 8).isoformat(),
            "reason": "leave",
        },
    )
    assert backwards.status_code == 422
    listed = (
        await practice.ctx.client.get(
            f"{API}/admin/dentists/{practice.dentist_a.id}/time-off", headers=admin
        )
    ).json()
    assert len(listed) == 1
    assert (
        await practice.ctx.client.delete(f"{API}/admin/time-off/{listed[0]['id']}", headers=admin)
    ).status_code == 204


async def test_a_dentist_can_be_limited_to_some_services_and_deactivated(
    practice: Practice,
) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    changed = await practice.ctx.client.patch(
        f"{API}/admin/dentists/{practice.dentist_a.id}",
        headers=admin,
        json={"service_ids": [str(practice.cleaning.id)], "is_active": False, "color": "#112233"},
    )
    assert changed.status_code == 200
    assert changed.json()["service_ids"] == [str(practice.cleaning.id)]
    unknown = await practice.ctx.client.patch(
        f"{API}/admin/dentists/{practice.dentist_a.id}",
        headers=admin,
        json={"service_ids": ["00000000-0000-4000-8000-0000000000aa"]},
    )
    assert unknown.status_code == 422
    names = [
        d["full_name"] for d in (await practice.ctx.client.get(f"{API}/public/dentists")).json()
    ]
    assert "Dr. Priya Raman" not in names


# --- assistant intents and transcripts --------------------------------------------------------------


async def test_intent_examples_can_be_added_and_removed(practice: Practice, fake_embedder) -> None:  # type: ignore[no-untyped-def]
    practice.ctx.app.state.embedder = fake_embedder
    admin = await headers_for(practice, UserRole.ADMIN)
    client = practice.ctx.client
    body = {"intent": "opening_hours", "text": "when do you open on saturdays"}
    created = await client.post(f"{API}/admin/kb/intents", headers=admin, json=body)
    assert created.status_code == 201
    assert (
        await client.post(f"{API}/admin/kb/intents", headers=admin, json=body)
    ).status_code == 409
    assert (
        await client.post(
            f"{API}/admin/kb/intents", headers=admin, json={"intent": "Bad Name", "text": "xxxx"}
        )
    ).status_code == 422
    listed = (await client.get(f"{API}/admin/kb/intents", headers=admin)).json()
    assert [e["text"] for e in listed] == [body["text"]]
    assert (
        await client.delete(f"{API}/admin/kb/intents/{created.json()['id']}", headers=admin)
    ).status_code == 204
    assert (
        await client.delete(f"{API}/admin/kb/intents/{created.json()['id']}", headers=admin)
    ).status_code == 404


async def test_transcripts_hide_personal_details_and_filter_by_feedback(practice: Practice) -> None:
    ctx = practice.ctx
    await ctx.execute(
        "INSERT INTO chat_sessions (id) VALUES ('aaaaaaaa-0000-4000-8000-000000000001'), ('aaaaaaaa-0000-4000-8000-000000000002')"
    )
    await ctx.execute(
        "INSERT INTO chat_messages (session_id, role, content, feedback) VALUES "
        "('aaaaaaaa-0000-4000-8000-000000000001', 'user', 'Hi, my name is Jane Smith, call 555 123 4567 or jane@example.com', NULL),"
        "('aaaaaaaa-0000-4000-8000-000000000001', 'assistant', 'Thanks. Born 03/04/1988?', -1),"
        "('aaaaaaaa-0000-4000-8000-000000000002', 'user', 'What are your hours?', NULL),"
        "('aaaaaaaa-0000-4000-8000-000000000002', 'assistant', 'We open at 8.', 1)"
    )
    admin = await headers_for(practice, UserRole.ADMIN)
    all_rows = (await ctx.client.get(f"{API}/admin/chat/sessions", headers=admin)).json()
    assert len(all_rows) == 2
    negative = (
        await ctx.client.get(f"{API}/admin/chat/sessions?feedback=negative", headers=admin)
    ).json()
    assert [r["thumbs_down"] for r in negative] == [1]
    transcript = (
        await ctx.client.get(f"{API}/admin/chat/sessions/{negative[0]['id']}", headers=admin)
    ).json()
    text_ = " ".join(m["content"] for m in transcript["messages"])
    assert transcript["masked"] is True
    for secret in ("Jane", "Smith", "555 123", "jane@example.com", "1988"):
        assert secret not in text_
    assert "[email]" in text_ and "[number]" in text_ and "[date]" in text_
    assert "[name]" in negative[0]["first_message"] or "[email]" in negative[0]["first_message"]
    assert await ctx.fetch("SELECT 1 FROM audit_logs WHERE action = 'chat.review'")
    bad = await ctx.client.get(f"{API}/admin/chat/sessions?feedback=maybe", headers=admin)
    assert bad.status_code == 422


# --- settings and the audit export -------------------------------------------------------------------


async def test_settings_are_read_changed_and_checked(practice: Practice) -> None:
    admin = await headers_for(practice, UserRole.ADMIN)
    client = practice.ctx.client
    current = (await client.get(f"{API}/admin/settings", headers=admin)).json()
    assert current["booking"]["cancellation_free_hours"] == 24
    assert current["clinic"]["timezone"] == "America/New_York"
    current["booking"]["cancellation_free_hours"] = 48
    current["reminders"]["hours_before"] = [72, 24]
    current["billing"]["monthly_revenue_target"] = "90000.00"
    saved = await client.put(
        f"{API}/admin/settings",
        headers=admin,
        json={k: current[k] for k in ("booking", "reminders", "billing")},
    )
    assert saved.status_code == 200, saved.text
    again = (await client.get(f"{API}/admin/settings", headers=admin)).json()
    assert again["booking"]["cancellation_free_hours"] == 48
    assert again["reminders"]["hours_before"] == [72, 24]
    assert float(again["billing"]["monthly_revenue_target"]) == 90000
    current["booking"]["slot_grid_minutes"] = 1
    refused = await client.put(
        f"{API}/admin/settings", headers=admin, json={"booking": current["booking"]}
    )
    assert refused.status_code == 422
    unknown = await client.put(f"{API}/admin/settings", headers=admin, json={"clinic": {}})
    assert unknown.status_code == 422


async def test_audit_export_neutralises_spreadsheet_formulas(practice: Practice) -> None:
    ctx = practice.ctx
    await ctx.execute(
        "INSERT INTO audit_logs (action, entity) VALUES ('test.event', '=HYPERLINK(\"x\")')"
    )
    admin = await headers_for(practice, UserRole.ADMIN)
    response = await ctx.client.get(
        f"{API}/admin/audit-logs/export.csv?action=test.event", headers=admin
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    body = response.text
    assert body.splitlines()[0].startswith("time,actor_id")
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body
    assert await ctx.fetch("SELECT 1 FROM audit_logs WHERE action = 'data.export'")


# --- staff work screens ---------------------------------------------------------------------------------


async def test_the_appointment_drawer_shows_a_clinical_note_only_to_its_dentist(
    practice: Practice,
) -> None:
    dentist, dentist_id = await dentist_login(practice)
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Dentist

        own = (await db.execute(select(Dentist).where(Dentist.id == dentist_id))).scalar_one()
    appointment = await practice.book_direct(own, local_utc(future_date(3), 9))
    other = await practice.book_direct(practice.dentist_a, local_utc(future_date(3), 11))
    client = practice.ctx.client

    saved = await client.put(
        f"{API}/staff/appointments/{appointment.id}/clinical-note",
        headers=dentist,
        json={"note": "Sensitive upper left."},
    )
    assert saved.status_code == 200
    stored = (
        await practice.ctx.fetch(
            "SELECT clinical_note_enc FROM appointments WHERE id = :i", i=appointment.id
        )
    )[0][0]
    assert stored and "Sensitive" not in stored

    mine = (await client.get(f"{API}/staff/appointments/{appointment.id}", headers=dentist)).json()
    assert mine["clinical_note"] == "Sensitive upper left."
    desk = (
        await client.get(
            f"{API}/staff/appointments/{appointment.id}",
            headers=await headers_for(practice, UserRole.RECEPTIONIST),
        )
    ).json()
    assert desk["clinical_note"] is None and desk["patient_email"]
    assert (
        await client.get(f"{API}/staff/appointments/{other.id}", headers=dentist)
    ).status_code == 404
    assert (
        await client.put(
            f"{API}/staff/appointments/{other.id}/clinical-note",
            headers=dentist,
            json={"note": "x"},
        )
    ).status_code == 404


async def test_completing_a_visit_adds_performed_services_to_the_invoice(
    practice: Practice,
) -> None:
    dentist, dentist_id = await dentist_login(practice)
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Dentist

        own = (await db.execute(select(Dentist).where(Dentist.id == dentist_id))).scalar_one()
    past = datetime.now(UTC) - timedelta(hours=3)
    appointment = await practice.book_direct(own, past, status=AppointmentStatus.CHECKED_IN)
    done = await practice.ctx.client.post(
        f"{API}/staff/appointments/{appointment.id}/complete",
        headers=dentist,
        json={"performed_service_ids": [str(practice.crown.id)], "clinical_note": "Crown fitted."},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    items = await practice.ctx.fetch(
        "SELECT description FROM invoice_items ii JOIN invoices i ON i.id = ii.invoice_id WHERE i.appointment_id = :a ORDER BY description",
        a=appointment.id,
    )
    assert [r[0] for r in items] == ["Porcelain Crown", "Routine Exam and Cleaning"]
    unknown = await practice.ctx.client.post(
        f"{API}/staff/appointments/{appointment.id}/complete",
        headers=dentist,
        json={"performed_service_ids": ["00000000-0000-4000-8000-0000000000aa"]},
    )
    assert unknown.status_code in (404, 422)
    # A receptionist may complete a visit but cannot write the clinical note.
    desk = await headers_for(practice, UserRole.RECEPTIONIST)
    other = await practice.book_direct(
        practice.dentist_b, past - timedelta(days=1), status=AppointmentStatus.CHECKED_IN
    )
    refused = await practice.ctx.client.post(
        f"{API}/staff/appointments/{other.id}/complete", headers=desk, json={"clinical_note": "x"}
    )
    assert refused.status_code == 403


async def test_front_desk_can_move_a_visit_and_a_clash_leaves_it_alone(practice: Practice) -> None:
    desk = await headers_for(practice, UserRole.RECEPTIONIST)
    day = future_date(2)
    first = await practice.book_direct(practice.dentist_a, local_utc(day, 9))
    blocker = await practice.book_direct(practice.dentist_b, local_utc(day, 14))
    client = practice.ctx.client

    moved = await client.patch(
        f"{API}/staff/appointments/{first.id}/reschedule",
        headers=desk,
        json={"start": local_utc(day, 15).isoformat(), "dentist_id": str(practice.dentist_a.id)},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["rescheduled_from"] == str(first.id)
    old = await practice.ctx.fetch("SELECT status FROM appointments WHERE id = :i", i=first.id)
    assert old == [("cancelled",)]

    new_id = moved.json()["id"]
    clash = await client.patch(
        f"{API}/staff/appointments/{new_id}/reschedule",
        headers=desk,
        json={"start": local_utc(day, 14).isoformat(), "dentist_id": str(practice.dentist_b.id)},
    )
    assert clash.status_code == 409, clash.text
    still = await practice.ctx.fetch("SELECT status FROM appointments WHERE id = :i", i=new_id)
    assert still == [("booked",)]
    assert blocker.id


async def test_patient_history_notes_duplicates_and_alerts(practice: Practice) -> None:
    desk = await headers_for(practice, UserRole.RECEPTIONIST)
    client = practice.ctx.client
    await practice.book_direct(practice.dentist_a, local_utc(future_date(2), 10))
    history = (
        await client.get(f"{API}/patients/{practice.patient.id}/history", headers=desk)
    ).json()
    assert len(history["appointments"]) == 1 and history["invoices"] == []

    posted = await client.post(
        f"{API}/patients/{practice.patient.id}/notes",
        headers=desk,
        json={"body": "Prefers mornings."},
    )
    assert posted.status_code == 201
    stored = (await practice.ctx.fetch("SELECT body_enc FROM patient_notes"))[0][0]
    assert "mornings" not in stored
    notes = (await client.get(f"{API}/patients/{practice.patient.id}/notes", headers=desk)).json()
    assert notes[0]["body"] == "Prefers mornings."

    await practice.ctx.execute(
        "INSERT INTO patients (first_name, last_name, email, source) VALUES ('Amelia', 'Hartwel', 'other@example.com', 'walk_in'), ('Zed', 'Quill', 'zq@example.com', 'walk_in')"
    )
    duplicates = (
        await client.get(f"{API}/patients/{practice.patient.id}/duplicates", headers=desk)
    ).json()
    assert [d["patient"]["last_name"] for d in duplicates] == ["Hartwel"]
    assert "similar name" in duplicates[0]["reasons"]

    soon = datetime.now(UTC) + timedelta(hours=20)
    await practice.book_direct(practice.dentist_b, soon.replace(minute=0, second=0, microsecond=0))
    await practice.ctx.execute(
        "INSERT INTO contact_inquiries (name, message, source) VALUES ('A', 'hello there', 'contact_form')"
    )
    alerts = (await client.get(f"{API}/staff/alerts", headers=desk)).json()
    assert alerts == {"unconfirmed_soon": 1, "new_inquiries": 1}


async def test_a_dentist_sees_their_own_numbers_and_no_invoices(practice: Practice) -> None:
    dentist, dentist_id = await dentist_login(practice)
    async with practice.ctx.session_factory() as db:
        from sqlalchemy import select

        from app.db.models import Dentist

        own = (await db.execute(select(Dentist).where(Dentist.id == dentist_id))).scalar_one()
    base = datetime.now(UTC) - timedelta(days=3)
    await practice.book_direct(own, base, status=AppointmentStatus.COMPLETED)
    await practice.book_direct(own, base - timedelta(days=1), status=AppointmentStatus.NO_SHOW)
    performance = (
        await practice.ctx.client.get(f"{API}/staff/me/performance", headers=dentist)
    ).json()
    assert performance["visits"] == 1 and performance["no_shows"] == 1
    assert performance["no_show_rate"] == 0.5
    denied = await practice.ctx.client.get(
        f"{API}/staff/me/performance", headers=await headers_for(practice, UserRole.RECEPTIONIST)
    )
    assert denied.status_code == 403
    history = await practice.ctx.client.get(
        f"{API}/patients/{practice.patient.id}/history", headers=dentist
    )
    assert history.status_code == 200 and history.json()["invoices"] == []


def test_masking_covers_the_common_ways_people_write_themselves() -> None:
    from app.services.pii import mask_text

    assert mask_text("Email me at a.b+c@mail.co.uk") == "Email me at [email]"
    assert mask_text("Phone +1 (555) 010-0199 please") == "Phone [number] please"
    assert (
        mask_text("I'm Dana Whitfield and I was born 1/2/90") == "I'm [name] and I was born [date]"
    )
    assert mask_text("Is 9:30 free on the 14th?") == "Is 9:30 free on the 14th?"


async def test_staff_can_send_a_reminder_now_to_a_booked_visit(practice: Practice) -> None:
    desk = await headers_for(practice, UserRole.RECEPTIONIST)
    appointment = await practice.book_direct(practice.dentist_a, local_utc(future_date(2), 10))
    url = f"{API}/staff/appointments/{appointment.id}/remind"
    sent = await practice.ctx.client.post(url, headers=desk)
    assert sent.status_code == 200, sent.text
    assert practice.ctx.mailer.outbox
    again = await practice.ctx.client.post(url, headers=desk)  # a second press sends again
    assert again.status_code == 200
    assert await practice.ctx.fetch("SELECT 1 FROM audit_logs WHERE action = 'reminder.manual'")
    # Not for dentists, patients, finished or past visits.
    assert (
        await practice.ctx.client.post(url, headers=await headers_for(practice, UserRole.DENTIST))
    ).status_code == 403
    done = await practice.book_direct(
        practice.dentist_b, local_utc(future_date(3), 10), status=AppointmentStatus.CANCELLED
    )
    assert (
        await practice.ctx.client.post(f"{API}/staff/appointments/{done.id}/remind", headers=desk)
    ).status_code == 422
    past = await practice.book_direct(practice.dentist_b, datetime.now(UTC) - timedelta(days=1))
    assert (
        await practice.ctx.client.post(f"{API}/staff/appointments/{past.id}/remind", headers=desk)
    ).status_code == 422
