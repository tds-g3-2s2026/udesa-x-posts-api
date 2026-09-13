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


def decode_access_token(public_key: Ed25519PublicKey, token: str) -> dict:
    """Check the signature and the expiry, and return the claims.

    The algorithm is pinned to a single value: accepting whatever the token
    announces is how the `alg:none` and the HS256 confusion attacks work.
    """
    return jwt.decode(token, public_key, algorithms=[TOKEN_ALGORITHM])
