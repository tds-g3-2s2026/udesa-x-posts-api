import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from posts_api.api.deps import CurrentUserDep, RedisDep, SessionDep
from posts_api.api.schemas.follow_listings import FollowListItemSummary
from posts_api.api.schemas.pagination import CursorPage
from posts_api.app.repositories.follow_listings import FollowListingRepository
from posts_api.app.repositories.follow_requests import FollowRequestRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.services.follow_listings import FollowListingService
from posts_api.app.services.follows import FollowService
from posts_api.config.settings import get_settings
from posts_api.infrastructure.redis.rate_limiter import RedisRateLimiter

router = APIRouter(prefix="/users", tags=["follows"])


def get_follow_service(session: SessionDep, redis: RedisDep) -> FollowService:
    """Where the service gets its collaborators: PostgreSQL and Redis."""
    settings = get_settings()
    return FollowService(
        FollowRepository(session),
        FollowRequestRepository(session),
        RedisRateLimiter(redis),
        follow_limit=settings.follow_rate_limit,
        window_seconds=settings.follow_rate_window_seconds,
    )


ServiceDep = Annotated[FollowService, Depends(get_follow_service)]


def get_follow_listing_service(session: SessionDep) -> FollowListingService:
    return FollowListingService(FollowListingRepository(session), FollowRepository(session))


ListingServiceDep = Annotated[FollowListingService, Depends(get_follow_listing_service)]


@router.post(
    "/{user_id}/follow",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={202: {"description": "La cuenta es protegida y quedó una solicitud pendiente."}},
)
async def follow(user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> Response:
    """Follow an account. Who is following comes from the token, never from the body."""
    pending = await service.follow(current_user, user_id)
    # 202 and not 201: nothing was created for the caller, the request was
    # accepted and somebody else has to answer it.
    if pending is not None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow(user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    await service.unfollow(current_user, user_id)


@router.get("/{user_id}/followers")
async def followers(
    user_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: ListingServiceDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[FollowListItemSummary]:
    """Whoever follows this account. Reading it also puts the caller on the graph."""
    items, next_cursor = await service.followers_of(user_id, current_user, cursor=cursor)
    return CursorPage(
        items=[FollowListItemSummary.of(one) for one in items], next_cursor=next_cursor
    )


@router.get("/{user_id}/following")
async def following(
    user_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: ListingServiceDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[FollowListItemSummary]:
    """Whoever this account follows."""
    items, next_cursor = await service.following_of(user_id, current_user, cursor=cursor)
    return CursorPage(
        items=[FollowListItemSummary.of(one) for one in items], next_cursor=next_cursor
    )
