from typing import Annotated

from fastapi import APIRouter, Depends, Query

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.api.schemas.feed import FeedPostSummary
from posts_api.api.schemas.pagination import CursorPage
from posts_api.app.repositories.feed import FeedRepository
from posts_api.app.services.feed import FeedService

router = APIRouter(prefix="/feed", tags=["feed"])


def get_feed_service(session: SessionDep) -> FeedService:
    return FeedService(FeedRepository(session))


ServiceDep = Annotated[FeedService, Depends(get_feed_service)]


@router.get("")
async def read_feed(
    current_user: CurrentUserDep,
    service: ServiceDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[FeedPostSummary]:
    """The posts of whoever the caller follows, newest first."""
    posts, next_cursor = await service.for_viewer(current_user, cursor=cursor)
    items = [FeedPostSummary.of(one) for one in posts]
    return CursorPage(items=items, next_cursor=next_cursor)
