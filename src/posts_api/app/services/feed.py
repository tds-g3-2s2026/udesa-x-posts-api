"""The rules of reading the feed.

No FastAPI and no SQLAlchemy here, the same shape every other service in this
codebase uses.
"""

from posts_api.app.feed_pagination import FeedCursor
from posts_api.app.models.follow import Account
from posts_api.app.models.post import PostWithAuthor
from posts_api.app.repositories.feed import FeedRepository
from posts_api.app.services.post_images import PostImages


class FeedService:
    def __init__(self, feed: FeedRepository, images: PostImages) -> None:
        self._feed = feed
        self._images = images

    async def for_viewer(
        self, viewer: Account, *, cursor: str | None = None
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The posts of whoever the viewer follows, one page at a time."""
        decoded = FeedCursor.decode(cursor) if cursor is not None else None
        posts, next_cursor = await self._feed.for_viewer(viewer.id, cursor=decoded)
        return await self._images.attach(posts), next_cursor
