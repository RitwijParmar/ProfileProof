from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PROFILEPROOF_", env_file=".env")

    environment: str = "development"
    log_level: str = "INFO"
    cache_ttl_seconds: int = Field(default=3600, ge=0, le=86_400)
    rate_limit_requests: int = Field(default=60, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    max_body_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    oidc_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)
    pdl_timeout_seconds: float = Field(default=8.0, ge=0.1, le=30.0)
    pdl_min_likelihood: int = Field(default=8, ge=6, le=10)
    pdl_calls_per_instance_per_day: int = Field(default=50, ge=1, le=10_000)
    pdl_api_key: SecretStr | None = None
    enable_demo_provider: bool = True
    api_key_sha256: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
