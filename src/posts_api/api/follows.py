import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from posts_api.api.deps import CurrentUserDep, RedisDep, SessionDep
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.services.follows import FollowService
from posts_api.config.settings import get_settings
from posts_api.infrastructure.redis.rate_limiter import RedisRateLimiter

router = APIRouter(prefix="/users", tags=["follows"])


def get_follow_service(session: SessionDep, redis: RedisDep) -> FollowService:
    """Where the service gets its collaborators: PostgreSQL and Redis."""
    settings = get_settings()
    return FollowService(
        FollowRepository(session),
        RedisRateLimiter(redis),
        follow_limit=settings.follow_rate_limit,
        window_seconds=settings.follow_rate_window_seconds,
    )


ServiceDep = Annotated[FollowService, Depends(get_follow_service)]


@router.post("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def follow(user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    """Follow an account. Who is following comes from the token, never from the body."""
    await service.follow(current_user, user_id)


@router.delete("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow(user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    await service.unfollow(current_user, user_id)
