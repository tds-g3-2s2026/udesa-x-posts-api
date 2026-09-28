import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from posts_api.api.deps import CurrentUserDep, RedisDep, SessionDep
from posts_api.api.schemas.feed import FeedPostSummary
from posts_api.api.schemas.posts import CreatePostRequest, PostSummary
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.services.posts import PostService
from posts_api.config.settings import get_settings
from posts_api.infrastructure.redis.rate_limiter import RedisRateLimiter

router = APIRouter(prefix="/posts", tags=["posts"])


def get_post_service(session: SessionDep, redis: RedisDep) -> PostService:
    """Where the service gets its collaborators: PostgreSQL and Redis."""
    settings = get_settings()
    return PostService(
        PostRepository(session),
        FollowRepository(session),
        RedisRateLimiter(redis),
        post_limit=settings.post_rate_limit,
        window_seconds=settings.post_rate_window_seconds,
    )


ServiceDep = Annotated[PostService, Depends(get_post_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_post(
    body: CreatePostRequest, current_user: CurrentUserDep, service: ServiceDep
) -> PostSummary:
    """Publish a post. The author comes from the token, never from the body."""
    post = await service.create(current_user, body.content)
    return PostSummary.of(post)


@router.get("/{post_id}")
async def get_post(
    post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> FeedPostSummary:
    """A single post. `404` for one that does not exist and for one the caller cannot see."""
    post = await service.get(post_id, current_user)
    return FeedPostSummary.of(post)
