"""Everything the feed endpoint reads from PostgreSQL.

Its own repository, not a method bolted onto `PostRepository`: the feed joins
`posts` against `follows` and `user_profiles`, a shape none of the other post
reads need.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.post import PostWithAuthor
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, Cursor, apply_cursor, page_of
from posts_api.app.repositories.post_visibility import visible_to
from posts_api.infrastructure.database.models import FollowModel, PostModel, UserProfileModel


class FeedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_viewer(
        self,
        viewer_id: uuid.UUID,
        *,
        cursor: Cursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The posts of whoever `viewer_id` follows, most recent first.

        Restricted to followed authors by the join to `follows`, and to
        visible ones by `visible_to`: the second condition is redundant with
        the first today, because following a protected account already means
        an approved relationship exists, but it is written explicitly and not
        assumed, since this is exactly the filter a later story extends.
        """
        base = (
            select(PostModel, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .join(FollowModel, FollowModel.followee_id == PostModel.author_id)
            .where(
                FollowModel.follower_id == viewer_id,
                visible_to(
                    viewer_id,
                    author_id=PostModel.author_id,
                    author_visibility=UserProfileModel.visibility,
                ),
            )
        )
        statement = apply_cursor(
            base,
            order_by=PostModel.created_at,
            tiebreak_by=PostModel.id,
            cursor=cursor,
            limit=limit,
        )
        found = await self._session.execute(statement)
        posts = [
            PostWithAuthor(
                id=post.id,
                author_id=post.author_id,
                author_handle=handle,
                content=post.content,
                created_at=post.created_at,
                likes_count=post.likes_count,
                retweets_count=post.retweets_count,
                replies_count=post.replies_count,
            )
            for post, handle in found.all()
        ]
        return page_of(
            posts, limit=limit, at=lambda one: one.created_at, tiebreak=lambda one: one.id
        )
