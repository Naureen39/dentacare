from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api import health
from app.api.v1.router import router as v1_router
from app.core.config import Settings, get_settings
from app.core.crypto import FieldCipher
from app.core.errors import ErrorResponse, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.core.security import PasswordService
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.session import create_engine, create_session_factory
from app.services.mailer import SmtpMailer
from app.services.queue import ArqJobQueue

logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(cfg)
        redis = Redis.from_url(cfg.redis_url, decode_responses=True)
        app.state.settings = cfg
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.redis = redis
        app.state.cipher = FieldCipher.from_settings(
            cfg.field_encryption_key, cfg.field_encryption_old_keys, cfg.jwt_secret
        )
        app.state.passwords = PasswordService(cfg)
        app.state.mailer = SmtpMailer(cfg)
        app.state.jobs = ArqJobQueue(cfg.redis_url)
        logger.info("startup_complete", env=cfg.env)
        try:
            yield
        finally:
            await app.state.jobs.close()
            await redis.aclose()
            await engine.dispose()
            logger.info("shutdown_complete")

    app = FastAPI(
        title=f"{cfg.clinic_name} API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if cfg.is_production else "/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
        responses={
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
        },
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=cfg.is_production)
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(v1_router, prefix="/api/v1")
    return app


app = create_app()
