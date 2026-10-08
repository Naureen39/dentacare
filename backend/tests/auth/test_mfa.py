import uuid
from datetime import timedelta

import pyotp

from app.core.security import create_jwt
from app.db.enums import UserRole
from tests.auth.conftest import STRONG_PASSWORD, Ctx, unique_email

SETUP = "/api/v1/auth/mfa/setup"
ENABLE = "/api/v1/auth/mfa/enable"
VERIFY = "/api/v1/auth/mfa/verify"


async def enrolled_admin(ctx: Ctx, role: UserRole = UserRole.ADMIN) -> tuple[str, str, list[str]]:
    """Create a staff user and complete the mandatory enrolment. Returns email, secret, codes."""
    email = unique_email(role.value)
    await ctx.create_user(email, role)
    first = (await ctx.login(email)).json()
    assert first["status"] == "mfa_setup_required"
    result = await ctx.enrol_mfa(first["mfa_token"])
    return email, str(result["secret"]), list(result["recovery_codes"])


async def mfa_login(ctx: Ctx, email: str) -> str:
    response = await ctx.login(email)
    body = response.json()
    assert body["status"] == "mfa_required", body
    return str(body["mfa_token"])


# --- mandatory roles ----------------------------------------------------------------


async def test_admin_and_dentist_must_enrol_before_getting_a_session(ctx: Ctx) -> None:
    for role in (UserRole.ADMIN, UserRole.DENTIST):
        email = unique_email(role.value)
        await ctx.create_user(email, role)
        response = await ctx.login(email)
        body = response.json()
        assert body["status"] == "mfa_setup_required"
        assert "access_token" not in body
        assert "refresh_token" not in response.headers.get("set-cookie", "")


async def test_enrolment_completes_the_sign_in_and_returns_eight_recovery_codes(ctx: Ctx) -> None:
    email = unique_email("admin")
    await ctx.create_user(email, UserRole.ADMIN)
    token = (await ctx.login(email)).json()["mfa_token"]
    headers = ctx.auth(token)

    setup = await ctx.client.post(SETUP, headers=headers)
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    enable = await ctx.client.post(ENABLE, headers=headers, json={"code": pyotp.TOTP(secret).now()})

    body = enable.json()
    assert enable.status_code == 200
    assert body["status"] == "authenticated" and body["access_token"]
    assert len(body["recovery_codes"]) == 8
    me = await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(body["access_token"]))
    assert me.json()["mfa_enabled"] is True


async def test_totp_secret_and_recovery_codes_are_not_stored_in_plaintext(ctx: Ctx) -> None:
    email, secret, codes = await enrolled_admin(ctx)
    [(stored,)] = await ctx.fetch("SELECT mfa_secret_enc FROM users WHERE email = :e", e=email)
    assert secret not in str(stored)
    hashes = [r[0] for r in await ctx.fetch("SELECT code_hash FROM mfa_recovery_codes")]
    assert len(hashes) == 8
    assert all(str(h).startswith("$argon2id$") for h in hashes)
    assert not any(code.replace("-", "") in str(h) for code in codes for h in hashes)


async def test_enrolment_rejects_a_wrong_code(ctx: Ctx) -> None:
    email = unique_email("admin")
    await ctx.create_user(email, UserRole.ADMIN)
    headers = ctx.auth((await ctx.login(email)).json()["mfa_token"])
    await ctx.client.post(SETUP, headers=headers)

    response = await ctx.client.post(ENABLE, headers=headers, json={"code": "000000"})
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_mfa_code"


async def test_enable_without_setup_is_rejected(ctx: Ctx) -> None:
    email = unique_email("admin")
    await ctx.create_user(email, UserRole.ADMIN)
    headers = ctx.auth((await ctx.login(email)).json()["mfa_token"])
    response = await ctx.client.post(ENABLE, headers=headers, json={"code": "123456"})
    assert response.status_code == 409


async def test_staff_cannot_disable_mandatory_mfa(ctx: Ctx) -> None:
    email, secret, _ = await enrolled_admin(ctx)
    await ctx.clear_totp_replay_keys()
    token = await mfa_login(ctx, email)
    session = await ctx.client.post(
        VERIFY, json={"mfa_token": token, "code": pyotp.TOTP(secret).now()}
    )
    access = session.json()["access_token"]
    await ctx.clear_totp_replay_keys()

    response = await ctx.client.post(
        "/api/v1/auth/mfa/disable",
        headers=ctx.auth(access),
        json={"password": STRONG_PASSWORD, "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 403 and response.json()["code"] == "mfa_mandatory"


async def test_access_token_without_mfa_claim_is_refused_for_mandatory_roles(ctx: Ctx) -> None:
    email = unique_email("admin")
    user = await ctx.create_user(email, UserRole.ADMIN)
    forged = create_jwt(
        ctx.settings,
        user_id=user.id,
        role="admin",
        token_type="access",
        mfa=False,
        lifetime=timedelta(minutes=5),
    )
    response = await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(forged))
    assert response.status_code == 403 and response.json()["code"] == "mfa_required"


# --- login with MFA -----------------------------------------------------------------


async def test_login_with_totp_code(ctx: Ctx) -> None:
    email, secret, _ = await enrolled_admin(ctx)
    await ctx.clear_totp_replay_keys()
    token = await mfa_login(ctx, email)

    response = await ctx.client.post(
        VERIFY, json={"mfa_token": token, "code": pyotp.TOTP(secret).now()}
    )
    assert response.status_code == 200
    assert response.json()["access_token"]
    assert "refresh_token=" in response.headers["set-cookie"] or ctx.client.cookies.get(
        "refresh_token"
    )


async def test_wrong_totp_code_is_rejected_and_counts_towards_lockout(ctx: Ctx) -> None:
    email, _, _ = await enrolled_admin(ctx)
    token = await mfa_login(ctx, email)

    for _ in range(5):
        response = await ctx.client.post(VERIFY, json={"mfa_token": token, "code": "000000"})
        assert response.status_code == 401
    [(locked,)] = await ctx.fetch(
        "SELECT locked_until IS NOT NULL FROM users WHERE email = :e", e=email
    )
    assert locked is True


async def test_a_totp_code_cannot_be_replayed(ctx: Ctx) -> None:
    email, secret, _ = await enrolled_admin(ctx)
    await ctx.clear_totp_replay_keys()
    code = pyotp.TOTP(secret).now()

    first = await ctx.client.post(
        VERIFY, json={"mfa_token": await mfa_login(ctx, email), "code": code}
    )
    second = await ctx.client.post(
        VERIFY, json={"mfa_token": await mfa_login(ctx, email), "code": code}
    )
    assert first.status_code == 200
    assert second.status_code == 401


async def test_recovery_code_works_once(ctx: Ctx) -> None:
    email, _, codes = await enrolled_admin(ctx)

    first = await ctx.client.post(
        VERIFY, json={"mfa_token": await mfa_login(ctx, email), "recovery_code": codes[0]}
    )
    again = await ctx.client.post(
        VERIFY, json={"mfa_token": await mfa_login(ctx, email), "recovery_code": codes[0]}
    )
    other = await ctx.client.post(
        VERIFY, json={"mfa_token": await mfa_login(ctx, email), "recovery_code": codes[1].upper()}
    )
    assert first.status_code == 200
    assert again.status_code == 401
    assert other.status_code == 200
    used = await ctx.fetch("SELECT count(*) FROM mfa_recovery_codes WHERE used_at IS NOT NULL")
    assert used == [(2,)]


async def test_verify_requires_exactly_one_of_code_or_recovery_code(ctx: Ctx) -> None:
    email, _, _ = await enrolled_admin(ctx)
    token = await mfa_login(ctx, email)
    neither = await ctx.client.post(VERIFY, json={"mfa_token": token})
    both = await ctx.client.post(
        VERIFY, json={"mfa_token": token, "code": "123456", "recovery_code": "abcde-fghjk"}
    )
    assert neither.status_code == both.status_code == 422


# --- token separation ---------------------------------------------------------------


async def test_challenge_and_setup_tokens_cannot_be_used_as_access_tokens(ctx: Ctx) -> None:
    email, _, _ = await enrolled_admin(ctx)
    challenge = await mfa_login(ctx, email)
    response = await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(challenge))
    assert response.status_code == 401

    other = unique_email("admin2")
    await ctx.create_user(other, UserRole.ADMIN)
    setup_token = (await ctx.login(other)).json()["mfa_token"]
    assert (
        await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(setup_token))
    ).status_code == 401
    assert (
        await ctx.client.get("/api/v1/patients", headers=ctx.auth(setup_token))
    ).status_code == 401


async def test_access_tokens_cannot_be_used_as_mfa_challenge(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    access = await ctx.access_token(email)
    response = await ctx.client.post(VERIFY, json={"mfa_token": access, "code": "123456"})
    assert response.status_code == 401


async def test_mfa_token_for_unknown_user_is_rejected(ctx: Ctx) -> None:
    ghost = create_jwt(
        ctx.settings,
        user_id=uuid.uuid4(),
        role="admin",
        token_type="mfa_challenge",
        mfa=False,
        lifetime=timedelta(minutes=5),
    )
    response = await ctx.client.post(VERIFY, json={"mfa_token": ghost, "code": "123456"})
    assert response.status_code == 401


# --- optional MFA for other roles ---------------------------------------------------


async def test_patient_can_enable_and_disable_mfa(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    access = await ctx.access_token(email)
    headers = ctx.auth(access)

    secret = (await ctx.client.post(SETUP, headers=headers)).json()["secret"]
    enable = await ctx.client.post(ENABLE, headers=headers, json={"code": pyotp.TOTP(secret).now()})
    assert enable.status_code == 200 and len(enable.json()["recovery_codes"]) == 8

    # From now on a password alone is not enough.
    assert (await ctx.login(email)).json()["status"] == "mfa_required"

    await ctx.clear_totp_replay_keys()
    disable = await ctx.client.post(
        "/api/v1/auth/mfa/disable",
        headers=headers,
        json={"password": STRONG_PASSWORD, "code": pyotp.TOTP(secret).now()},
    )
    assert disable.status_code == 200
    assert (await ctx.login(email)).json()["status"] == "authenticated"
    assert await ctx.fetch("SELECT count(*) FROM mfa_recovery_codes") == [(0,)]


async def test_disabling_mfa_needs_password_and_code(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    headers = ctx.auth(await ctx.access_token(email))
    secret = (await ctx.client.post(SETUP, headers=headers)).json()["secret"]
    await ctx.client.post(ENABLE, headers=headers, json={"code": pyotp.TOTP(secret).now()})
    await ctx.clear_totp_replay_keys()

    response = await ctx.client.post(
        "/api/v1/auth/mfa/disable",
        headers=headers,
        json={"password": "wrong-password-value-1", "code": pyotp.TOTP(secret).now()},
    )
    assert response.status_code == 401
