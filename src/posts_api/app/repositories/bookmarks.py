"""Everything the bookmarks need from PostgreSQL.

The saved list itself is read by `PostRepository.saved_by_viewer`, through the
same visibility rule as every other post listing.
"""

import uuid

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.infrastructure.database.models import BookmarkModel, PostModel


def saved_by(viewer_id: uuid.UUID) -> ColumnElement[bool]:
    """Whether `viewer_id` saved the post a query is reading.

    Correlated to `posts` the same way `liked_by` is, so a query that selects
    posts can add the state of the bookmark button as one more column.
    """
    return (
        select(BookmarkModel.user_id)
        .where(BookmarkModel.user_id == viewer_id, BookmarkModel.post_id == PostModel.id)
        .correlate(PostModel)
        .exists()
    )


class BookmarkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
        """Save the post. Saving it again keeps the original instant.

        `ON CONFLICT DO NOTHING` so the database decides which of two concurrent saves
        inserted the row.
        """
        await self._session.execute(
            insert(BookmarkModel).values(user_id=user_id, post_id=post_id).on_conflict_do_nothing()
        )

    async def remove(self, user_id: uuid.UUID, post_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(BookmarkModel).where(
                BookmarkModel.user_id == user_id, BookmarkModel.post_id == post_id
            )
        )

    async def remove_for_post(self, post_id: uuid.UUID) -> None:
        await self._session.execute(delete(BookmarkModel).where(BookmarkModel.post_id == post_id))
