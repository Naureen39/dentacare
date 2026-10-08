from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://meridian:meridian@127.0.0.1:5432/meridian"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-development-only"  # noqa: S105
    jwt_access_minutes: int = 15
    refresh_days: int = 14
    field_encryption_key: str = ""
    cookie_domain: str = ""
    cors_origins: str = "http://localhost:5173"
    public_base_url: str = "http://localhost:5173"
    field_encryption_old_keys: str = ""

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    gemini_api_key: str = ""
    gemini_model: str = ""
    llm_primary: Literal["groq", "gemini"] = "groq"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str = "models"
    embed_preload: bool = True
    kb_dir: str = "../data/kb"
    intents_file: str = "../data/intents.yaml"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_pass: str = ""

    clinic_tz: str = "America/New_York"
    clinic_name: str = "Meridian Dental Care"
    clinic_address: str = "1200 Harbor View Drive, Suite 300, Springfield, NY 10001"
    clinic_phone: str = "(555) 010-0199"
    clinic_email: str = "frontdesk@meridian.test"
    mail_from: str = "no-reply@meridian.test"

    # Password hashing (argon2id). Defaults follow current OWASP guidance.
    argon2_time_cost: int = Field(default=3, ge=1)
    argon2_memory_kib: int = Field(default=65536, ge=8)
    argon2_parallelism: int = Field(default=2, ge=1)

    # Authentication policy
    password_min_length: int = 12
    email_verification_hours: int = 24
    password_reset_minutes: int = 30
    lockout_attempts: int = 5
    lockout_minutes: int = 15
    mfa_challenge_minutes: int = 5

    # Rate limits (requests per window)
    rate_limit_login_per_minute: int = 5
    rate_limit_public_booking_per_hour: int = 20
    rate_limit_chat_per_minute: int = 30
    rate_limit_contact_per_hour: int = 5
    rate_limit_account_email_per_hour: int = 10
    rate_limit_action_link_per_hour: int = 60

    # Retention defaults, overridden by app_settings rows
    chat_retention_days: int = 90
    guest_anonymize_months: int = 12

    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        if self.env == "production":
            if self.jwt_secret.startswith("change-me") or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be a random value of at least 32 characters")
            if not self.field_encryption_key:
                raise ValueError("FIELD_ENCRYPTION_KEY is required in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
