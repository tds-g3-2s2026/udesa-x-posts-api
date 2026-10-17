"""Everything the retweets need from PostgreSQL.

The counter on the post and the row that justifies it are written through the
same repository, on the session of the request, so the service can move both
in one transaction.
"""

import uuid

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.infrastructure.database.models import PostModel, RetweetModel


def retweeted_by(viewer_id: uuid.UUID) -> ColumnElement[bool]:
    """Whether `viewer_id` already retweeted the post a query is reading.

    A value computed per viewer and not a column: the same post is retweeted for
    one reader and not for the next. Correlated to `posts` on purpose, so any
    query that selects posts can add it as one more column and the screen gets
    the state of the button without a second call per row.
    """
    return (
        select(RetweetModel.user_id)
        .where(RetweetModel.user_id == viewer_id, RetweetModel.post_id == PostModel.id)
        .correlate(PostModel)
        .exists()
    )


class RetweetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
        """Record the retweet and report whether it was new.

        `ON CONFLICT DO NOTHING` and not a read followed by an insert: two
        requests from the same account arriving together would both read "no
        retweet yet" and one of them would fail on the primary key. This way the
        database decides which one inserted, and only that one reports `True`.
        """
        result = await self._session.execute(
            insert(RetweetModel).values(user_id=user_id, post_id=post_id).on_conflict_do_nothing()
        )
        return result.rowcount > 0

    async def remove(self, user_id: uuid.UUID, post_id: uuid.UUID) -> bool:
        """Delete the retweet and report whether there was one to delete."""
        result = await self._session.execute(
            delete(RetweetModel).where(
                RetweetModel.user_id == user_id, RetweetModel.post_id == post_id
            )
        )
        return result.rowcount > 0

    async def move_counter(self, post_id: uuid.UUID, *, by: int) -> None:
        """Add `by` to the retweets of the post.

        The sum is written as SQL and not read into Python first, for the same
        reason `FollowRepository.move_counters` does it: two retweets landing
        together would read the same value and one would be lost.
        """
        await self._session.execute(
            update(PostModel)
            .where(PostModel.id == post_id)
            .values(retweets_count=func.greatest(0, PostModel.retweets_count + by))
        )
