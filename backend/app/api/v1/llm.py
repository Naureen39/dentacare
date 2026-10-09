"""Administration of the LLM gateway: status, provider order, limits and usage."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert

from app.chat.llm_gateway import LlmGateway
from app.core.deps import CurrentUser, Session, require_roles
from app.core.errors import AppError
from app.db.enums import UserRole
from app.db.models import AppSetting, LlmUsage
from app.schemas.llm import LimitsRequest, PrimaryRequest, ProviderUsageRow, UsageSummary
from app.services import audit

router = APIRouter(prefix="/admin/llm", tags=["llm"])

AdminUser = Annotated[CurrentUser, Depends(require_roles(UserRole.ADMIN))]


def get_gateway(request: Request) -> LlmGateway:
    gateway: LlmGateway | None = getattr(request.app.state, "llm", None)
    if gateway is None:
        raise AppError("llm_unavailable", "The language model gateway is not configured.", 503)
    return gateway


Gateway = Annotated[LlmGateway, Depends(get_gateway)]


async def _put_setting(db: Session, key: str, value: Any, user: CurrentUser) -> None:
    statement = insert(AppSetting).values(key=key, value=value, updated_by=user.id)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={
                "value": statement.excluded.value,
                "updated_by": user.id,
                "updated_at": func.now(),
            },
        )
    )


@router.get("/status")
async def llm_status(_: AdminUser, gateway: Gateway) -> dict[str, Any]:
    """Provider order, circuit breaker state, cooldowns and how much of each limit is used."""
    return await gateway.status()


@router.put("/primary")
async def set_primary(
    body: PrimaryRequest, request: Request, db: Session, current: AdminUser, gateway: Gateway
) -> dict[str, str]:
    """Choose which provider is tried first. The other one remains the fallback."""
    await _put_setting(db, "llm_primary", body.provider, current)
    await audit.record(
        db,
        "llm.set_primary",
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="app_setting",
        entity_id="llm_primary",
        metadata={"provider": body.provider},
    )
    await db.commit()
    gateway.invalidate_config()
    return {"primary": body.provider}


@router.put("/limits/{provider}")
async def set_limits(
    provider: str,
    body: LimitsRequest,
    request: Request,
    db: Session,
    current: AdminUser,
    gateway: Gateway,
) -> dict[str, int | None]:
    """Store a provider's published limits, for example Gemini's from Google AI Studio."""
    if provider not in ("groq", "gemini"):
        raise AppError("not_found", "Unknown provider.", 404)
    values = body.model_dump()
    for metric, value in values.items():
        await _put_setting(db, f"{provider}_{metric}", value, current)
    await audit.record(
        db,
        "llm.set_limits",
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="app_setting",
        entity_id=provider,
        metadata={"provider": provider, **{k: v for k, v in values.items()}},
    )
    await db.commit()
    gateway.invalidate_config()
    return values


@router.get("/usage", response_model=UsageSummary)
async def usage(
    _: AdminUser, db: Session, hours: Annotated[int, Query(ge=1, le=24 * 31)] = 24
) -> UsageSummary:
    """Calls, tokens, latency and failovers per provider and outcome."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        await db.execute(
            select(
                LlmUsage.provider,
                LlmUsage.status,
                func.count(),
                func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
                func.coalesce(func.sum(LlmUsage.cached_tokens), 0),
                func.coalesce(func.avg(LlmUsage.latency_ms), 0),
                func.coalesce(func.sum(case((LlmUsage.fallback_from.is_not(None), 1), else_=0)), 0),
            )
            .where(LlmUsage.created_at >= since)
            .group_by(LlmUsage.provider, LlmUsage.status)
            .order_by(LlmUsage.provider, LlmUsage.status)
        )
    ).all()
    return UsageSummary(
        hours=hours,
        rows=[
            ProviderUsageRow(
                provider=r[0],
                status=r[1],
                calls=int(r[2]),
                prompt_tokens=int(r[3]),
                completion_tokens=int(r[4]),
                cached_tokens=int(r[5]),
                average_latency_ms=int(r[6]),
                failovers=int(r[7]),
            )
            for r in rows
        ],
    )
