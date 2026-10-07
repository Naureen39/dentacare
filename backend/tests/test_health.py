from httpx import AsyncClient

from app.main import create_app


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_request_id_is_generated_and_echoed(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert len(response.headers["X-Request-ID"]) >= 8

    custom = await client.get("/health", headers={"X-Request-ID": "trace-12345678"})
    assert custom.headers["X-Request-ID"] == "trace-12345678"


async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "bad id!\t"})
    assert response.headers["X-Request-ID"] != "bad id!\t"


async def test_ready_reports_degraded_when_dependencies_are_down(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "unavailable"
    assert body["checks"]["redis"] == "ok"


async def test_unknown_route_uses_uniform_error_format(client: AsyncClient) -> None:
    response = await client.get("/api/v1/missing")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "details", "request_id"}
    assert body["code"] == "not_found"
    assert body["request_id"] == response.headers["X-Request-ID"]


async def test_unhandled_exception_uses_uniform_error_format(settings) -> None:  # type: ignore[no-untyped-def]
    from httpx import ASGITransport

    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert "secret" not in body["message"]
    assert body["request_id"]


async def test_info_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/info")
    assert response.status_code == 200
    assert response.json()["environment"] == "test"


async def test_openapi_schema_is_served(client: AsyncClient) -> None:
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
