from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, read from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No defaults on purpose: a missing URL stops the service from starting,
    # instead of failing on the first request.
    database_url: str
    redis_url: str

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
