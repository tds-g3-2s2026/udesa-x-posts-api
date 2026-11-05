"""The language each account reads its feed in, a copy of what it chose in users-api."""

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from posts_api.infrastructure.database.models import PostModel, UserProfileModel


def in_feed_language_of(viewer_id: uuid.UUID) -> ColumnElement[bool]:
    """Whether the post is in the language `viewer_id` reads, for the query that lists them.

    A post without a known language is shown to everybody: the ones older than
    the detection have NULL, and the ones it could not classify have `other`.

    Read inside the statement so the filter runs before paging, and a page is
    not left short for having had to drop rows afterwards. An account with no
    profile row follows nobody, so it never gets here with posts to filter.
    """
    viewer = aliased(UserProfileModel)
    chosen = select(viewer.feed_language).where(viewer.id == viewer_id).scalar_subquery()
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

        The row is created when the account never reached this service, so what
        it chose before its first request is not lost: `ensure_profile` does
        not touch this column. An event older than the last one applied changes
        nothing, and neither does the same one delivered twice.
        """
        applied = await self._session.execute(
            insert(UserProfileModel)
            .values(id=user_id, feed_language=language, feed_language_at=at)
            .on_conflict_do_update(
                index_elements=[UserProfileModel.id],
                set_={"feed_language": language, "feed_language_at": at},
                where=or_(
                    UserProfileModel.feed_language_at.is_(None),
                    UserProfileModel.feed_language_at < at,
                ),
            )
        )
        return applied.rowcount > 0
