"""The language each account reads its feed in, a copy of what it chose in users-api."""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.infrastructure.database.models import FeedPreferenceModel, PostModel


def in_feed_language_of(viewer_id: uuid.UUID) -> ColumnElement[bool]:
    """Whether the post is in the language `viewer_id` reads, for the query that lists them.

    A post without a known language is shown to everybody: the ones older than
    the detection have NULL, and the ones it could not classify have `other`. So
    is everything to an account that never chose.

    Read inside the statement so the filter runs before paging, and a page is
    not left short for having had to drop rows afterwards.
    """
    chosen = func.coalesce(
        select(FeedPreferenceModel.language)
        .where(FeedPreferenceModel.user_id == viewer_id)
        .scalar_subquery(),
        "all",
    )
    return or_(
        PostModel.language.is_(None),
        PostModel.language == "other",
        chosen == "all",
        PostModel.language == chosen,
    )


class FeedLanguageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def apply(self, user_id: uuid.UUID, language: str, at: datetime) -> bool:
        """Keep the language, and say whether this change was newer than the stored one.

        An event older than the last one applied changes nothing, and neither
        does the same one delivered twice.
        """
        applied = await self._session.execute(
            insert(FeedPreferenceModel)
            .values(user_id=user_id, language=language, changed_at=at)
            .on_conflict_do_update(
                index_elements=[FeedPreferenceModel.user_id],
                set_={"language": language, "changed_at": at},
                where=FeedPreferenceModel.changed_at < at,
            )
        )
        return applied.rowcount > 0
