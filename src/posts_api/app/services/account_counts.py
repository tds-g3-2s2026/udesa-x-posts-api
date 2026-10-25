"""The numbers of one account for the backoffice detail screen (E5-H4).

The account itself, its state and its registration date, are users-api's. The
backoffice asks there for those and here for these two numbers, and puts the
screen together.
"""

import uuid
from dataclasses import dataclass

from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository


@dataclass(frozen=True)
class AccountCounts:
    followers: int
    posts: int


class AccountCountsService:
    def __init__(self, posts: PostRepository, follows: FollowRepository) -> None:
        self._posts = posts
        self._follows = follows

    async def counts_of(self, user_id: uuid.UUID) -> AccountCounts:
        """Read on every call, not cached: it is one account per screen, not a
        listing, and a cached counter would drift from the real one.

        An account without a local profile counts zero in both: it never used
        this service, or it was already closed.
        """
        profile = await self._follows.find_profile(user_id)
        if profile is None:
            return AccountCounts(followers=0, posts=0)
        return AccountCounts(
            followers=profile.followers_count,
            posts=await self._posts.count_by_author(user_id),
        )
