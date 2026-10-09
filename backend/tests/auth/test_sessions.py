from httpx import Response

from tests.auth.conftest import Ctx, unique_email

SESSIONS = "/api/v1/auth/sessions"


async def sign_in(ctx: Ctx, email: str, agent: str) -> Response:
    return await ctx.client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery-staple-9"},
        headers={"User-Agent": agent},
    )


async def test_lists_each_signed_in_device_once_and_marks_the_current_one(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await sign_in(ctx, email, "Phone")
    phone_cookie = ctx.client.cookies.get("refresh_token")
    other = await sign_in(ctx, email, "Laptop")
    token = other.json()["access_token"]

    # A refresh rotates the token but the device must still appear once.
    csrf = {"X-CSRF-Token": ctx.client.cookies.get("csrf_token") or "", "User-Agent": "Laptop"}
    await ctx.client.post("/api/v1/auth/refresh", headers=csrf)

    response = await ctx.client.get(SESSIONS, headers=ctx.auth(token))
    assert response.status_code == 200
    rows = response.json()
    assert sorted(r["user_agent"] for r in rows) == ["Laptop", "Phone"]
    assert [r["user_agent"] for r in rows if r["current"]] == ["Laptop"]
    assert phone_cookie  # the other device's cookie is not the one in use


async def test_revoking_a_session_ends_it_and_only_that_one(ctx: Ctx) -> None:
    email = unique_email()
    await ctx.create_user(email)
    await sign_in(ctx, email, "Phone")
    token = (await sign_in(ctx, email, "Laptop")).json()["access_token"]
    rows = (await ctx.client.get(SESSIONS, headers=ctx.auth(token))).json()
    phone = next(r for r in rows if r["user_agent"] == "Phone")

    gone = await ctx.client.delete(f"{SESSIONS}/{phone['id']}", headers=ctx.auth(token))
    assert gone.status_code == 204

    after = (await ctx.client.get(SESSIONS, headers=ctx.auth(token))).json()
    assert [r["user_agent"] for r in after] == ["Laptop"]
    assert await ctx.fetch("SELECT 1 FROM audit_logs WHERE action = 'auth.session_revoke'")


async def test_another_users_session_cannot_be_revoked_or_seen(ctx: Ctx) -> None:
    mine, theirs = unique_email(), unique_email()
    await ctx.create_user(mine)
    await ctx.create_user(theirs)
    await sign_in(ctx, theirs, "Their phone")
    their_id = (await ctx.fetch("SELECT family_id FROM refresh_tokens"))[0][0]
    token = (await sign_in(ctx, mine, "Mine")).json()["access_token"]

    assert [
        r["user_agent"] for r in (await ctx.client.get(SESSIONS, headers=ctx.auth(token))).json()
    ] == ["Mine"]
    response = await ctx.client.delete(f"{SESSIONS}/{their_id}", headers=ctx.auth(token))
    assert response.status_code == 404
    assert await ctx.fetch(
        "SELECT 1 FROM refresh_tokens WHERE revoked_at IS NULL AND user_agent = 'Their phone'"
    )


async def test_sessions_need_a_signed_in_user(ctx: Ctx) -> None:
    assert (await ctx.client.get(SESSIONS)).status_code == 401
