from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "ClearText API"
    app_version: str = "1.0.0"
    redis_url: str = "redis://localhost:6379"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    api_master_key: str = ""
    cache_ttl_seconds: int = 86400  # 24 hours
    playwright_timeout_ms: int = 15000
    max_content_length: int = 500000  # ~500KB of text

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
