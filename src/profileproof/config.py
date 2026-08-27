from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROFILEPROOF_", env_file=".env")

    environment: str = "development"
    log_level: str = "INFO"
    cache_ttl_seconds: int = Field(default=300, ge=0, le=3600)
    rate_limit_requests: int = Field(default=60, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    max_body_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    oidc_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    enable_demo_provider: bool = True
    api_key_sha256: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
