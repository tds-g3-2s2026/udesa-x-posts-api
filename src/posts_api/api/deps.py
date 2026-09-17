"""Where the interfaces get their implementations.

This is the seam. Above it the services talk to abstractions; below it live the
classes under `infrastructure/`. Moving a piece to another technology is
changing what this module hands out, and nothing else.

The connections themselves are opened once in the lifespan and read from
`app.state`, so a handler never reaches in there by hand.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account
from posts_api.app.security import decode_access_token
from posts_api.infrastructure.database.session import session_scope


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A transaction per request, committed when the handler returns."""
    async for session in session_scope(request.app.state.session_factory):
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_redis(request: Request) -> Redis:
    """The connection opened once in the lifespan, not a new one per request."""
    return request.app.state.redis


RedisDep = Annotated[Redis, Depends(get_redis)]

# Rejects a missing or malformed Authorization header before anything else runs.
bearer_scheme = HTTPBearer()
BearerDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)]


def get_current_user(request: Request, credentials: BearerDep) -> Account:
    """The account behind the bearer token.

    Signature and expiry are all this service checks. Revocation is recorded in
    the Redis of users-api, which posts-api does not share, so a token closed by
    a logout keeps working here until it expires on its own: fifteen minutes at
    most. Narrowing that window needs the revocation events from the queue.
    """
    try:
        claims = decode_access_token(request.app.state.jwt_public_key, credentials.credentials)
    except jwt.InvalidTokenError as exc:
        raise ProblemError(
            status=401,
            code="invalid-token",
            title="No se pudo autenticar la solicitud",
            detail="El token no es válido",
        ) from exc

    # The handle is read with `get` and not indexed: a token minted before
    # users-api started sending it stays valid until it expires, and rejecting
    # it would log everyone out on deploy.
    return Account(id=uuid.UUID(claims["sub"]), handle=claims.get("handle"))


CurrentUserDep = Annotated[Account, Depends(get_current_user)]
