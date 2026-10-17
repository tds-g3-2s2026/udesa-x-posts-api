"""Everything the likes need from PostgreSQL.

The counter on the post and the row that justifies it are written through the
same repository, on the session of the request, so the service can move both
in one transaction.
"""

import uuid

from sqlalchemy import ColumnElement, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.infrastructure.database.models import LikeModel, PostModel


def liked_by(viewer_id: uuid.UUID) -> ColumnElement[bool]:
    """Whether `viewer_id` already liked the post a query is reading.

    A value computed per viewer and not a column: the same post is liked for
    one reader and not for the next. Correlated to `posts` on purpose, so any
    query that selects posts can add it as one more column and the screen gets
    the state of the button without a second call per row.
    """
    return (
        select(LikeModel.user_id)
        .where(LikeModel.user_id == viewer_id, LikeModel.post_id == PostModel.id)
        .correlate(PostModel)
        .exists()
    )


class LikeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
        """Record the like and report whether it was new.

        `ON CONFLICT DO NOTHING` and not a read followed by an insert: two
        requests from the same account arriving together would both read "no
        like yet" and one of them would fail on the primary key. This way the
        database decides which one inserted, and only that one reports `True`.
        """
        result = await self._session.execute(
            insert(LikeModel).values(user_id=user_id, post_id=post_id).on_conflict_do_nothing()
        )
        return result.rowcount > 0

    async def remove(self, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
        """Delete the like and report whether there was one to delete."""
        result = await self._session.execute(
            delete(LikeModel).where(LikeModel.user_id == user_id, LikeModel.post_id == post_id)
        )
        return result.rowcount > 0

    async def move_counter(self, post_id: uuid.UUID, *, by: int) -> None:
        """Add `by` to the likes of the post.

        The sum is written as SQL and not read into Python first, for the same
        reason `FollowRepository.move_counters` does it: two likes landing
        together would read the same value and one would be lost.
        """
        await self._session.execute(
            update(PostModel)
            .where(PostModel.id == post_id)
            .values(likes_count=PostModel.likes_count + by)
        )
