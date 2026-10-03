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

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, ProfileVisibility
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


def get_users_api(request: Request) -> httpx.AsyncClient:
    """The client for the internal routes of users-api, opened once in the lifespan."""
    return request.app.state.users_api


UsersApiDep = Annotated[httpx.AsyncClient, Depends(get_users_api)]

# Rejects a missing or malformed Authorization header before anything else runs.
bearer_scheme = HTTPBearer()
BearerDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)]


def get_claims(request: Request, credentials: BearerDep) -> dict:
    """The claims of the bearer token.

    Signature, expiry and issuer are checked locally. Revocation is recorded in
    the Redis of users-api, which posts-api does not share, so a token closed by
    a logout keeps working here until it expires on its own: fifteen minutes at
    most. Narrowing that window needs the revocation events from the queue.
    """
    try:
        return decode_access_token(
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


ClaimsDep = Annotated[dict, Depends(get_claims)]


def get_current_user(claims: ClaimsDep) -> Account:
    """The account behind the bearer token."""
    # The handle and the visibility are both read with `get` and not indexed:
    # a token minted before users-api started sending either one stays valid
    # until it expires, and rejecting it would log everyone out on deploy.
    raw_visibility = claims.get("profile_visibility")
    try:
        profile_visibility = ProfileVisibility(raw_visibility) if raw_visibility else None
    except ValueError:
        profile_visibility = None

    return Account(
        id=uuid.UUID(claims["sub"]),
        handle=claims.get("handle"),
        profile_visibility=profile_visibility,
    )


CurrentUserDep = Annotated[Account, Depends(get_current_user)]

# The roles users-api hands to backoffice accounts.
ADMINISTRATOR_ROLES = frozenset({"moderator", "superadmin"})


def require_administrator(claims: ClaimsDep) -> None:
    """Refuse anything but a backoffice token, with 403: the session is valid,
    the permission is missing."""
    if claims.get("role") not in ADMINISTRATOR_ROLES:
        raise ProblemError(
            status=403,
            code="administrator-required",
            title="No se pudo completar la acción",
            detail="Solo un administrador puede ver esta información",
        )


AdministratorDep = Annotated[None, Depends(require_administrator)]
