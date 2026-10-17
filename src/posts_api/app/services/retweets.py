"""Share readable posts and undo shares in the request transaction."""

import uuid

from posts_api.app.models.follow import Account
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.retweets import RetweetRepository
from posts_api.app.services.posts import post_not_found


class RetweetService:
    def __init__(
        self, retweets: RetweetRepository, posts: PostRepository, follows: FollowRepository
    ) -> None:
        self._retweets = retweets
        self._posts = posts
        self._follows = follows

    async def retweet(self, viewer: Account, post_id: uuid.UUID) -> bool:
        """Return whether the request created a new share."""
        await self._follows.ensure_profile(viewer)
        await self._readable(post_id, viewer.id)

        # The counter moves only if the row did, and in the same transaction:
        # a retweet that was already there must not count a second time.
        created = await self._retweets.add(viewer.id, post_id)
        if created:
            await self._retweets.move_counter(post_id, by=1)
        return created

    async def unretweet(self, viewer: Account, post_id: uuid.UUID) -> None:
        """Take the retweet back. Doing it without one is not an error either."""
        await self._readable(post_id, viewer.id)

        if await self._retweets.remove(viewer.id, post_id):
            await self._retweets.move_counter(post_id, by=-1)

    async def _readable(self, post_id: uuid.UUID, viewer_id: uuid.UUID) -> None:
        """Unreadable and missing posts produce the same response."""
        post = await self._posts.lock_visible(post_id, viewer_id=viewer_id)
        if post is None or post.deleted:
            raise post_not_found()
