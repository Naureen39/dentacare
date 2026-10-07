import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 3.0


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe: the process is running."""
    return HealthResponse(status="ok")


async def _check_database(request: Request) -> str:
    try:
        async with request.app.state.engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        return "unavailable"


async def _check_redis(request: Request) -> str:
    try:
        await asyncio.wait_for(request.app.state.redis.ping(), CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        return "unavailable"


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(request: Request) -> JSONResponse:
    """Readiness probe: dependencies are reachable."""
    db, cache = await asyncio.gather(_check_database(request), _check_redis(request))
    checks = {"database": db, "redis": cache}
    healthy = all(v == "ok" for v in checks.values())
    body = ReadyResponse(status="ready" if healthy else "degraded", checks=checks)
    return JSONResponse(status_code=200 if healthy else 503, content=body.model_dump())
