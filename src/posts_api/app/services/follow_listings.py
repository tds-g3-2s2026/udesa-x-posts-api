"""The rules of the followers and following screens.

A service of its own, alongside `repositories/follow_listings.py`:
`services/follows.py` belongs to this week's protected-account stories, and
touching it here would land two people's changes on the same lines.
"""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, FollowListItem, ProfileVisibility, UserProfile
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.follow_listings import FollowListingRepository
from posts_api.app.repositories.follows import FollowRepository

# A fixed-size suggestion box, not a paginated listing: there is no scenario
# where a client asks for a second page of "who to follow".
SUGGESTED_ACCOUNTS_LIMIT = 10


class FollowListingService:
    def __init__(self, listings: FollowListingRepository, follows: FollowRepository) -> None:
        self._listings = listings
        self._follows = follows

    async def followers_of(
        self, user_id: uuid.UUID, viewer: Account, *, cursor: str | None = None
    ) -> tuple[list[FollowListItem], str | None]:
        await self._authorize(user_id, viewer)
        decoded = Cursor.decode(cursor) if cursor is not None else None
        return await self._listings.followers_of(user_id, viewer_id=viewer.id, cursor=decoded)

    async def following_of(
        self, user_id: uuid.UUID, viewer: Account, *, cursor: str | None = None
    ) -> tuple[list[FollowListItem], str | None]:
        await self._authorize(user_id, viewer)
        decoded = Cursor.decode(cursor) if cursor is not None else None
        return await self._listings.following_of(user_id, viewer_id=viewer.id, cursor=decoded)

    async def suggested_accounts(self, viewer: Account) -> list[UserProfile]:
        """The most-followed accounts the viewer does not already follow."""
        await self._follows.ensure_profile(viewer)
        return await self._follows.suggested_for(viewer.id, limit=SUGGESTED_ACCOUNTS_LIMIT)

    async def _authorize(self, user_id: uuid.UUID, viewer: Account) -> None:
        """Put the viewer on the graph, then decide whether they get to read this account's lists.

        Opening either screen is enough to put the viewer on the graph, the
        same bootstrap the pending-requests screen already does: a profile is
        only created by a request that succeeds, and without this an account
        that never followed anyone could never be followed for the first time.
        It runs before the visibility check, not after, because being refused
        the list should not also cost the caller their spot on the graph.

        A stranger asking about a protected account gets `403`, and not an
        empty list: the account is not secret, only its lists are, so hiding
        that distinction would tell mobile "nobody follows this account" when
        the truth is "you are not allowed to see who does".
        """
        await self._follows.ensure_profile(viewer)

        target = await self._follows.find_profile(user_id)
        if target is None:
            raise ProblemError(
                status=404,
                code="user-not-found",
                title="No se pudo obtener la lista",
                detail="La cuenta no existe",
            )

        if viewer.id == user_id or target.visibility is not ProfileVisibility.PROTECTED:
            return
        if await self._follows.is_following(viewer.id, user_id):
            return

        raise ProblemError(
            status=403,
            code="follow-list-not-visible",
            title="No se pudo obtener la lista",
            detail="Esta cuenta es protegida y no la seguís",
        )
