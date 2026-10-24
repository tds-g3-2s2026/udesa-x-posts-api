"""The posts listed on a user's profile (E2-H14).

Its own repository and not a method on `FeedRepository`: the feed reads the
posts of whoever the viewer follows and this reads the posts of one author,
and the two change with different stories.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.post import PostWithAuthor
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, Cursor, apply_cursor, page_of
from posts_api.app.repositories.likes import liked_by
from posts_api.app.repositories.post_visibility import visible_to
from posts_api.infrastructure.database.models import PostModel, UserProfileModel


class ProfilePostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def by_author(
        self,
        author_id: uuid.UUID,
        viewer_id: uuid.UUID,
        *,
        cursor: Cursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The author's posts, most recent first.

        The service already refused a viewer who cannot read this author, but
        `visible_to` stays in the query anyway: a listing of posts that skips
        it is one refactor away from a privacy leak.
        """
        base = (
            select(PostModel, UserProfileModel.handle, liked_by(viewer_id))
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .where(
                PostModel.author_id == author_id,
                # Replies are read from the post they answer, as in the feed.
                PostModel.parent_id.is_(None),
                visible_to(
                    viewer_id,
                    author_id=PostModel.author_id,
                    author_visibility=UserProfileModel.visibility,
                    author_deleted_at=UserProfileModel.deleted_at,
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
                parent_id=post.parent_id,
                liked_by_me=liked,
            )
            for post, handle, liked in found.all()
        ]
        return page_of(
            posts, limit=limit, at=lambda one: one.created_at, tiebreak=lambda one: one.id
        )
