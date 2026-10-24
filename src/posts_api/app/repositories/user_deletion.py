"""What closing an account changes in the data this service keeps about it.

Nothing is deleted from `user_profiles`, `posts` or `reports`: other rows point
at them, and users-api keeps the account as a soft delete too. What goes away is
what the person did with other people: follows, requests, blocks, likes and
retweets. The counters of everyone they touched are corrected in the same
statements, because they are stored columns and not counted on every read.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.infrastructure.database.models import (
    BlockModel,
    FollowModel,
    FollowRequestModel,
    LikeModel,
    PostModel,
    RetweetModel,
    UserProfileModel,
)


class UserDeletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def close(self, user_id: uuid.UUID, at: datetime) -> bool:
        """Mark the account as closed, and say whether this call was the one to do it.

        The row is created when the account never reached this service, so an
        event that arrives first is not lost and `ensure_profile`, which never
        touches `deleted_at`, cannot bring the account back. It is left public:
        its replies stay, and a protected account with no followers would
        otherwise hide them from everybody.
        """
        await self._session.execute(
            insert(UserProfileModel)
            .values(id=user_id)
            .on_conflict_do_nothing(index_elements=[UserProfileModel.id])
        )
        closed = await self._session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id == user_id, UserProfileModel.deleted_at.is_(None))
            .values(deleted_at=at, visibility="public", followers_count=0, following_count=0)
        )
        return closed.rowcount > 0

    async def release_follows(self, user_id: uuid.UUID) -> None:
        """Remove every follow and follow request of the account, in both directions."""
        followed = select(FollowModel.followee_id).where(FollowModel.follower_id == user_id)
        following = select(FollowModel.follower_id).where(FollowModel.followee_id == user_id)
        await self._session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id.in_(followed))
            .values(followers_count=func.greatest(UserProfileModel.followers_count - 1, 0))
        )
        await self._session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id.in_(following))
            .values(following_count=func.greatest(UserProfileModel.following_count - 1, 0))
        )
        await self._session.execute(
            delete(FollowModel).where(
                or_(FollowModel.follower_id == user_id, FollowModel.followee_id == user_id)
            )
        )
        await self._session.execute(
            delete(FollowRequestModel).where(
                or_(
                    FollowRequestModel.requester_id == user_id,
                    FollowRequestModel.target_id == user_id,
                )
            )
        )

    async def release_blocks(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(BlockModel).where(
                or_(BlockModel.blocker_id == user_id, BlockModel.blocked_id == user_id)
            )
        )

    async def release_likes(self, user_id: uuid.UUID) -> None:
        taken = select(LikeModel.post_id).where(LikeModel.user_id == user_id)
        # A deleted post already has its counters at zero, so it is left alone.
        await self._session.execute(
            update(PostModel)
            .where(PostModel.id.in_(taken), PostModel.deleted_at.is_(None))
            .values(likes_count=func.greatest(PostModel.likes_count - 1, 0))
        )
        await self._session.execute(delete(LikeModel).where(LikeModel.user_id == user_id))

    async def release_retweets(self, user_id: uuid.UUID) -> None:
        taken = select(RetweetModel.post_id).where(RetweetModel.user_id == user_id)
        await self._session.execute(
            update(PostModel)
            .where(PostModel.id.in_(taken), PostModel.deleted_at.is_(None))
            .values(retweets_count=func.greatest(PostModel.retweets_count - 1, 0))
        )
        await self._session.execute(delete(RetweetModel).where(RetweetModel.user_id == user_id))
