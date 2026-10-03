import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Integration tests need PostgreSQL and Redis. docker/docker-compose.dev.yml
# provides both; without the variables the whole integration suite is skipped so
# the unit tests still run on any machine.
HAS_SERVICES = bool(os.getenv("DATABASE_URL") and os.getenv("REDIS_URL"))

requires_services = pytest.mark.skipif(not HAS_SERVICES, reason="needs DATABASE_URL and REDIS_URL")


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    """Bring the schema up with Alembic, not with metadata.create_all.

    Running the real migration means the tests also prove that it matches the
    models: a column added to a model without its migration fails here instead
    of in production.
    """
    if not HAS_SERVICES:
        return

    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


# The tests mint their own key pair and overwrite whatever the environment
# carries: signing needs the private half, so a key from outside is unusable
# here. The CI sets its own throwaway key for the service, and this replaces it
# for the duration of the suite.
TEST_PRIVATE_KEY = Ed25519PrivateKey.generate()
os.environ["JWT_PUBLIC_KEY"] = (
    TEST_PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)

# The service refuses to start without the secret. Kept if the environment has
# one. users-api points at a port nothing listens on: the tests that do not
# replace the call see it refused at once, never a real host.
os.environ.setdefault("INTERNAL_API_TOKEN", "test-internal-token")
os.environ.setdefault("USERS_API_URL", "http://127.0.0.1:9")


def issue_token(
    subject: uuid.UUID | None = None,
    *,
    issuer: str = "users-api",
    role: str = "user",
    handle: str | None = "@alumno_01",
    profile_visibility: str | None = "public",
    expires_in_minutes: int = 15,
) -> str:
    """A token of the same shape users-api issues, signed with the test key."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "sub": str(subject or uuid.uuid4()),
            "role": role,
            "handle": handle,
            "profile_visibility": profile_visibility,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=expires_in_minutes),
        },
        TEST_PRIVATE_KEY,
        algorithm="EdDSA",
    )
