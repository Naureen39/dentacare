import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.enums import UserRole


class StrictModel(BaseModel):
    """Rejects unknown fields, which blocks mass assignment."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    marketing_consent: bool = False


class MessageResponse(BaseModel):
    message: str


class VerifyEmailRequest(StrictModel):
    token: str = Field(min_length=20, max_length=200)


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class MfaVerifyRequest(StrictModel):
    mfa_token: str = Field(min_length=20, max_length=2000)
    code: str | None = Field(default=None, min_length=6, max_length=6)
    recovery_code: str | None = Field(default=None, min_length=8, max_length=20)


class MfaEnableRequest(StrictModel):
    code: str = Field(min_length=6, max_length=6)


class MfaDisableRequest(StrictModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=6)


class ForgotPasswordRequest(StrictModel):
    email: EmailStr


class ResetPasswordRequest(StrictModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(StrictModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class AuthenticatedResponse(BaseModel):
    status: Literal["authenticated"] = "authenticated"
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    recovery_codes: list[str] | None = None


class MfaRequiredResponse(BaseModel):
    status: Literal["mfa_required"] = "mfa_required"
    mfa_token: str


class MfaSetupRequiredResponse(BaseModel):
    status: Literal["mfa_setup_required"] = "mfa_setup_required"
    mfa_token: str


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    mfa_enabled: bool
    email_verified: bool
    patient_id: uuid.UUID | None
