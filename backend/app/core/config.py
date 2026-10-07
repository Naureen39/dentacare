from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://meridian:meridian@localhost:5432/meridian"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-development-only"  # noqa: S105
    jwt_access_minutes: int = 15
    refresh_days: int = 14
    field_encryption_key: str = ""
    cookie_domain: str = ""
    cors_origins: str = "http://localhost:5173"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    gemini_api_key: str = ""
    gemini_model: str = ""
    llm_primary: Literal["groq", "gemini"] = "groq"
    embed_model: str = "BAAI/bge-small-en-v1.5"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_pass: str = ""

    clinic_tz: str = "America/New_York"
    clinic_name: str = "Meridian Dental Care"

    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
