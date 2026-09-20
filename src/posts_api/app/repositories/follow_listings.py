"""Reads for the followers and following screens.

A repository of its own, separate from `repositories/follows.py`: that file
belongs to this week's protected-account stories, and editing it here would
land two people's changes on the same lines.
"""

import uuid

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from posts_api.app.models.follow import FollowListItem
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, Cursor, apply_cursor, page_of
from posts_api.infrastructure.database.models import FollowModel, UserProfileModel


class FollowListingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def followers_of(
        self,
        user_id: uuid.UUID,
        *,
        viewer_id: uuid.UUID,
        cursor: Cursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[FollowListItem], str | None]:
        """Whoever follows `user_id`, most recent relationship first."""
        return await self._list(
            account_filter=FollowModel.followee_id == user_id,
            other_id=FollowModel.follower_id,
            viewer_id=viewer_id,
            cursor=cursor,
            limit=limit,
        )

    async def following_of(
        self,
        user_id: uuid.UUID,
        *,
        viewer_id: uuid.UUID,
        cursor: Cursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[FollowListItem], str | None]:
        """Whoever `user_id` follows, most recent relationship first."""
        return await self._list(
            account_filter=FollowModel.follower_id == user_id,
            other_id=FollowModel.followee_id,
            viewer_id=viewer_id,
            cursor=cursor,
            limit=limit,
        )

    async def _list(
        self,
        *,
        account_filter: ColumnElement,
        other_id: InstrumentedAttribute,
        viewer_id: uuid.UUID,
        cursor: Cursor | None,
        limit: int,
    ) -> tuple[list[FollowListItem], str | None]:
        """Followers and following are the same query with the two columns swapped.

        `other_id` is whichever column names the account the screen shows: the
        follower on the followers screen, the followee on the following one.
        It doubles as the cursor's tiebreak, because it is what makes each row
        of a page unique once `created_at` is fixed.
        """
        base = (
            select(other_id.label("account_id"), FollowModel.created_at, UserProfileModel.handle)
            .select_from(FollowModel)
            .join(UserProfileModel, UserProfileModel.id == other_id)
            .where(account_filter)
        )
        statement = apply_cursor(
            base,
            order_by=FollowModel.created_at,
            tiebreak_by=other_id,
            cursor=cursor,
            limit=limit,
        )
        found = await self._session.execute(statement)
        rows = found.all()

        already_followed = await self._followed_by_viewer(
            viewer_id, {row.account_id for row in rows}
        )
        items = [
            FollowListItem(
                id=row.account_id,
                handle=row.handle,
                followed_by_viewer=row.account_id in already_followed,
                created_at=row.created_at,
            )
            for row in rows
        ]
        return page_of(
            items, limit=limit, at=lambda one: one.created_at, tiebreak=lambda one: one.id
        )

    async def _followed_by_viewer(
        self, viewer_id: uuid.UUID, account_ids: set[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Which of these accounts the viewer follows already, one query instead of one per row."""
        if not account_ids:
            return set()
        found = await self._session.execute(
            select(FollowModel.followee_id).where(
                FollowModel.follower_id == viewer_id,
                FollowModel.followee_id.in_(account_ids),
            )
        )
        return set(found.scalars())
