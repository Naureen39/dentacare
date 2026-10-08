from datetime import UTC, datetime, timedelta

import pytest

from app.db.enums import UserRole
from tests.auth.conftest import STRONG_PASSWORD, Ctx, unique_email

REGISTER = "/api/v1/auth/register"
GENERIC = "The email address or password is incorrect."


def registration(email: str, password: str = STRONG_PASSWORD, **extra: object) -> dict[str, object]:
    return {
        "email": email,
        "password": password,
        "first_name": "Amelia",
        "last_name": "Hartwell",
        **extra,
    }


# --- registration and verification --------------------------------------------------


async def test_registration_creates_unverified_patient_and_sends_link(ctx: Ctx) -> None:
    email = unique_email()
    response = await ctx.client.post(REGISTER, json=registration(email, phone="+1 555 0100"))

    assert response.status_code == 202
    assert len(ctx.mailer.outbox) == 1
    assert ctx.mailer.outbox[0].to == email
    rows = await ctx.fetch(
        "SELECT role::text, email_verified_at FROM users WHERE email = :e", e=email
    )
    assert rows == [("patient", None)]
    patients = await ctx.fetch(
        "SELECT first_name, user_id IS NOT NULL FROM patients WHERE email = :e", e=email
    )
    assert patients == [("Amelia", True)]


async def test_registration_response_is_identical_for_existing_email(ctx: Ctx) -> None:
    email = unique_email()
    first = await ctx.client.post(REGISTER, json=registration(email))
    second = await ctx.client.post(REGISTER, json=registration(email))

    assert second.status_code == first.status_code == 202
    assert second.json() == first.json()
    assert len(await ctx.fetch("SELECT 1 FROM users WHERE email = :e", e=email)) == 1
    assert "already exists" in ctx.mailer.outbox[-1].subject


async def test_registration_rejects_weak_passwords(ctx: Ctx) -> None:
    for password in ["short1!", "passwordpassword", "aaaaaaaaaaaaaa"]:
        response = await ctx.client.post(REGISTER, json=registration(unique_email(), password))
        assert response.status_code == 422
        assert response.json()["code"] == "weak_password"
    assert ctx.mailer.outbox == []


async def test_registration_rejects_unknown_fields_such_as_role(ctx: Ctx) -> None:
    response = await ctx.client.post(REGISTER, json=registration(unique_email(), role="admin"))
    assert response.status_code == 422


async def test_registration_stores_phone_encrypted(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.client.post(REGISTER, json=registration(email, phone="+1 555 0142"))
    [(stored,)] = await ctx.fetch("SELECT phone_enc FROM patients WHERE email = :e", e=email)
    assert stored and "555" not in stored


async def test_email_verification_activates_the_account_once(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.client.post(REGISTER, json=registration(email))
    token = ctx.last_token("/verify-email")

    first = await ctx.client.post("/api/v1/auth/verify-email", json={"token": token})
    again = await ctx.client.post("/api/v1/auth/verify-email", json={"token": token})

    assert first.status_code == 200
    assert again.status_code == 400 and again.json()["code"] == "invalid_token"
    assert (await ctx.login(email)).json()["status"] == "authenticated"


async def test_expired_verification_token_is_rejected(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.client.post(REGISTER, json=registration(email))
    token = ctx.last_token("/verify-email")
    await ctx.execute("UPDATE auth_tokens SET expires_at = now() - interval '1 minute'")

    response = await ctx.client.post("/api/v1/auth/verify-email", json={"token": token})
    assert response.status_code == 400


async def test_verification_token_lasts_twenty_four_hours(ctx: Ctx) -> None:
    await ctx.client.post(REGISTER, json=registration(unique_email()))
    [(hours,)] = await ctx.fetch(
        "SELECT round(extract(epoch FROM (expires_at - created_at)) / 3600) FROM auth_tokens"
    )
    assert hours == 24


async def test_unknown_verification_token_is_rejected(ctx: Ctx) -> None:
    response = await ctx.client.post("/api/v1/auth/verify-email", json={"token": "x" * 43})
    assert response.status_code == 400


async def test_login_before_verification_is_refused(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email, verified=False)
    response = await ctx.login(email)
    assert response.status_code == 403
    assert response.json()["code"] == "email_not_verified"


# --- login --------------------------------------------------------------------------


async def test_login_issues_access_token_and_secure_refresh_cookie(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    response = await ctx.login(email)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "authenticated" and body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60

    cookies = response.headers.get_list("set-cookie")
    refresh = next(c for c in cookies if c.startswith("refresh_token="))
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1/auth"):
        assert attribute.lower() in refresh.lower()
    csrf = next(c for c in cookies if c.startswith("csrf_token="))
    assert "httponly" not in csrf.lower()

    me = await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(body["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == email


async def test_refresh_token_is_stored_only_as_a_hash(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await ctx.login(email)
    raw = ctx.client.cookies.get("refresh_token")
    [(stored,)] = await ctx.fetch("SELECT token_hash FROM refresh_tokens")
    assert raw and stored != raw and len(str(stored)) == 64


async def test_wrong_password_and_unknown_email_give_the_same_response(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)

    wrong = await ctx.login(email, "not-the-right-password-1")
    unknown = await ctx.login(unique_email("nobody"), "not-the-right-password-1")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["message"] == unknown.json()["message"] == GENERIC
    assert wrong.json()["code"] == unknown.json()["code"] == "invalid_credentials"


async def test_unknown_email_still_performs_a_password_hash_verification(
    ctx: Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(ctx.passwords, "verify_dummy", lambda password: calls.append(password))
    await ctx.login(unique_email("ghost"), "whatever-password-1")
    assert calls == ["whatever-password-1"]


async def test_account_locks_after_five_failures_with_a_generic_message(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)

    for _ in range(5):
        response = await ctx.login(email, "wrong-password-value-1")
        assert response.json()["message"] == GENERIC

    # Even the correct password is refused while locked, with the same message.
    locked = await ctx.login(email)
    assert locked.status_code == 401
    assert locked.json()["message"] == GENERIC
    [(until,)] = await ctx.fetch("SELECT locked_until FROM users WHERE email = :e", e=email)
    assert timedelta(minutes=14) < until - datetime.now(UTC) <= timedelta(minutes=15)


async def test_lock_expires_and_success_resets_the_counter(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    for _ in range(5):
        await ctx.login(email, "wrong-password-value-1")
    await ctx.execute("UPDATE users SET locked_until = now() - interval '1 second'")

    assert (await ctx.login(email)).status_code == 200
    [(failed,)] = await ctx.fetch("SELECT failed_logins FROM users WHERE email = :e", e=email)
    assert failed == 0


async def test_failures_below_the_threshold_do_not_lock(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    for _ in range(4):
        await ctx.login(email, "wrong-password-value-1")
    assert (await ctx.login(email)).status_code == 200


async def test_deactivated_account_cannot_sign_in(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await ctx.execute("UPDATE users SET is_active = false")
    response = await ctx.login(email)
    assert response.status_code == 401 and response.json()["message"] == GENERIC


async def test_login_is_rate_limited_per_ip(ctx: Ctx) -> None:
    ctx.set_settings(rate_limit_login_per_minute=3)
    statuses = [
        (await ctx.login(unique_email("rl"), "whatever-password-1")).status_code for _ in range(5)
    ]
    assert statuses == [401, 401, 401, 429, 429]


async def test_login_is_rate_limited_per_account(ctx: Ctx) -> None:
    ctx.set_settings(rate_limit_login_per_minute=2)
    target = unique_email("victim")
    codes = []
    for _ in range(4):
        # Reset only the per IP counter so the per account counter is what trips.
        async for key in ctx.redis.scan_iter("rl:login:*"):
            if ":acct:" not in key:
                await ctx.redis.delete(key)
        codes.append((await ctx.login(target, "whatever-password-1")).status_code)
    assert codes == [401, 401, 429, 429]


async def test_rate_limit_response_has_retry_after_and_uniform_body(ctx: Ctx) -> None:
    ctx.set_settings(rate_limit_login_per_minute=1)
    await ctx.login(unique_email("a"), "whatever-password-1")
    blocked = await ctx.login(unique_email("b"), "whatever-password-1")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    assert set(blocked.json()) == {"code", "message", "details", "request_id"}


async def test_login_and_failures_are_audited_without_personal_data(ctx: Ctx) -> None:
    email = unique_email("audited")
    await ctx.create_user(email)
    await ctx.login(email, "wrong-password-value-1")
    await ctx.login(unique_email("ghost"), "wrong-password-value-1")
    await ctx.login(email)

    actions = [r[0] for r in await ctx.fetch("SELECT action FROM audit_logs ORDER BY created_at")]
    assert actions.count("auth.login_failed") == 2
    assert actions.count("auth.login") == 1
    dump = str(await ctx.fetch("SELECT metadata::text, ip::text FROM audit_logs"))
    assert "@example.com" not in dump and STRONG_PASSWORD not in dump


# --- password recovery and change ---------------------------------------------------


async def test_forgot_password_responds_identically_for_unknown_accounts(ctx: Ctx) -> None:
    known = unique_email()
    await ctx.create_user(known)
    a = await ctx.client.post("/api/v1/auth/forgot", json={"email": known})
    b = await ctx.client.post("/api/v1/auth/forgot", json={"email": unique_email("nobody")})

    assert a.status_code == b.status_code == 202
    assert a.json() == b.json()
    assert [m.to for m in ctx.mailer.outbox] == [known]


async def test_password_reset_flow_changes_password_and_revokes_sessions(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await ctx.login(email)
    await ctx.client.post("/api/v1/auth/forgot", json={"email": email})
    token = ctx.last_token("/reset-password")
    new_password = "a-brand-new-passphrase-42"

    reset = await ctx.client.post(
        "/api/v1/auth/reset", json={"token": token, "new_password": new_password}
    )
    assert reset.status_code == 200
    assert (await ctx.login(email, STRONG_PASSWORD)).status_code == 401
    assert (await ctx.login(email, new_password)).status_code == 200
    revoked = await ctx.fetch("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NOT NULL")
    assert revoked[0][0] >= 1


async def test_reset_token_is_single_use_and_stored_hashed(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await ctx.client.post("/api/v1/auth/forgot", json={"email": email})
    token = ctx.last_token("/reset-password")
    [(stored,)] = await ctx.fetch("SELECT token_hash FROM auth_tokens")
    assert stored != token

    payload = {"token": token, "new_password": "a-brand-new-passphrase-42"}
    assert (await ctx.client.post("/api/v1/auth/reset", json=payload)).status_code == 200
    assert (await ctx.client.post("/api/v1/auth/reset", json=payload)).status_code == 400


async def test_reset_token_expires_after_thirty_minutes(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await ctx.client.post("/api/v1/auth/forgot", json={"email": email})
    [(minutes,)] = await ctx.fetch(
        "SELECT round(extract(epoch FROM (expires_at - created_at)) / 60) FROM auth_tokens"
    )
    assert minutes == 30

    token = ctx.last_token("/reset-password")
    await ctx.execute("UPDATE auth_tokens SET expires_at = now() - interval '1 second'")
    response = await ctx.client.post(
        "/api/v1/auth/reset", json={"token": token, "new_password": "a-brand-new-passphrase-42"}
    )
    assert response.status_code == 400


async def test_new_reset_request_invalidates_the_previous_link(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await ctx.client.post("/api/v1/auth/forgot", json={"email": email})
    first = ctx.last_token("/reset-password")
    await ctx.client.post("/api/v1/auth/forgot", json={"email": email})

    response = await ctx.client.post(
        "/api/v1/auth/reset", json={"token": first, "new_password": "a-brand-new-passphrase-42"}
    )
    assert response.status_code == 400


async def test_reset_enforces_the_password_policy(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await ctx.client.post("/api/v1/auth/forgot", json={"email": email})
    response = await ctx.client.post(
        "/api/v1/auth/reset",
        json={"token": ctx.last_token("/reset-password"), "new_password": "passwordpassword"},
    )
    assert response.status_code == 422


async def test_change_password_requires_the_current_password(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    token = await ctx.access_token(email)
    headers = ctx.auth(token)

    bad = await ctx.client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={
            "current_password": "wrong-password-value-1",
            "new_password": "a-brand-new-passphrase-42",
        },
    )
    good = await ctx.client.post(
        "/api/v1/auth/password",
        headers=headers,
        json={"current_password": STRONG_PASSWORD, "new_password": "a-brand-new-passphrase-42"},
    )
    assert bad.status_code == 401
    assert good.status_code == 200
    actions = [r[0] for r in await ctx.fetch("SELECT action FROM audit_logs")]
    assert "auth.password_change" in actions


async def test_change_password_rejects_reuse_of_the_same_password(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    token = await ctx.access_token(email)
    response = await ctx.client.post(
        "/api/v1/auth/password",
        headers=ctx.auth(token),
        json={"current_password": STRONG_PASSWORD, "new_password": STRONG_PASSWORD},
    )
    assert response.status_code == 422


async def test_passwords_are_hashed_with_argon2id(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email, UserRole.RECEPTIONIST)
    [(stored,)] = await ctx.fetch("SELECT password_hash FROM users WHERE email = :e", e=email)
    assert str(stored).startswith("$argon2id$") and STRONG_PASSWORD not in str(stored)
