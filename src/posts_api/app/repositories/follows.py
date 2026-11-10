"""Everything the follow endpoint reads and writes in PostgreSQL.

The service above asks in terms of the dataclasses in `app/models/follow.py`.
Nothing that leaves this file is a SQLAlchemy row, so the day the storage
changes, it changes here and nowhere else.
"""

import uuid
from datetime import datetime

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
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
        avatar_key=row.avatar_key,
        cover_key=row.cover_key,
    )


class FollowRepository:
    """Reads and writes of the social graph, on the session of the request."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_profile(self, user_id: uuid.UUID) -> UserProfile | None:
        """The account, or None when it is unknown or already closed.

        A closed account is answered like one that never existed, so every
        route that starts from this lookup refuses it with the same 404.
        """
        row = await self._session.get(UserProfileModel, user_id)
        if row is None or row.deleted_at is not None:
            return None
        return _to_profile(row)

    async def profile_is_deleted(self, user_id: uuid.UUID) -> bool:
        row = await self._session.get(UserProfileModel, user_id)
        return row is not None and row.deleted_at is not None

    async def create_profile_if_missing(self, account: Account) -> UserProfile | None:
        """Make the profile from what users-api just said, or complete the one an event made.

        A profile made by a visibility event has no handle. Here the handle is
        filled in, and the visibility is left alone: the event is what keeps it
        in step, and this lookup could be older than the last one applied.
        """
        await self._session.execute(
            insert(UserProfileModel)
            .values(
                id=account.id, handle=account.handle, visibility=account.profile_visibility.value
            )
            .on_conflict_do_update(
                index_elements=[UserProfileModel.id],
                set_={"handle": account.handle},
                where=UserProfileModel.handle.is_(None),
            )
        )
        return await self.find_profile(account.id)

    async def ensure_profile(self, account: Account) -> UserProfile:
        """The profile of whoever is signed in, created the first time they appear.

        The token only creates a missing profile, with the visibility it carries.
        It never rewrites a stored one: the token is up to 15 minutes old, and a
        change that already arrived by event would be undone by it. From then on
        the visibility is whatever the last event said (`apply_visibility`).

        The handle only ever gets filled in once, not kept in sync: a handle
        is fixed at registration and users-api refuses to change it, so a
        stored one can never be out of date.
        """
        await self._session.execute(
            insert(UserProfileModel)
            .values(
                id=account.id,
                handle=account.handle,
                visibility=(account.profile_visibility or ProfileVisibility.PUBLIC).value,
            )
            .on_conflict_do_nothing(index_elements=[UserProfileModel.id])
        )
        row = await self._session.get(UserProfileModel, account.id)
        if row.handle is None and account.handle is not None:
            row.handle = account.handle
            await self._session.flush()
        return _to_profile(row)

    async def apply_visibility(
        self, user_id: uuid.UUID, visibility: ProfileVisibility, at: datetime
    ) -> bool:
        """Keep the visibility, and say whether this change was newer than the stored one.

        An event older than the last one applied changes nothing, and neither
        does the same one delivered twice. A closed account is left as it is:
        it stays public so its replies are not hidden.

        The profile is made when the account never reached this service, so an
        event that arrives first is not lost. It has no handle, which the first
        request of its owner fills in, and the visibility it carries is the real
        one, not a default.
        """
        applied = await self._session.execute(
            insert(UserProfileModel)
            .values(id=user_id, visibility=visibility.value, visibility_changed_at=at)
            .on_conflict_do_update(
                index_elements=[UserProfileModel.id],
                set_={"visibility": visibility.value, "visibility_changed_at": at},
                where=and_(
                    UserProfileModel.deleted_at.is_(None),
                    or_(
                        UserProfileModel.visibility_changed_at.is_(None),
                        UserProfileModel.visibility_changed_at < at,
                    ),
                ),
            )
        )
        return applied.rowcount > 0

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
                UserProfileModel.deleted_at.is_(None),
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
