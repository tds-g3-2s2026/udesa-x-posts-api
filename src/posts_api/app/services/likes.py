"""The rules of liking a post and taking the like back.

No FastAPI and no SQLAlchemy here, the same shape every other service in this
codebase uses.
"""

import uuid

from posts_api.app.models.follow import Account
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.likes import LikeRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.services.posts import post_not_found


class LikeService:
    def __init__(
        self, likes: LikeRepository, posts: PostRepository, follows: FollowRepository
    ) -> None:
        self._likes = likes
        self._posts = posts
        self._follows = follows

    async def like(self, viewer: Account, post_id: uuid.UUID) -> None:
        """Like a post. Liking twice is not an error and does not count twice.

        The client retrying a request it never saw answered gets the same result
        as the first time, which is why this answers the same whether the like
        was new or already there.
        """
        # The row points at the account, so the account has to be on the graph
        # before it can like anything, the same bootstrap posting does.
        await self._follows.ensure_profile(viewer)
        await self._readable(post_id, viewer.id)

        # The counter moves only if the row did, and in the same transaction:
        # a like that was already there must not count a second time.
        if await self._likes.add(viewer.id, post_id):
            await self._likes.move_counter(post_id, by=1)

    async def unlike(self, viewer: Account, post_id: uuid.UUID) -> None:
        """Take the like back. Doing it without one is not an error either."""
        await self._readable(post_id, viewer.id)

        if await self._likes.remove(viewer.id, post_id):
            await self._likes.move_counter(post_id, by=-1)

    async def _readable(self, post_id: uuid.UUID, viewer_id: uuid.UUID) -> None:
        """A post the viewer cannot read cannot be liked, and says so like a missing one."""
        post = await self._posts.lock_visible(post_id, viewer_id=viewer_id)
        if post is None or post.deleted:
            raise post_not_found()
