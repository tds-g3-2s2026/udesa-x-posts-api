"""Mint a key pair and a token, for trying the API by hand in development.

Real tokens come from users-api. This exists so posts-api can be exercised on
its own, before the two services run together.

    uv run python scripts/dev_token.py

Prints the public key to put in JWT_PUBLIC_KEY and a token to send as
`Authorization: Bearer <token>`.
"""

import sys
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from posts_api.app.security import TOKEN_ALGORITHM


def main() -> None:
    private = Ed25519PrivateKey.generate()
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    # The id comes from the command line when the token has to match a user that
    # already exists, and is generated otherwise.
    subject = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "users-api",
            "sub": subject,
            "role": "user",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        private,
        algorithm=TOKEN_ALGORITHM,
    )

    print("JWT_PUBLIC_KEY:")
    print(public_pem)
    print(f"sub:   {subject}")
    print(f"token: {token}")


if __name__ == "__main__":
    main()
