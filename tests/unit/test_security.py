import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from posts_api.app.security import TOKEN_ALGORITHM, decode_access_token, load_public_key


def par_de_claves() -> tuple[Ed25519PrivateKey, str]:
    """A key pair, with the public half in PEM as the service receives it."""
    private = Ed25519PrivateKey.generate()
    pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, pem


def firmar(private: Ed25519PrivateKey, *, expira_en_minutos: int = 15) -> str:
    """Sign a token the same shape users-api issues."""
    ahora = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "role": "user",
            "jti": str(uuid.uuid4()),
            "iat": ahora,
            "exp": ahora + timedelta(minutes=expira_en_minutos),
        },
        private,
        algorithm=TOKEN_ALGORITHM,
    )


def test_a_token_signed_with_the_matching_key_is_accepted():
    private, pem = par_de_claves()
    token = firmar(private)

    claims = decode_access_token(load_public_key(pem), token)

    assert uuid.UUID(claims["sub"])
    assert claims["role"] == "user"


def test_a_token_signed_with_another_key_is_rejected():
    _, pem = par_de_claves()
    otra_private, _ = par_de_claves()
    token = firmar(otra_private)

    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(load_public_key(pem), token)


def test_an_expired_token_is_rejected():
    private, pem = par_de_claves()
    token = firmar(private, expira_en_minutos=-1)

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(load_public_key(pem), token)


def test_a_token_that_claims_no_signature_is_rejected():
    """The alg:none attack: a token that asks to be trusted without a signature."""
    _, pem = par_de_claves()
    token = jwt.encode({"sub": str(uuid.uuid4())}, key=None, algorithm="none")

    with pytest.raises(jwt.InvalidAlgorithmError):
        decode_access_token(load_public_key(pem), token)


def test_a_private_key_is_not_accepted_as_the_public_one():
    private, _ = par_de_claves()
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    with pytest.raises(ValueError):
        load_public_key(pem)


def test_a_public_key_of_another_algorithm_is_rejected():
    """A valid PEM that is not Ed25519: RSA would verify a different signature."""
    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    with pytest.raises(ValueError, match="Ed25519"):
        load_public_key(rsa_pem)
