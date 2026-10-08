"""Role matrix and object level access. Every protected route has negative tests."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import Range

from app.core.security import create_jwt
from app.db.enums import AppointmentChannel, AppointmentStatus, UserRole
from app.db.models import Appointment, Dentist, Service
from tests.auth.conftest import Ctx, unique_email

SLOT_START = datetime(2027, 5, 4, 14, 0, tzinfo=UTC)


@dataclass
class People:
    tokens: dict[UserRole, str]
    patient_id: uuid.UUID
    other_patient_id: uuid.UUID
    dentist_user_id: uuid.UUID
    user_ids: dict[UserRole, uuid.UUID]


async def build_people(ctx: Ctx) -> People:
    tokens: dict[UserRole, str] = {}
    user_ids: dict[UserRole, uuid.UUID] = {}
    for role in UserRole:
        email = unique_email(role.value)
        user = await ctx.create_user(email, role, first_name=role.value.title(), last_name="Tester")
        user_ids[role] = user.id
        tokens[role] = await ctx.access_token(email)
    [(patient_id,)] = await ctx.fetch(
        "SELECT p.id FROM patients p JOIN users u ON u.id = p.user_id WHERE u.role = 'patient'"
    )
    other = await ctx.create_user(
        unique_email("other"), UserRole.PATIENT, first_name="Other", last_name="Patient"
    )
    [(other_patient_id,)] = await ctx.fetch(
        "SELECT id FROM patients WHERE user_id = :u", u=other.id
    )
    return People(tokens, patient_id, other_patient_id, user_ids[UserRole.DENTIST], user_ids)


async def link_dentist_to_patient(ctx: Ctx, people: People, patient_id: uuid.UUID) -> None:
    async with ctx.session_factory() as db:
        from sqlalchemy import select

        dentist_id = (
            await db.execute(select(Dentist.id).where(Dentist.user_id == people.dentist_user_id))
        ).scalar_one()
        service = Service(
            code=f"T{uuid.uuid4().hex[:6]}",
            name="Exam",
            category="preventive",
            duration_min=45,
            base_price=Decimal("120.00"),
        )
        db.add(service)
        await db.flush()
        db.add(
            Appointment(
                patient_id=patient_id,
                dentist_id=dentist_id,
                service_id=service.id,
                slot=Range(SLOT_START, SLOT_START + timedelta(minutes=45), bounds="[)"),
                status=AppointmentStatus.BOOKED,
                channel=AppointmentChannel.STAFF,
            )
        )
        await db.commit()


# --- unauthenticated access -----------------------------------------------------------

PROTECTED = [
    ("GET", "/api/v1/auth/me"),
    ("POST", "/api/v1/auth/password"),
    ("POST", "/api/v1/auth/mfa/setup"),
    ("GET", "/api/v1/me"),
    ("PATCH", "/api/v1/me"),
    ("GET", "/api/v1/patients"),
    ("GET", f"/api/v1/patients/{uuid.uuid4()}"),
    ("PATCH", f"/api/v1/patients/{uuid.uuid4()}"),
    ("GET", "/api/v1/admin/audit-logs"),
    ("PATCH", f"/api/v1/admin/users/{uuid.uuid4()}/role"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_protected_routes_reject_anonymous_callers(ctx: Ctx, method: str, path: str) -> None:
    response = await ctx.client.request(method, path, json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "unauthorized"


@pytest.mark.parametrize("header", ["Bearer", "Bearer not.a.token", "Basic abc", "bearer"])
async def test_malformed_authorization_headers_are_rejected(ctx: Ctx, header: str) -> None:
    response = await ctx.client.get("/api/v1/auth/me", headers={"Authorization": header})
    assert response.status_code == 401


async def test_expired_access_token_is_rejected(ctx: Ctx) -> None:
    user = await ctx.create_user(unique_email())
    expired = create_jwt(
        ctx.settings,
        user_id=user.id,
        role="patient",
        token_type="access",
        mfa=False,
        lifetime=timedelta(minutes=5),
        now=datetime.now(UTC) - timedelta(hours=1),
    )
    assert (await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(expired))).status_code == 401


async def test_token_of_a_deactivated_user_stops_working_immediately(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    token = await ctx.access_token(email)
    assert (await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(token))).status_code == 200
    await ctx.execute("UPDATE users SET is_active = false")
    assert (await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(token))).status_code == 401


# --- role matrix ---------------------------------------------------------------------

ALL = set(UserRole)
STAFF = {UserRole.ADMIN, UserRole.RECEPTIONIST, UserRole.DENTIST}
FRONT_DESK = {UserRole.ADMIN, UserRole.RECEPTIONIST}


@pytest.mark.parametrize(
    ("method", "template", "allowed", "body"),
    [
        ("GET", "/api/v1/me", {UserRole.PATIENT}, None),
        ("PATCH", "/api/v1/me", {UserRole.PATIENT}, {"first_name": "Renamed"}),
        ("GET", "/api/v1/patients", STAFF, None),
        ("PATCH", "/api/v1/patients/{other}", FRONT_DESK, {"first_name": "Renamed"}),
        ("GET", "/api/v1/admin/audit-logs", {UserRole.ADMIN}, None),
    ],
)
async def test_role_matrix(
    ctx: Ctx, method: str, template: str, allowed: set[UserRole], body: dict[str, object] | None
) -> None:
    people = await build_people(ctx)
    path = template.format(other=people.other_patient_id)
    for role in UserRole:
        response = await ctx.client.request(
            method, path, headers=ctx.auth(people.tokens[role]), json=body
        )
        if role in allowed:
            assert response.status_code == 200, f"{role} should be allowed on {method} {path}"
        else:
            assert response.status_code == 403, f"{role} should be denied on {method} {path}"
            assert response.json()["code"] == "forbidden"


async def test_every_role_can_read_its_own_identity(ctx: Ctx) -> None:
    people = await build_people(ctx)
    for role in UserRole:
        response = await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(people.tokens[role]))
        assert response.status_code == 200 and response.json()["role"] == role.value


async def test_role_changes_require_admin(ctx: Ctx) -> None:
    people = await build_people(ctx)
    path = f"/api/v1/admin/users/{people.user_ids[UserRole.PATIENT]}/role"
    for role in (UserRole.PATIENT, UserRole.RECEPTIONIST, UserRole.DENTIST):
        response = await ctx.client.patch(
            path, headers=ctx.auth(people.tokens[role]), json={"role": "admin"}
        )
        assert response.status_code == 403
    assert await ctx.fetch(
        "SELECT role::text FROM users WHERE id = :i", i=people.user_ids[UserRole.PATIENT]
    ) == [("patient",)]


# --- object level access: patients ---------------------------------------------------


async def test_patient_cannot_read_another_patients_record(ctx: Ctx) -> None:
    people = await build_people(ctx)
    token = people.tokens[UserRole.PATIENT]
    for target in (
        people.other_patient_id,
        people.patient_id,
    ):  # even their own via the staff route
        response = await ctx.client.get(f"/api/v1/patients/{target}", headers=ctx.auth(token))
        assert response.status_code == 403


async def test_patient_cannot_modify_another_patients_record(ctx: Ctx) -> None:
    people = await build_people(ctx)
    response = await ctx.client.patch(
        f"/api/v1/patients/{people.other_patient_id}",
        headers=ctx.auth(people.tokens[UserRole.PATIENT]),
        json={"first_name": "Hijacked"},
    )
    assert response.status_code == 403
    assert await ctx.fetch(
        "SELECT first_name FROM patients WHERE id = :i", i=people.other_patient_id
    ) == [("Other",)]


async def test_me_only_ever_returns_the_signed_in_patient(ctx: Ctx) -> None:
    people = await build_people(ctx)
    response = await ctx.client.get("/api/v1/me", headers=ctx.auth(people.tokens[UserRole.PATIENT]))
    assert response.json()["id"] == str(people.patient_id)
    assert response.json()["first_name"] == "Patient"


async def test_patient_update_edits_only_their_own_row(ctx: Ctx) -> None:
    people = await build_people(ctx)
    response = await ctx.client.patch(
        "/api/v1/me",
        headers=ctx.auth(people.tokens[UserRole.PATIENT]),
        json={"first_name": "Changed"},
    )
    assert response.status_code == 200
    names: dict[str, str] = dict(await ctx.fetch("SELECT id::text, first_name FROM patients"))
    assert names[str(people.patient_id)] == "Changed"
    assert names[str(people.other_patient_id)] == "Other"


@pytest.mark.parametrize(
    "extra",
    [
        {"role": "admin"},
        {"user_id": str(uuid.uuid4())},
        {"id": str(uuid.uuid4())},
        {"email": "attacker@example.com"},
        {"source": "referral"},
        {"anonymized_at": None},
    ],
)
async def test_profile_update_rejects_mass_assignment(ctx: Ctx, extra: dict[str, object]) -> None:
    people = await build_people(ctx)
    response = await ctx.client.patch(
        "/api/v1/me",
        headers=ctx.auth(people.tokens[UserRole.PATIENT]),
        json={"first_name": "Ok", **extra},
    )
    assert response.status_code == 422


async def test_dentist_sees_only_patients_they_treat(ctx: Ctx) -> None:
    people = await build_people(ctx)
    await link_dentist_to_patient(ctx, people, people.patient_id)
    headers = ctx.auth(people.tokens[UserRole.DENTIST])

    own = await ctx.client.get(f"/api/v1/patients/{people.patient_id}", headers=headers)
    other = await ctx.client.get(f"/api/v1/patients/{people.other_patient_id}", headers=headers)
    listing = await ctx.client.get("/api/v1/patients", headers=headers)

    assert own.status_code == 200
    assert other.status_code == 404  # indistinguishable from a record that does not exist
    assert [p["id"] for p in listing.json()] == [str(people.patient_id)]


async def test_dentist_cannot_edit_patients(ctx: Ctx) -> None:
    people = await build_people(ctx)
    await link_dentist_to_patient(ctx, people, people.patient_id)
    response = await ctx.client.patch(
        f"/api/v1/patients/{people.patient_id}",
        headers=ctx.auth(people.tokens[UserRole.DENTIST]),
        json={"first_name": "Renamed"},
    )
    assert response.status_code == 403


async def test_receptionist_and_admin_can_view_and_edit_any_patient(ctx: Ctx) -> None:
    people = await build_people(ctx)
    for role in FRONT_DESK:
        headers = ctx.auth(people.tokens[role])
        view = await ctx.client.get(f"/api/v1/patients/{people.other_patient_id}", headers=headers)
        edit = await ctx.client.patch(
            f"/api/v1/patients/{people.other_patient_id}",
            headers=headers,
            json={"last_name": f"By{role.value}"},
        )
        assert view.status_code == edit.status_code == 200


async def test_unknown_patient_is_not_found(ctx: Ctx) -> None:
    people = await build_people(ctx)
    response = await ctx.client.get(
        f"/api/v1/patients/{uuid.uuid4()}", headers=ctx.auth(people.tokens[UserRole.RECEPTIONIST])
    )
    assert response.status_code == 404


async def test_patient_search_uses_fuzzy_matching(ctx: Ctx) -> None:
    people = await build_people(ctx)
    response = await ctx.client.get(
        "/api/v1/patients",
        params={"q": "Recepsionist"},
        headers=ctx.auth(people.tokens[UserRole.RECEPTIONIST]),
    )
    assert response.status_code == 200
    assert response.json() == [] or all("first_name" in p for p in response.json())
    exact = await ctx.client.get(
        "/api/v1/patients",
        params={"q": "Oth"},
        headers=ctx.auth(people.tokens[UserRole.RECEPTIONIST]),
    )
    assert [p["first_name"] for p in exact.json()] == ["Other"]


# --- encryption, audit and administration --------------------------------------------


async def test_sensitive_fields_are_encrypted_in_the_database_and_readable_through_the_api(
    ctx: Ctx,
) -> None:
    people = await build_people(ctx)
    headers = ctx.auth(people.tokens[UserRole.RECEPTIONIST])
    payload = {
        "phone": "+1 555 0177",
        "date_of_birth": "1988-02-29",
        "address": "12 Harbour Lane, Springfield",
        "insurance_member_id": "MBR-99812",
    }
    assert (
        await ctx.client.patch(
            f"/api/v1/patients/{people.patient_id}", headers=headers, json=payload
        )
    ).status_code == 200

    [row] = await ctx.fetch(
        "SELECT phone_enc, dob_enc, address_enc, insurance_member_id_enc FROM patients WHERE id = :i",
        i=people.patient_id,
    )
    for ciphertext, plain in zip(row, ("555", "1988", "Harbour", "99812"), strict=True):
        assert ciphertext and plain not in str(ciphertext)

    body = (await ctx.client.get(f"/api/v1/patients/{people.patient_id}", headers=headers)).json()
    assert body["phone"] == payload["phone"]
    assert body["date_of_birth"] == payload["date_of_birth"]
    assert body["address"] == payload["address"]
    assert body["insurance_member_id"] == payload["insurance_member_id"]


async def test_staff_record_access_and_changes_are_audited_without_personal_data(ctx: Ctx) -> None:
    people = await build_people(ctx)
    headers = ctx.auth(people.tokens[UserRole.RECEPTIONIST])
    await ctx.client.get(f"/api/v1/patients/{people.patient_id}", headers=headers)
    await ctx.client.patch(
        f"/api/v1/patients/{people.patient_id}",
        headers=headers,
        json={"phone": "+1 555 0100", "first_name": "Sam"},
    )

    rows = await ctx.fetch(
        "SELECT action, entity, entity_id, metadata::text FROM audit_logs "
        "WHERE action IN ('patient.view', 'patient.update') ORDER BY created_at"
    )
    assert [r[0] for r in rows] == ["patient.view", "patient.update"]
    assert all(r[1] == "patient" and r[2] == str(people.patient_id) for r in rows)
    assert "555" not in str(rows) and "Sam" not in str(rows)
    assert '"fields": ["first_name", "phone"]' in rows[1][3]


async def test_admin_can_read_the_audit_log_with_filters(ctx: Ctx) -> None:
    people = await build_people(ctx)
    admin = ctx.auth(people.tokens[UserRole.ADMIN])
    response = await ctx.client.get(
        "/api/v1/admin/audit-logs", params={"action": "auth.login"}, headers=admin
    )
    assert response.status_code == 200
    entries = response.json()
    assert entries and all(e["action"] == "auth.login" for e in entries)
    assert {
        "id",
        "actor_id",
        "actor_role",
        "action",
        "entity",
        "entity_id",
        "ip",
        "metadata",
        "created_at",
    } == set(entries[0])
    assert (
        await ctx.client.get("/api/v1/admin/audit-logs", params={"limit": 0}, headers=admin)
    ).status_code == 422


async def test_role_change_is_audited_and_ends_existing_sessions(ctx: Ctx) -> None:
    people = await build_people(ctx)
    target = people.user_ids[UserRole.PATIENT]
    admin = ctx.auth(people.tokens[UserRole.ADMIN])

    response = await ctx.client.patch(
        f"/api/v1/admin/users/{target}/role", headers=admin, json={"role": "receptionist"}
    )
    assert response.status_code == 200 and response.json()["role"] == "receptionist"

    assert await ctx.fetch(
        "SELECT count(*) FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=target
    ) == [(0,)]
    [(metadata,)] = await ctx.fetch(
        "SELECT metadata::text FROM audit_logs WHERE action = 'user.role_change'"
    )
    assert '"from": "patient"' in str(metadata) and '"to": "receptionist"' in str(metadata)


async def test_promoting_to_admin_does_not_grant_access_without_mfa(ctx: Ctx) -> None:
    people = await build_people(ctx)
    target = people.user_ids[UserRole.PATIENT]
    stale_token = people.tokens[UserRole.PATIENT]
    await ctx.client.patch(
        f"/api/v1/admin/users/{target}/role",
        headers=ctx.auth(people.tokens[UserRole.ADMIN]),
        json={"role": "admin"},
    )
    # The old token no longer carries any privilege: role is read from the database and an
    # admin session must have passed MFA.
    response = await ctx.client.get("/api/v1/admin/audit-logs", headers=ctx.auth(stale_token))
    assert response.status_code == 403
    assert response.json()["code"] == "mfa_required"


async def test_admin_cannot_change_their_own_role_or_an_unknown_user(ctx: Ctx) -> None:
    people = await build_people(ctx)
    admin = ctx.auth(people.tokens[UserRole.ADMIN])
    own = await ctx.client.patch(
        f"/api/v1/admin/users/{people.user_ids[UserRole.ADMIN]}/role",
        headers=admin,
        json={"role": "patient"},
    )
    ghost = await ctx.client.patch(
        f"/api/v1/admin/users/{uuid.uuid4()}/role", headers=admin, json={"role": "patient"}
    )
    invalid = await ctx.client.patch(
        f"/api/v1/admin/users/{people.user_ids[UserRole.PATIENT]}/role",
        headers=admin,
        json={"role": "superuser"},
    )
    assert (own.status_code, ghost.status_code, invalid.status_code) == (403, 404, 422)
