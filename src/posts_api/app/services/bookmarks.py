"""The rules of saving a post to a private list and reading that list.

No FastAPI and no SQLAlchemy here, the same shape every other service in this
codebase uses.
"""

import uuid

from posts_api.app.models.follow import Account
from posts_api.app.models.post import PostWithAuthor
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.bookmarks import BookmarkRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.services.post_images import PostImages
from posts_api.app.services.posts import post_not_found


class BookmarkService:
    def __init__(
        self,
        bookmarks: BookmarkRepository,
        posts: PostRepository,
        follows: FollowRepository,
        images: PostImages,
    ) -> None:
        self._bookmarks = bookmarks
        self._posts = posts
        self._follows = follows
        self._images = images

    async def save(self, viewer: Account, post_id: uuid.UUID) -> None:
        """Save a post the viewer can read. Saving twice is not an error."""
        # The row points at the account, so the account has to be on the graph
        # before it can save anything, the same bootstrap liking does.
        await self._follows.ensure_profile(viewer)
        if await self._posts.find_visible(post_id, viewer_id=viewer.id) is None:
            raise post_not_found()
        await self._bookmarks.add(viewer.id, post_id)

    async def unsave(self, viewer: Account, post_id: uuid.UUID) -> None:
        """Take the post off the list. The post itself is not looked at."""
        await self._bookmarks.remove(viewer.id, post_id)

    async def list(
        self, viewer: Account, cursor: Cursor | None
    ) -> tuple[list[PostWithAuthor], str | None]:
        posts, next_cursor = await self._posts.saved_by_viewer(viewer.id, cursor=cursor)
        return await self._images.attach(posts), next_cursor
