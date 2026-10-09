from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.v1 import (
    admin_console,
    analytics,
    auth,
    billing,
    chat,
    knowledge,
    llm,
    portal,
    public,
    records,
    staff,
    staff_work,
)
from app.core.config import Settings

router = APIRouter()
router.include_router(auth.router)
router.include_router(records.router)
router.include_router(public.router)
router.include_router(portal.router)
router.include_router(staff.router)
router.include_router(staff_work.router)
router.include_router(admin_console.router)
router.include_router(billing.router)
router.include_router(knowledge.router)
router.include_router(llm.router)
router.include_router(chat.router)
router.include_router(chat.admin_router)
router.include_router(analytics.router)


class InfoResponse(BaseModel):
    name: str
    version: str
    environment: str


@router.get("/info", response_model=InfoResponse, tags=["meta"])
async def info(request: Request) -> InfoResponse:
    """Basic service metadata, also used to exercise the generated API client."""
    settings: Settings = request.app.state.settings
    return InfoResponse(name=settings.clinic_name, version="0.1.0", environment=settings.env)
