"""Everything the follow endpoint reads and writes in PostgreSQL.

The service above asks in terms of the dataclasses in `app/models/follow.py`.
Nothing that leaves this file is a SQLAlchemy row, so the day the storage
changes, it changes here and nowhere else.
"""

import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.follow import ProfileVisibility, UserProfile
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

    async def ensure_profile(self, user_id: uuid.UUID) -> UserProfile:
        """The profile of whoever is signed in, created the first time they appear.

        No copy of the accounts arrives from users-api yet, so the first
        authenticated request a user makes is what puts them on the graph. The
        handle stays empty until that copy exists.
        """
        row = await self._session.get(UserProfileModel, user_id)
        if row is None:
            row = UserProfileModel(id=user_id)
            self._session.add(row)
            await self._session.flush()
        return _to_profile(row)

    async def is_following(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
        row = await self._session.get(FollowModel, (follower_id, followee_id))
        return row is not None

    async def add_follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        self._session.add(FollowModel(follower_id=follower_id, followee_id=followee_id))
        await self._session.flush()

    async def remove_follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(FollowModel).where(
                FollowModel.follower_id == follower_id,
                FollowModel.followee_id == followee_id,
            )
        )
