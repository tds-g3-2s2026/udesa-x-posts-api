"""Everything the follow endpoint reads and writes in PostgreSQL.

The service above asks in terms of the dataclasses in `app/models/follow.py`.
Nothing that leaves this file is a SQLAlchemy row, so the day the storage
changes, it changes here and nowhere else.
"""

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.follow import Account, ProfileVisibility, UserProfile
from posts_api.infrastructure.database.models import FollowModel, UserProfileModel


def _to_profile(row: UserProfileModel) -> UserProfile:
    """Turn a stored row into the profile the rules are written against."""
    return UserProfile(
        id=row.id,
        handle=row.handle,
        visibility=ProfileVisibility(row.visibility),
        followers_count=row.followers_count,
        following_count=row.following_count,
    )


class FollowRepository:
    """Reads and writes of the social graph, on the session of the request."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_profile(self, user_id: uuid.UUID) -> UserProfile | None:
        row = await self._session.get(UserProfileModel, user_id)
        return _to_profile(row) if row is not None else None

    async def ensure_profile(self, account: Account) -> UserProfile:
        """The profile of whoever is signed in, created the first time they appear.

        No copy of the accounts arrives from users-api yet, so the first
        authenticated request a user makes is what puts them on the graph, with
        the handle the token carries.

        An existing profile only gets its handle filled in when it is missing:
        a handle is fixed at registration and users-api refuses to change it, so
        a stored one can never be out of date, and overwriting it would only
        risk clashing with the unique index for nothing.
        """
        row = await self._session.get(UserProfileModel, account.id)
        if row is None:
            row = UserProfileModel(id=account.id, handle=account.handle)
            self._session.add(row)
            await self._session.flush()
        elif row.handle is None and account.handle is not None:
            row.handle = account.handle
            await self._session.flush()
        return _to_profile(row)

    async def is_following(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
        row = await self._session.get(FollowModel, (follower_id, followee_id))
        return row is not None

    async def add_follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        self._session.add(FollowModel(follower_id=follower_id, followee_id=followee_id))
        await self._session.flush()

    async def remove_follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
        """Delete the relationship and report whether there was one to delete."""
        result = await self._session.execute(
            delete(FollowModel).where(
                FollowModel.follower_id == follower_id,
                FollowModel.followee_id == followee_id,
            )
        )
        return result.rowcount > 0

    async def suggested_for(self, viewer_id: uuid.UUID, *, limit: int) -> list[UserProfile]:
        """The most-followed accounts, for a "who to follow" empty state.

        Excludes the viewer and anyone they already follow: a suggestion that
        would just show "Siguiendo" again is not a suggestion.
        """
        already_followed = select(FollowModel.followee_id).where(
            FollowModel.follower_id == viewer_id
        )
        found = await self._session.execute(
            select(UserProfileModel)
            .where(
                UserProfileModel.id != viewer_id,
                UserProfileModel.id.not_in(already_followed),
            )
            .order_by(UserProfileModel.followers_count.desc(), UserProfileModel.id)
            .limit(limit)
        )
        return [_to_profile(row) for row in found.scalars()]

    async def move_counters(
        self, follower_id: uuid.UUID, followee_id: uuid.UUID, *, by: int
    ) -> None:
        """Add `by` to both sides of the relationship.

        The arithmetic is written as SQL and not read into Python first. Two
        follows arriving at the same time each read the same value if the sum
        happens here, and one of the two increments is lost; `count + 1` inside
        the UPDATE makes the database do the sum over the row it has locked.
        """
        await self._session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id == followee_id)
            .values(followers_count=UserProfileModel.followers_count + by)
        )
        await self._session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id == follower_id)
            .values(following_count=UserProfileModel.following_count + by)
        )
