"""Everything the post endpoints need from PostgreSQL.

The service above asks in terms of `Post`/`PostWithAuthor`, from
`app/models/post.py`. Nothing that leaves this file is a SQLAlchemy row, the
same separation `follows` keeps between its repository and its storage model.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.post import Post, PostWithAuthor
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, Cursor, apply_cursor, page_of
from posts_api.app.repositories.post_visibility import visible_to
from posts_api.infrastructure.database.models import PostModel, UserProfileModel


def _to_post(row: PostModel) -> Post:
    return Post(
        id=row.id,
        author_id=row.author_id,
        content=row.content,
        created_at=row.created_at,
        likes_count=row.likes_count,
        retweets_count=row.retweets_count,
        replies_count=row.replies_count,
        parent_id=row.parent_id,
    )


def _to_post_with_author(post: PostModel, handle: str | None) -> PostWithAuthor:
    return PostWithAuthor(
        id=post.id,
        author_id=post.author_id,
        author_handle=handle,
        content=post.content,
        created_at=post.created_at,
        likes_count=post.likes_count,
        retweets_count=post.retweets_count,
        replies_count=post.replies_count,
        parent_id=post.parent_id,
    )


class PostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, author_id: uuid.UUID, content: str, *, parent_id: uuid.UUID | None = None
    ) -> Post:
        row = PostModel(author_id=author_id, content=content, parent_id=parent_id)
        self._session.add(row)
        # Flushed so the row gets its id and timestamp from PostgreSQL before
        # the response is built, without closing the transaction.
        await self._session.flush()
        await self._session.refresh(row)
        return _to_post(row)

    async def count_created_since(self, since: datetime) -> int:
        return await self._session.scalar(
            select(func.count()).select_from(PostModel).where(PostModel.created_at >= since)
        )

    async def find_visible(
        self, post_id: uuid.UUID, *, viewer_id: uuid.UUID
    ) -> PostWithAuthor | None:
        """The post, only if `viewer_id` is allowed to read its author's posts.

        A post that exists but is not visible comes back the same as one that
        does not exist at all: the caller turns both into the same `404`, the
        same reasoning `FollowRequestService._required` already uses for
        requests aimed at somebody else.
        """
        found = await self._session.execute(
            select(PostModel, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .where(
                PostModel.id == post_id,
                visible_to(
                    viewer_id,
                    author_id=PostModel.author_id,
                    author_visibility=UserProfileModel.visibility,
                ),
            )
        )
        row = found.first()
        if row is None:
            return None
        post, handle = row
        return _to_post_with_author(post, handle)

    async def count_reply(self, post_id: uuid.UUID) -> None:
        """Add one to the replies counter of the post that was just answered.

        Written as SQL and not read into Python first, for the same reason
        `FollowRepository.move_counters` is: two replies landing together would
        each read the same value and one of them would be lost.
        """
        await self._session.execute(
            update(PostModel)
            .where(PostModel.id == post_id)
            .values(replies_count=PostModel.replies_count + 1)
        )

    async def replies_to(
        self,
        post_id: uuid.UUID,
        *,
        viewer_id: uuid.UUID,
        cursor: Cursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The replies to a post, oldest first, one page at a time.

        Each reply goes through `visible_to` on its own author: the parent being
        readable says nothing about who answered it, and a reply from somebody
        the viewer blocked, or from a protected account they do not follow, must
        not come back just because it hangs from a post they can read.
        """
        base = (
            select(PostModel, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .where(
                PostModel.parent_id == post_id,
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
            ascending=True,
        )
        found = await self._session.execute(statement)
        replies = [_to_post_with_author(post, handle) for post, handle in found.all()]
        return page_of(
            replies, limit=limit, at=lambda one: one.created_at, tiebreak=lambda one: one.id
        )
