from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration, read from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No defaults on purpose: a missing URL stops the service from starting,
    # instead of failing on the first request.
    database_url: str
    redis_url: str

    # Ed25519 public key in PEM format, the other half of the key users-api
    # signs with. Without it the service cannot tell a real token from a forged
    # one, so it refuses to start rather than accept everything.
    jwt_public_key: str

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
