"""Sweeps over every route the API declares, so a new route cannot quietly skip a safeguard.

* Every operation needs a signed in user unless it is on a short, reviewed list of public ones.
* Each role is refused the areas that belong to other roles, on every operation in them.
* Every request body rejects fields it does not declare, which is what stops mass assignment.
* A spoofed ``X-Forwarded-For`` header does not give a caller a fresh rate limit.
"""

import re
import uuid
from typing import Any

import pytest

from app.db.enums import UserRole
from tests.auth.conftest import Ctx, unique_email

API = "/api/v1"
ID = str(uuid.UUID(int=0))
TOKEN = "a" * 40

# Routes that are open to anyone by design. Adding a route here is a decision to make in review.
PUBLIC_PREFIXES = (
    "/health",
    "/ready",
    f"{API}/openapi.json",
    f"{API}/info",
    f"{API}/public/",
    f"{API}/chat/sessions",
    f"{API}/auth/register",
    f"{API}/auth/verify-email",
    f"{API}/auth/login",
    f"{API}/auth/mfa/verify",
    f"{API}/auth/refresh",
    f"{API}/auth/logout",
    f"{API}/auth/forgot",
    f"{API}/auth/reset",
)
METHODS = ("get", "post", "put", "patch", "delete")


def operations(ctx: Ctx) -> list[tuple[str, str, dict[str, Any]]]:
    spec = ctx.app.openapi()
    return [
        (method.upper(), path, op)
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in METHODS
    ]


def concrete(path: str) -> str:
    """The path with every parameter filled in with a value of the right shape."""
    return re.sub(
        r"\{([^}]+)\}",
        lambda m: TOKEN if "token" in m.group(1) else ID,
        path,
    )


def is_public(path: str) -> bool:
    return path.startswith(PUBLIC_PREFIXES)


async def call(ctx: Ctx, method: str, path: str, headers: dict[str, str] | None = None) -> int:
    response = await ctx.client.request(method, concrete(path), headers=headers, json={})
    return response.status_code


async def token_for(ctx: Ctx, role: UserRole) -> dict[str, str]:
    email = unique_email(role.value)
    await ctx.create_user(email, role)
    return ctx.auth(await ctx.access_token(email))


async def test_the_api_declares_a_meaningful_number_of_operations(ctx: Ctx) -> None:
    assert len(operations(ctx)) > 120


async def test_every_operation_needs_a_signed_in_user_unless_it_is_listed_public(ctx: Ctx) -> None:
    open_routes = []
    for method, path, _ in operations(ctx):
        if is_public(path) and not path.startswith(f"{API}/auth/"):
            continue
        status = await call(ctx, method, path)
        if is_public(path):  # the auth routes that are public still must not leak a 2xx
            assert status < 500 and status != 200, (method, path, status)
        elif status != 401:
            open_routes.append((method, path, status))
    assert open_routes == [], f"routes answering without a sign in: {open_routes}"


# Where each role must be refused, as route prefixes. A refusal is 403 (signed in, wrong role).
FORBIDDEN: dict[UserRole, tuple[str, ...]] = {
    UserRole.PATIENT: (
        f"{API}/admin/",
        f"{API}/staff/",
        f"{API}/billing/",
        f"{API}/analytics/",
        f"{API}/patients",
    ),
    UserRole.RECEPTIONIST: (f"{API}/admin/", f"{API}/me/", f"{API}/analytics/refresh"),
    UserRole.DENTIST: (
        f"{API}/admin/",
        f"{API}/billing/",
        f"{API}/me/",
        f"{API}/analytics/refresh",
        f"{API}/staff/alerts",
    ),
}


@pytest.mark.parametrize("role", list(FORBIDDEN))
async def test_each_role_is_refused_the_areas_of_other_roles(ctx: Ctx, role: UserRole) -> None:
    headers = await token_for(ctx, role)
    leaks = []
    for method, path, _ in operations(ctx):
        if not path.startswith(FORBIDDEN[role]):
            continue
        # A dentist may read the invoices of their own appointments (docs/billing.md), but never
        # change billing.
        if role is UserRole.DENTIST and path.startswith(f"{API}/billing/") and method == "GET":
            continue
        status = await call(ctx, method, path, headers)
        if status != 403:
            leaks.append((method, path, status))
    assert leaks == [], f"{role.value} was not refused: {leaks}"


async def test_a_receptionist_cannot_create_accounts_or_change_roles(ctx: Ctx) -> None:
    headers = await token_for(ctx, UserRole.RECEPTIONIST)
    for method, path in [
        ("POST", f"{API}/admin/users"),
        ("PATCH", f"{API}/admin/users/{ID}/role"),
        ("PUT", f"{API}/admin/settings"),
    ]:
        assert await call(ctx, method, path, headers) == 403


def schema_of(spec: dict[str, Any], node: dict[str, Any]) -> list[dict[str, Any]]:
    """The object schemas a request body can take, with references followed."""
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return schema_of(spec, spec["components"]["schemas"][name])
    if "anyOf" in node or "oneOf" in node:
        return [
            s for part in node.get("anyOf", node.get("oneOf", [])) for s in schema_of(spec, part)
        ]
    return [node]


async def test_every_request_body_rejects_fields_it_does_not_declare(ctx: Ctx) -> None:
    spec = ctx.app.openapi()
    open_bodies = []
    for method, path, op in operations(ctx):
        content = op.get("requestBody", {}).get("content", {})
        if "application/json" not in content:
            continue
        for schema in schema_of(spec, content["application/json"]["schema"]):
            if schema.get("type") == "object" and schema.get("additionalProperties") is not False:
                open_bodies.append((method, path, schema.get("title")))
    assert open_bodies == [], f"bodies that accept unknown fields: {open_bodies}"


async def test_a_spoofed_forwarded_for_header_does_not_reset_the_login_limit(ctx: Ctx) -> None:
    ctx.set_settings(rate_limit_login_per_minute=3, rate_limit_account_email_per_hour=1000)
    statuses = []
    for n in range(6):
        response = await ctx.client.post(
            f"{API}/auth/login",
            json={"email": f"nobody{n}@example.com", "password": "wrong-password-123"},
            headers={"X-Forwarded-For": f"203.0.113.{n}", "X-Real-IP": f"198.51.100.{n}"},
        )
        statuses.append(response.status_code)
    assert statuses[:3] == [401, 401, 401]
    assert 429 in statuses[3:], statuses


async def test_errors_never_reveal_internals(ctx: Ctx) -> None:
    for path in (f"{API}/no-such-route", f"{API}/patients/not-a-uuid"):
        response = await ctx.client.get(path)
        body = response.text.lower()
        assert "traceback" not in body and "sqlalchemy" not in body and "psycopg" not in body
        assert response.status_code in (401, 404, 422)
        assert response.json()["code"]
