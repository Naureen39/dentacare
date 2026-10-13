"""Contract tests: the running API answers in the shape its OpenAPI document promises.

Every read operation that needs nothing but a signed in administrator is called against the
seeded database and its JSON is validated against the declared response schema. Error answers are
validated against the shared error schema. The document itself must be valid OpenAPI.
"""

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate

from tests.analytics.conftest import AS_OF
from tests.analytics.helpers import RANGES, Api, span
from tests.auth.conftest import Ctx


def response_schema(
    spec: dict[str, Any], op: dict[str, Any], status: str = "200"
) -> dict[str, Any] | None:
    content = op.get("responses", {}).get(status, {}).get("content", {})
    if "application/json" not in content:
        return None
    return {"components": spec["components"], **content["application/json"]["schema"]}


def readable_operations(ctx: Ctx) -> list[tuple[str, dict[str, Any]]]:
    """GET operations with no path parameters and no required query parameters."""
    spec = ctx.app.openapi()
    found = []
    for path, item in spec["paths"].items():
        op = item.get("get")
        if op is None or "{" in path:
            continue
        if any(p.get("required") and p["in"] == "query" for p in op.get("parameters", [])):
            continue
        if response_schema(spec, op) is None:
            continue
        found.append((path, op))
    return found


def test_the_openapi_document_is_valid(ctx: Ctx) -> None:
    validate(ctx.app.openapi())


async def test_every_readable_endpoint_answers_in_its_declared_shape(ctx: Ctx, admin: Api) -> None:
    spec = ctx.app.openapi()
    operations = readable_operations(ctx)
    assert len(operations) > 30
    problems: list[str] = []
    checked = 0
    for path, op in operations:
        if path in ("/health", "/ready"):
            continue
        response = await ctx.client.get(
            path, params={"as_of": AS_OF.isoformat(), **span(*RANGES[1])}, headers=admin.headers
        )
        if response.status_code in (403, 404, 503):  # another role's area, no data yet, or off
            continue
        if response.status_code != 200:
            problems.append(f"{path}: {response.status_code} {response.text[:120]}")
            continue
        if "json" not in response.headers.get("content-type", ""):
            continue  # a file download that declares its own media type
        errors = sorted(
            Draft202012Validator(response_schema(spec, op) or {}).iter_errors(response.json()),
            key=lambda e: list(e.path),
        )
        if errors:
            problems.append(f"{path}: {errors[0].message[:160]} at {list(errors[0].path)}")
        checked += 1
    assert problems == [], problems
    assert checked > 25


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/v1/auth/me", 401),
        ("GET", "/api/v1/admin/users", 401),
        ("GET", "/api/v1/public/appointment-actions/" + "x" * 30, 404),
        ("GET", "/api/v1/patients/not-a-uuid", 401),
        ("POST", "/api/v1/auth/login", 422),
    ],
)
async def test_error_answers_share_one_shape(
    ctx: Ctx, method: str, path: str, expected: int
) -> None:
    response = await ctx.client.request(method, path, json={})
    assert response.status_code == expected
    body = response.json()
    error_schema = {
        "components": ctx.app.openapi()["components"],
        "$ref": "#/components/schemas/ErrorResponse",
    }
    assert list(Draft202012Validator(error_schema).iter_errors(body)) == []
    assert response.headers["X-Request-ID"] == body["request_id"]
    json.dumps(body)  # serialisable, no stray objects


def test_the_committed_openapi_file_matches_the_running_api(ctx: Ctx) -> None:
    """The frontend's types are generated from frontend/openapi.json, so it must not drift."""
    from pathlib import Path

    committed = json.loads(Path("../frontend/openapi.json").read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(ctx.app.openapi()))
