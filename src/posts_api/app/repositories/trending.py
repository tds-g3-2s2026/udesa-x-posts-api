"""The trending ranking, read from PostgreSQL.

Counts over every viewer alike: the visibility rule of `post_visibility.py`
depends on the viewer, so it is not used here. Only the author's own columns
decide which posts count.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.trending import TrendingTopic
from posts_api.infrastructure.database.models import PostHashtagModel, PostModel, UserProfileModel


class TrendingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def top(self, *, since: datetime, limit: int) -> list[TrendingTopic]:
        """The hashtags of the posts created since `since`, most used first, ties by tag."""
        uses = func.count(PostHashtagModel.post_id)
        statement = (
            select(PostHashtagModel.tag, uses)
            .join(PostModel, PostModel.id == PostHashtagModel.post_id)
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .where(
                PostModel.created_at >= since,
                PostModel.deleted_at.is_(None),
                UserProfileModel.deleted_at.is_(None),
                UserProfileModel.visibility == "public",
            )
            .group_by(PostHashtagModel.tag)
            .order_by(uses.desc(), PostHashtagModel.tag)
            .limit(limit)
        )
        rows = await self._session.execute(statement)
        return [TrendingTopic(tag=tag, count=count) for tag, count in rows]
