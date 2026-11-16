import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from posts_api.api.deps import CurrentUserDep, PostImagesDep, SessionDep
from posts_api.api.schemas.feed import FeedPostSummary
from posts_api.api.schemas.pagination import CursorPage
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.bookmarks import BookmarkRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.services.bookmarks import BookmarkService

router = APIRouter(tags=["bookmarks"])


def get_bookmark_service(session: SessionDep, images: PostImagesDep) -> BookmarkService:
    return BookmarkService(
        BookmarkRepository(session), PostRepository(session), FollowRepository(session), images
    )


ServiceDep = Annotated[BookmarkService, Depends(get_bookmark_service)]


@router.put("/posts/{post_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def save_post(post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    """Save a post to the caller's list. Idempotent: `204` whether it was new or already there."""
    await service.save(current_user, post_id)


@router.delete("/posts/{post_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def unsave_post(
    post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> None:
    """Take the post off the caller's list. Idempotent: `204` whether it was saved or not."""
    await service.unsave(current_user, post_id)


@router.get("/bookmarks")
async def read_bookmarks(
    current_user: CurrentUserDep,
    service: ServiceDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[FeedPostSummary]:
    """The posts the caller saved, most recently saved first."""
    decoded = Cursor.decode(cursor) if cursor is not None else None
    posts, next_cursor = await service.list(current_user, decoded)
    return CursorPage(items=[FeedPostSummary.of(one) for one in posts], next_cursor=next_cursor)
