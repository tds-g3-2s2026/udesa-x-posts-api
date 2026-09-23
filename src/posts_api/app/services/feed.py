"""The rules of reading the feed.

No FastAPI and no SQLAlchemy here, the same shape every other service in this
codebase uses.
"""

from posts_api.app.models.follow import Account
from posts_api.app.models.post import PostWithAuthor
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.feed import FeedRepository


class FeedService:
    def __init__(self, feed: FeedRepository) -> None:
        self._feed = feed

    async def for_viewer(
        self, viewer: Account, *, cursor: str | None = None
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The posts of whoever the viewer follows, one page at a time."""
        decoded = Cursor.decode(cursor) if cursor is not None else None
        return await self._feed.for_viewer(viewer.id, cursor=decoded)
