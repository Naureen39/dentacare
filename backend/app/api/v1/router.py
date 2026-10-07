from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.config import Settings

router = APIRouter()


class InfoResponse(BaseModel):
    name: str
    version: str
    environment: str


@router.get("/info", response_model=InfoResponse, tags=["meta"])
async def info(request: Request) -> InfoResponse:
    """Basic service metadata, also used to exercise the generated API client."""
    settings: Settings = request.app.state.settings
    return InfoResponse(name=settings.clinic_name, version="0.1.0", environment=settings.env)
