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

# The tests mint their own key pair so they never depend on users-api running.
# setdefault leaves a real key alone when one is passed in.
TEST_PRIVATE_KEY = Ed25519PrivateKey.generate()
os.environ.setdefault(
    "JWT_PUBLIC_KEY",
    TEST_PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode(),
)


def issue_token(subject: uuid.UUID | None = None, *, expires_in_minutes: int = 15) -> str:
    """A token of the same shape users-api issues, signed with the test key."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(subject or uuid.uuid4()),
            "role": "user",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=expires_in_minutes),
        },
        TEST_PRIVATE_KEY,
        algorithm="EdDSA",
    )
