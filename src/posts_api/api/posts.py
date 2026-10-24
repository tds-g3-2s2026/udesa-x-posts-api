import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from posts_api.api.deps import CurrentUserDep, PostImagesDep, RedisDep, SessionDep
from posts_api.api.multipart import is_multipart, read_post_form
from posts_api.api.schemas.feed import FeedPostSummary
from posts_api.api.schemas.pagination import CursorPage
from posts_api.api.schemas.posts import CreatePostRequest, PostSummary
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.likes import LikeRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.retweets import RetweetRepository
from posts_api.app.services.posts import PostService
from posts_api.config.settings import get_settings
from posts_api.infrastructure.redis.rate_limiter import RedisRateLimiter

router = APIRouter(prefix="/posts", tags=["posts"])


def get_post_service(session: SessionDep, redis: RedisDep, images: PostImagesDep) -> PostService:
    """Where the service gets its collaborators: PostgreSQL, Redis and the image storage."""
    settings = get_settings()
    return PostService(
        PostRepository(session),
        FollowRepository(session),
        RedisRateLimiter(redis),
        LikeRepository(session),
        RetweetRepository(session),
        images,
        post_limit=settings.post_rate_limit,
        window_seconds=settings.post_rate_window_seconds,
    )


ServiceDep = Annotated[PostService, Depends(get_post_service)]


async def read_json_body(request: Request) -> CreatePostRequest:
    """The JSON body, failing the way FastAPI does when it validates one itself.

    Read by hand because this one route takes two kinds of body and FastAPI
    can only declare one; the errors keep the shape the declared body gave.
    """
    raw = await request.body()
    if not raw:
        raise RequestValidationError(
            [{"type": "missing", "loc": ("body",), "msg": "Field required"}]
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RequestValidationError(
            [{"type": "json_invalid", "loc": ("body", exc.pos), "msg": "JSON decode error"}]
        ) from exc
    try:
        return CreatePostRequest.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        ) from exc


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_post(
    request: Request, current_user: CurrentUserDep, service: ServiceDep
) -> PostSummary:
    """Publish a post, as JSON or as `multipart/form-data` with up to four images.

    The author comes from the token, never from the body.
    """
    if not is_multipart(request.headers.get("content-type")):
        body = await read_json_body(request)
        return PostSummary.of(await service.create(current_user, body.content))

    # Charged before the body is read: a client that is over its limit does not
    # get to make the server receive its files first.
    await service.charge(current_user)
    form = await read_post_form(request)
    try:
        post = await service.create(current_user, form.content, images=form.images, charged=True)
    finally:
        form.close()
    return PostSummary.of(post)


@router.get("/{post_id}")
async def get_post(
    post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> FeedPostSummary:
    """A single post. `404` for one that does not exist and for one the caller cannot see."""
    post = await service.get(post_id, current_user)
    return FeedPostSummary.of(post)


@router.post("/{post_id}/replies", status_code=status.HTTP_201_CREATED)
async def create_reply(
    post_id: uuid.UUID,
    body: CreatePostRequest,
    current_user: CurrentUserDep,
    service: ServiceDep,
) -> PostSummary:
    """Answer a post. Same body, same checks and same limit as publishing one."""
    reply = await service.create(current_user, body.content, parent_id=post_id)
    return PostSummary.of(reply)


@router.get("/{post_id}/replies")
async def list_replies(
    post_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: ServiceDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[FeedPostSummary]:
    """The replies to a post, oldest first. `404` when the post itself is not readable."""
    replies, next_cursor = await service.replies_to(post_id, current_user, cursor=cursor)
    items = [FeedPostSummary.of(one) for one in replies]
    return CursorPage(items=items, next_cursor=next_cursor)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> None:
    await service.delete(post_id, current_user)
