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
    linkedin_timeout_seconds: float = Field(default=10.0, ge=0.1, le=30.0)
    linkedin_min_interval_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
    linkedin_cooldown_seconds: int = Field(default=900, ge=60, le=86_400)
    linkedin_calls_per_instance_per_day: int = Field(default=100, ge=1, le=10_000)
    linkedin_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    )
    linkedin_li_at: SecretStr | None = None
    linkedin_jsessionid: SecretStr | None = None
    relay_pointer_url: str | None = None
    enable_demo_provider: bool = True
    api_key_sha256: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
