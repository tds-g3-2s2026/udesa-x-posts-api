"""Verifying the access tokens that users-api issues.

This service never signs a token, it only checks one. That asymmetry is the
whole point of EdDSA over a shared secret: holding the public half lets
posts-api verify, and does not let it mint.
"""

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

TOKEN_ALGORITHM = "EdDSA"


def load_public_key(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("JWT_PUBLIC_KEY must be an Ed25519 public key in PEM format")
    return key


def decode_access_token(public_key: Ed25519PublicKey, token: str, *, issuer: str) -> dict:
    """Check the signature, the expiry, and the issuer, and return the claims.

    The algorithm is pinned to a single value: accepting whatever the token
    announces is how the `alg:none` and the HS256 confusion attacks work.
    """
    return jwt.decode(
        token,
        public_key,
        algorithms=[TOKEN_ALGORITHM],
        issuer=issuer,
        # `jti` and `iat` are what the revocation marks of users-api are matched
        # against, so a token without them cannot be checked and is refused.
        options={"require": ["iss", "iat", "jti"]},
    )


def is_session_revoked(*, token_marked: bool, cutoff: int | None, issued_at: float) -> bool:
    """Whether users-api closed the session this token belongs to.

    `token_marked` is the mark of a single logout. `cutoff` is the instant after
    which nothing issued earlier counts, written by a password change or by an
    account put under review; `None` when there is none.

    Compared with <= and not <: users-api stores the cutoff truncated to the
    second, so a token issued inside that same second would otherwise survive the
    very change that was supposed to kill it. The rule is the one `get_current_user`
    applies in users-api and has to stay identical to it.
    """
    return token_marked or (cutoff is not None and issued_at <= cutoff)
