"""The accounts that posts mention, read back for the posts a screen is about to show."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.mentions import Mention
from posts_api.infrastructure.database.models import PostMentionModel, UserProfileModel


class PostMentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_posts(self, post_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[Mention]]:
        """The mentions of every one of those posts, in a single query.

        Only the accounts that exist today: one closed after the post was written
        stays in the table, but the app must not link to a profile that is gone.
        """
        found = await self._session.execute(
            select(PostMentionModel.post_id, UserProfileModel.id, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == PostMentionModel.user_id)
            .where(
                PostMentionModel.post_id.in_(list(post_ids)),
                UserProfileModel.deleted_at.is_(None),
                UserProfileModel.handle.is_not(None),
            )
            .order_by(PostMentionModel.post_id, UserProfileModel.handle)
        )
        by_post: dict[uuid.UUID, list[Mention]] = {}
        for post_id, account_id, handle in found:
            by_post.setdefault(post_id, []).append(
                Mention(id=account_id, handle=handle.removeprefix("@"))
            )
        return by_post
