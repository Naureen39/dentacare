from httpx import Response

from tests.auth.conftest import Ctx, unique_email

REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


async def signed_in(ctx: Ctx) -> tuple[str, Response]:
    email = unique_email()
    await ctx.create_user(email)
    response = await ctx.login(email)
    return email, response


def put_cookie(ctx: Ctx, name: str, value: str | None, path: str) -> None:
    """Replace a cookie in the client jar, avoiding duplicates from different domains."""
    ctx.client.cookies.delete(name)
    if value is not None:
        ctx.client.cookies.set(name, value, domain="test.local", path=path)


def csrf_headers(ctx: Ctx) -> dict[str, str]:
    return {"X-CSRF-Token": ctx.client.cookies.get("csrf_token") or ""}


async def test_refresh_rotates_the_token_and_returns_a_new_access_token(ctx: Ctx) -> None:
    await signed_in(ctx)
    old_refresh = ctx.client.cookies.get("refresh_token")

    response = await ctx.client.post(REFRESH, headers=csrf_headers(ctx))

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert ctx.client.cookies.get("refresh_token") != old_refresh
    rows = await ctx.fetch(
        "SELECT revoked_at IS NOT NULL, replaced_by IS NOT NULL FROM refresh_tokens ORDER BY created_at"
    )
    assert rows == [(True, True), (False, False)]
    families = await ctx.fetch("SELECT count(DISTINCT family_id) FROM refresh_tokens")
    assert families == [(1,)]


async def test_new_access_token_works_after_refresh(ctx: Ctx) -> None:
    await signed_in(ctx)
    token = (await ctx.client.post(REFRESH, headers=csrf_headers(ctx))).json()["access_token"]
    assert (await ctx.client.get("/api/v1/auth/me", headers=ctx.auth(token))).status_code == 200


async def test_reusing_a_rotated_token_revokes_the_whole_family(ctx: Ctx) -> None:
    await signed_in(ctx)
    stolen = ctx.client.cookies.get("refresh_token")
    await ctx.client.post(REFRESH, headers=csrf_headers(ctx))  # legitimate rotation
    legitimate_new = ctx.client.cookies.get("refresh_token")

    # An attacker replays the old token.
    put_cookie(ctx, "refresh_token", stolen, "/api/v1/auth")
    replay = await ctx.client.post(REFRESH, headers=csrf_headers(ctx))
    assert replay.status_code == 401
    assert replay.json()["code"] == "session_revoked"

    # The legitimate holder of the newest token is signed out as well.
    put_cookie(ctx, "refresh_token", legitimate_new, "/api/v1/auth")
    after = await ctx.client.post(REFRESH, headers=csrf_headers(ctx))
    assert after.status_code == 401
    assert await ctx.fetch("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL") == [(0,)]
    actions = [r[0] for r in await ctx.fetch("SELECT action FROM audit_logs")]
    assert "auth.refresh_token_reuse" in actions


async def test_other_families_are_not_affected_by_reuse_detection(ctx: Ctx) -> None:
    email, _ = await signed_in(ctx)
    first_family_token = ctx.client.cookies.get("refresh_token")
    await ctx.client.post(REFRESH, headers=csrf_headers(ctx))
    await ctx.login(email)  # second device, new family
    second_device = ctx.client.cookies.get("refresh_token")

    put_cookie(ctx, "refresh_token", first_family_token, "/api/v1/auth")
    await ctx.client.post(REFRESH, headers=csrf_headers(ctx))  # reuse in family one

    put_cookie(ctx, "refresh_token", second_device, "/api/v1/auth")
    assert (await ctx.client.post(REFRESH, headers=csrf_headers(ctx))).status_code == 200


async def test_refresh_requires_csrf_header(ctx: Ctx) -> None:
    await signed_in(ctx)
    missing = await ctx.client.post(REFRESH)
    wrong = await ctx.client.post(REFRESH, headers={"X-CSRF-Token": "not-the-token"})
    assert missing.status_code == wrong.status_code == 403
    assert missing.json()["code"] == "csrf_failed"


async def test_refresh_rejects_a_foreign_origin(ctx: Ctx) -> None:
    await signed_in(ctx)
    response = await ctx.client.post(
        REFRESH, headers={**csrf_headers(ctx), "Origin": "https://evil.example"}
    )
    assert response.status_code == 403


async def test_refresh_accepts_an_allowed_origin(ctx: Ctx) -> None:
    await signed_in(ctx)
    response = await ctx.client.post(
        REFRESH, headers={**csrf_headers(ctx), "Origin": "http://localhost:5173"}
    )
    assert response.status_code == 200


async def test_refresh_without_a_cookie_is_unauthorized(ctx: Ctx) -> None:
    put_cookie(ctx, "refresh_token", None, "/api/v1/auth")
    put_cookie(ctx, "csrf_token", "abc", "/")
    response = await ctx.client.post(REFRESH, headers={"X-CSRF-Token": "abc"})
    assert response.status_code == 401


async def test_expired_refresh_token_is_rejected(ctx: Ctx) -> None:
    await signed_in(ctx)
    await ctx.execute("UPDATE refresh_tokens SET expires_at = now() - interval '1 second'")
    assert (await ctx.client.post(REFRESH, headers=csrf_headers(ctx))).status_code == 401


async def test_refresh_token_lifetime_is_fourteen_days(ctx: Ctx) -> None:
    await signed_in(ctx)
    [(days,)] = await ctx.fetch(
        "SELECT round(extract(epoch FROM (expires_at - created_at)) / 86400) FROM refresh_tokens"
    )
    assert days == 14


async def test_deactivated_user_cannot_refresh(ctx: Ctx) -> None:
    await signed_in(ctx)
    await ctx.execute("UPDATE users SET is_active = false")
    assert (await ctx.client.post(REFRESH, headers=csrf_headers(ctx))).status_code == 401


async def test_logout_revokes_the_session_and_clears_cookies(ctx: Ctx) -> None:
    await signed_in(ctx)
    token = ctx.client.cookies.get("refresh_token")

    response = await ctx.client.post(LOGOUT, headers=csrf_headers(ctx))
    assert response.status_code == 204
    assert await ctx.fetch("SELECT count(*) FROM refresh_tokens WHERE revoked_at IS NULL") == [(0,)]

    put_cookie(ctx, "refresh_token", token, "/api/v1/auth")
    put_cookie(ctx, "csrf_token", "abc", "/")
    assert (await ctx.client.post(REFRESH, headers={"X-CSRF-Token": "abc"})).status_code == 401


async def test_logout_requires_csrf(ctx: Ctx) -> None:
    await signed_in(ctx)
    assert (await ctx.client.post(LOGOUT)).status_code == 403
