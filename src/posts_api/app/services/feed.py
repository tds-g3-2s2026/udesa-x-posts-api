"""The rules of reading the feed, and the feed of a list.

No FastAPI and no SQLAlchemy here, the same shape every other service in this
codebase uses.
"""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.feed_pagination import FeedCursor
from posts_api.app.models.follow import Account
from posts_api.app.models.post import PostWithAuthor
from posts_api.app.repositories.feed import FeedRepository
from posts_api.app.repositories.lists import ListRepository
from posts_api.app.services.post_images import PostImages


class FeedService:
    def __init__(self, feed: FeedRepository, images: PostImages, lists: ListRepository) -> None:
        self._feed = feed
        self._images = images
        self._lists = lists

    async def for_viewer(
        self, viewer: Account, *, cursor: str | None = None
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The posts of whoever the viewer follows, one page at a time."""
        decoded = FeedCursor.decode(cursor) if cursor is not None else None
        posts, next_cursor = await self._feed.for_viewer(viewer.id, cursor=decoded)
        return await self._images.attach(posts), next_cursor

    async def for_list(
        self, viewer: Account, list_id: uuid.UUID, *, cursor: str | None = None
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The posts of the accounts in one of the viewer's lists, one page at a time (E3-H8).

        A list made by someone else answers the same 404 as one that does not exist.
        """
        if await self._lists.find_owned(list_id, viewer.id) is None:
            raise ProblemError(
                status=404,
                code="list-not-found",
                title="No se pudo abrir la lista",
                detail="La lista no existe",
            )
        decoded = FeedCursor.decode(cursor) if cursor is not None else None
        posts, next_cursor = await self._feed.for_list(viewer.id, list_id, cursor=decoded)
        return await self._images.attach(posts), next_cursor
