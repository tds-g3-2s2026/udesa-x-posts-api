"""Where the interfaces get their implementations.

This is the seam. Above it the services talk to abstractions; below it live the
classes under `infrastructure/`. Moving a piece to another technology is
changing what this module hands out, and nothing else.

The connections themselves are opened once in the lifespan and read from
`app.state`, so a handler never reaches in there by hand.
"""

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, ProfileVisibility
from posts_api.app.repositories.revocations import RevocationStore
from posts_api.app.security import decode_access_token
from posts_api.infrastructure.database.session import session_scope
from posts_api.infrastructure.redis.revocations import RedisRevocationStore

logger = logging.getLogger(__name__)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A transaction per request, committed when the handler returns."""
    async for session in session_scope(request.app.state.session_factory):
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_redis(request: Request) -> Redis:
    """The connection opened once in the lifespan, not a new one per request."""
    return request.app.state.redis


RedisDep = Annotated[Redis, Depends(get_redis)]


def get_users_api(request: Request) -> httpx.AsyncClient:
    """The client for the internal routes of users-api, opened once in the lifespan."""
    return request.app.state.users_api


UsersApiDep = Annotated[httpx.AsyncClient, Depends(get_users_api)]


def get_revocations(request: Request) -> RevocationStore:
    """The revocation marks of users-api, over the connection opened in the lifespan."""
    return RedisRevocationStore(request.app.state.auth_redis)


RevocationsDep = Annotated[RevocationStore, Depends(get_revocations)]

# Rejects a missing or malformed Authorization header before anything else runs.
bearer_scheme = HTTPBearer()
BearerDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)]


async def get_current_user(
    request: Request, credentials: BearerDep, revocations: RevocationsDep
) -> Account:
    """The account behind the bearer token.

    Signature, expiry and issuer are checked locally. Revocation is not: a
    logout, a password change or an account put under review is written by
    users-api in its Redis, and ADR-014 has this service read those marks on
    every request instead of waiting for the token to expire. The answer is
    the same as users-api gives.
    """
    try:
        claims = decode_access_token(
            request.app.state.jwt_public_key,
            credentials.credentials,
            issuer=request.app.state.settings.jwt_issuer,
        )
    except jwt.InvalidTokenError as exc:
        raise ProblemError(
            status=401,
            code="invalid-token",
            title="No se pudo autenticar la solicitud",
            detail="El token no es válido",
        ) from exc

    user_id = uuid.UUID(claims["sub"])
    try:
        revoked = await revocations.is_revoked(claims["jti"], user_id, claims["iat"])
    except RedisError as exc:
        # Fail closed: when the marks cannot be read there is no way to tell a
        # live session from a closed one, and letting the request through would
        # bring back the window this check exists to close.
        logger.exception("Could not read the revocation marks")
        raise ProblemError(
            status=503,
            code="auth-unavailable",
            title="No se pudo verificar la sesión",
            detail="No pudimos verificar tu sesión en este momento. Probá de nuevo en unos minutos",
        ) from exc
    if revoked:
        raise ProblemError(
            status=401,
            code="session-revoked",
            title="La sesión ya no es válida",
            detail="Tu sesión se cerró. Iniciá sesión de nuevo",
        )

    # The handle and the visibility are both read with `get` and not indexed:
    # a token minted before users-api started sending either one stays valid
    # until it expires, and rejecting it would log everyone out on deploy.
    raw_visibility = claims.get("profile_visibility")
    try:
        profile_visibility = ProfileVisibility(raw_visibility) if raw_visibility else None
    except ValueError:
        profile_visibility = None

    return Account(
        id=user_id,
        handle=claims.get("handle"),
        profile_visibility=profile_visibility,
    )


CurrentUserDep = Annotated[Account, Depends(get_current_user)]
