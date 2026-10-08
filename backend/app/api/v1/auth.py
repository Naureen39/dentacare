import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app.core.config import Settings
from app.core.deps import (
    AppSettings,
    Authenticated,
    Cipher,
    MailerDep,
    MfaSetupPrincipal,
    Passwords,
    RedisDep,
    Session,
)
from app.core.errors import AppError
from app.core.rate_limit import account_email_rule, ip_rate_limit, login_rule
from app.db.models import Patient
from app.schemas.auth import (
    AuthenticatedResponse,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    MfaDisableRequest,
    MfaEnableRequest,
    MfaRequiredResponse,
    MfaSetupRequiredResponse,
    MfaSetupResponse,
    MfaVerifyRequest,
    RecoveryCodesResponse,
    RegisterRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from app.services.auth import AuthService
from app.services.auth import Session as IssuedSession

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"  # noqa: S105
CSRF_HEADER = "X-CSRF-Token"
AUTH_COOKIE_PATH = "/api/v1/auth"

login_limit = Depends(ip_rate_limit(login_rule))
account_email_limit = Depends(ip_rate_limit(account_email_rule))


def get_auth_service(
    request: Request,
    db: Session,
    settings: AppSettings,
    redis: RedisDep,
    passwords: Passwords,
    cipher: Cipher,
    mailer: MailerDep,
) -> AuthService:
    return AuthService(
        db=db,
        settings=settings,
        redis=redis,
        passwords=passwords,
        cipher=cipher,
        mailer=mailer,
        request=request,
    )


Service = Annotated[AuthService, Depends(get_auth_service)]


# --- cookies and CSRF --------------------------------------------------------------


def _cookie_options(settings: Settings) -> dict[str, object]:
    options: dict[str, object] = {"secure": True, "samesite": "strict"}
    if settings.cookie_domain:
        options["domain"] = settings.cookie_domain
    return options


def set_session_cookies(response: Response, settings: Settings, refresh_token: str) -> None:
    max_age = settings.refresh_days * 24 * 3600
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=max_age,
        httponly=True,
        path=AUTH_COOKIE_PATH,
        **_cookie_options(settings),  # type: ignore[arg-type]
    )
    # Readable by the frontend so it can echo the value in a header (double submit).
    response.set_cookie(
        CSRF_COOKIE,
        secrets.token_urlsafe(24),
        max_age=max_age,
        httponly=False,
        path="/",
        **_cookie_options(settings),  # type: ignore[arg-type]
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    domain = settings.cookie_domain or None
    response.delete_cookie(
        REFRESH_COOKIE,
        path=AUTH_COOKIE_PATH,
        domain=domain,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(CSRF_COOKIE, path="/", domain=domain, secure=True, samesite="strict")


def require_csrf(request: Request) -> None:
    """Double submit token check plus an Origin allowlist, on top of SameSite=Strict."""
    settings: Settings = request.app.state.settings
    origin = request.headers.get("Origin")
    if origin is not None and origin not in settings.cors_origin_list:
        raise AppError("csrf_failed", "The request origin is not allowed.", 403)
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise AppError("csrf_failed", "The request could not be verified.", 403)


csrf_protected = Depends(require_csrf)


def _authenticated(
    response: Response, settings: Settings, session: IssuedSession
) -> AuthenticatedResponse:
    set_session_cookies(response, settings, session.refresh_token)
    return AuthenticatedResponse(
        access_token=session.access_token,
        expires_in=session.expires_in,
        recovery_codes=session.recovery_codes,
    )


# --- registration ------------------------------------------------------------------


@router.post(
    "/register", status_code=202, response_model=MessageResponse, dependencies=[account_email_limit]
)
async def register(body: RegisterRequest, service: Service) -> MessageResponse:
    await service.register(
        email=str(body.email).lower(),
        password=body.password,
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        marketing_consent=body.marketing_consent,
    )
    return MessageResponse(
        message="If the address can be registered, a confirmation email has been sent."
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(body: VerifyEmailRequest, service: Service) -> MessageResponse:
    await service.verify_email(body.token)
    return MessageResponse(message="Your email address has been confirmed. You can now sign in.")


# --- login and MFA -----------------------------------------------------------------


@router.post(
    "/login",
    response_model=AuthenticatedResponse | MfaRequiredResponse | MfaSetupRequiredResponse,
    dependencies=[login_limit],
)
async def login(
    body: LoginRequest, response: Response, service: Service, settings: AppSettings
) -> AuthenticatedResponse | MfaRequiredResponse | MfaSetupRequiredResponse:
    outcome = await service.login(str(body.email).lower(), body.password)
    if outcome.kind == "authenticated" and outcome.session is not None:
        return _authenticated(response, settings, outcome.session)
    if outcome.mfa_token is None:
        raise AppError("internal_error", "Sign in could not be completed.", 500)
    if outcome.kind == "mfa_required":
        return MfaRequiredResponse(mfa_token=outcome.mfa_token)
    return MfaSetupRequiredResponse(mfa_token=outcome.mfa_token)


@router.post("/mfa/verify", response_model=AuthenticatedResponse, dependencies=[login_limit])
async def mfa_verify(
    body: MfaVerifyRequest, response: Response, service: Service, settings: AppSettings
) -> AuthenticatedResponse:
    session = await service.verify_mfa(body.mfa_token, body.code, body.recovery_code)
    return _authenticated(response, settings, session)


@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def mfa_setup(principal: MfaSetupPrincipal, service: Service) -> MfaSetupResponse:
    secret, uri = await service.mfa_setup(principal.user)
    return MfaSetupResponse(secret=secret, otpauth_uri=uri)


@router.post("/mfa/enable", response_model=AuthenticatedResponse | RecoveryCodesResponse)
async def mfa_enable(
    body: MfaEnableRequest,
    principal: MfaSetupPrincipal,
    response: Response,
    service: Service,
    settings: AppSettings,
) -> AuthenticatedResponse | RecoveryCodesResponse:
    codes = await service.mfa_enable(principal.user, body.code)
    if principal.claims.token_type == "mfa_setup":
        # Mandatory enrolment finishes the interrupted sign in.
        session = await service.finish_enrolment_login(principal.user)
        session.recovery_codes = codes
        return _authenticated(response, settings, session)
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/mfa/disable", response_model=MessageResponse)
async def mfa_disable(
    body: MfaDisableRequest, current: Authenticated, service: Service
) -> MessageResponse:
    await service.mfa_disable(current.user, body.password, body.code)
    return MessageResponse(message="Multi-factor authentication has been disabled.")


# --- token lifecycle ---------------------------------------------------------------


@router.post("/refresh", response_model=AuthenticatedResponse, dependencies=[csrf_protected])
async def refresh(
    request: Request, response: Response, service: Service, settings: AppSettings
) -> AuthenticatedResponse:
    try:
        session = await service.refresh(request.cookies.get(REFRESH_COOKIE))
    except AppError:
        clear_session_cookies(response, settings)
        raise
    return _authenticated(response, settings, session)


@router.post("/logout", status_code=204, dependencies=[csrf_protected])
async def logout(request: Request, service: Service, settings: AppSettings) -> Response:
    await service.logout(request.cookies.get(REFRESH_COOKIE))
    response = Response(status_code=204)
    clear_session_cookies(response, settings)
    return response


# --- password recovery -------------------------------------------------------------


@router.post(
    "/forgot", status_code=202, response_model=MessageResponse, dependencies=[account_email_limit]
)
async def forgot(body: ForgotPasswordRequest, service: Service) -> MessageResponse:
    await service.forgot_password(str(body.email).lower())
    return MessageResponse(
        message="If an account exists for that address, a reset link has been sent."
    )


@router.post("/reset", response_model=MessageResponse)
async def reset(body: ResetPasswordRequest, service: Service) -> MessageResponse:
    await service.reset_password(body.token, body.new_password)
    return MessageResponse(message="Your password has been changed. Please sign in.")


@router.post("/password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest, current: Authenticated, service: Service
) -> MessageResponse:
    await service.change_password(current.user, body.current_password, body.new_password)
    return MessageResponse(
        message="Your password has been changed. Please sign in again on other devices."
    )


# --- identity ----------------------------------------------------------------------


@router.get("/me", response_model=MeResponse)
async def me(current: Authenticated, db: Session) -> MeResponse:
    patient_id = (
        await db.execute(select(Patient.id).where(Patient.user_id == current.id))
    ).scalar_one_or_none()
    return MeResponse(
        id=current.id,
        email=current.user.email,
        role=current.role,
        mfa_enabled=current.user.mfa_enabled,
        email_verified=current.user.email_verified_at is not None,
        patient_id=patient_id,
    )
