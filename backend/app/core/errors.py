from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


class ErrorResponse(BaseModel):
    """Uniform error body returned by every failing endpoint."""

    code: str
    message: str
    details: Any = None
    request_id: str | None = None


class AppError(Exception):
    """Domain error that maps to a uniform error response."""

    def __init__(
        self, code: str, message: str, status_code: int = 400, details: Any = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
}


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _response(
    request: Request, status_code: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    body = ErrorResponse(
        code=code, message=message, details=details, request_id=_request_id(request)
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        return _response(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return _response(request, 422, "validation_error", "The request is invalid.", details)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", error_type=type(exc).__name__, exc_info=exc)
        return _response(
            request, 500, "internal_error", "An unexpected error occurred. Please try again."
        )
