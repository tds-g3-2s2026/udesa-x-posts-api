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
from posts_api.app.repositories.likes import liked_by
from posts_api.app.repositories.post_visibility import visible_to
from posts_api.app.repositories.retweets import retweeted_by
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


def _to_post_with_author(
    post: PostModel,
    handle: str | None,
    author_deleted_at: datetime | None,
    liked: bool,
    retweeted: bool,
) -> PostWithAuthor:
    return PostWithAuthor(
        id=post.id,
        author_id=post.author_id,
        # A closed account does not keep its handle on what it left behind.
        author_handle=None if author_deleted_at else handle,
        author_deleted=author_deleted_at is not None,
        content=None if post.deleted_at else post.content,
        deleted=post.deleted_at is not None,
        created_at=post.created_at,
        likes_count=0 if post.deleted_at else post.likes_count,
        retweets_count=0 if post.deleted_at else post.retweets_count,
        replies_count=post.replies_count,
        parent_id=post.parent_id,
        liked_by_me=liked and post.deleted_at is None,
        retweeted_by_me=retweeted and post.deleted_at is None,
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

    async def search(
        self, query: str, viewer_id: uuid.UUID, *, cursor: Cursor | None
    ) -> tuple[list[PostWithAuthor], str | None]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = (
            select(PostModel, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .where(
                PostModel.content.ilike(f"%{escaped}%", escape="\\"),
                PostModel.deleted_at.is_(None),
                visible_to(
                    viewer_id,
                    author_id=PostModel.author_id,
                    author_visibility=UserProfileModel.visibility,
                    author_deleted_at=UserProfileModel.deleted_at,
                ),
            )
        )
        rows = await self._session.execute(
            apply_cursor(
                statement, order_by=PostModel.created_at, tiebreak_by=PostModel.id, cursor=cursor
            )
        )
        posts = [_to_post_with_author(post, handle, None, False, False) for post, handle in rows]
        return page_of(
            posts,
            limit=DEFAULT_PAGE_SIZE,
            at=lambda post: post.created_at,
            tiebreak=lambda post: post.id,
        )

    async def count_created_since(self, since: datetime) -> int:
        return await self._session.scalar(
            select(func.count()).select_from(PostModel).where(PostModel.created_at >= since)
        )

    async def count_by_author(self, author_id: uuid.UUID) -> int:
        """The author's posts that were not deleted, replies included."""
        return await self._session.scalar(
            select(func.count())
            .select_from(PostModel)
            .where(PostModel.author_id == author_id, PostModel.deleted_at.is_(None))
        )

    async def find_visible(
        self, post_id: uuid.UUID, *, viewer_id: uuid.UUID, include_deleted: bool = False
    ) -> PostWithAuthor | None:
        """The post, only if `viewer_id` is allowed to read its author's posts.

        A post that exists but is not visible comes back the same as one that
        does not exist at all: the caller turns both into the same `404`, the
        same reasoning `FollowRequestService._required` already uses for
        requests aimed at somebody else.
        """
        found = await self._session.execute(
            select(
                PostModel,
                UserProfileModel.handle,
                UserProfileModel.deleted_at,
                liked_by(viewer_id),
                retweeted_by(viewer_id),
            )
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .where(
                PostModel.id == post_id,
                True if include_deleted else PostModel.deleted_at.is_(None),
                visible_to(
                    viewer_id,
                    author_id=PostModel.author_id,
                    author_visibility=UserProfileModel.visibility,
                    author_deleted_at=UserProfileModel.deleted_at,
                    keeps_deleted_author=PostModel.parent_id.is_not(None),
                ),
            )
        )
        row = found.first()
        if row is None:
            return None
        post, handle, author_deleted_at, liked, retweeted = row
        return _to_post_with_author(post, handle, author_deleted_at, liked, retweeted)

    async def lock_visible(
        self, post_id: uuid.UUID, *, viewer_id: uuid.UUID
    ) -> PostWithAuthor | None:
        """Lock the post before checking its current state or changing its relations."""
        await self._session.execute(
            select(PostModel.id).where(PostModel.id == post_id).with_for_update()
        )
        return await self.find_visible(post_id, viewer_id=viewer_id, include_deleted=True)

    async def mark_deleted(self, post_id: uuid.UUID) -> None:
        await self._session.execute(
            update(PostModel)
            .where(PostModel.id == post_id, PostModel.deleted_at.is_(None))
            .values(deleted_at=func.clock_timestamp(), likes_count=0, retweets_count=0)
        )

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
            select(
                PostModel,
                UserProfileModel.handle,
                UserProfileModel.deleted_at,
                liked_by(viewer_id),
                retweeted_by(viewer_id),
            )
            .join(UserProfileModel, UserProfileModel.id == PostModel.author_id)
            .where(
                PostModel.parent_id == post_id,
                visible_to(
                    viewer_id,
                    author_id=PostModel.author_id,
                    author_visibility=UserProfileModel.visibility,
                    author_deleted_at=UserProfileModel.deleted_at,
                    # Every row here is a reply: the ones of a closed account stay.
                    keeps_deleted_author=PostModel.parent_id.is_not(None),
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
        replies = [
            _to_post_with_author(post, handle, author_deleted_at, liked, retweeted)
            for post, handle, author_deleted_at, liked, retweeted in found.all()
        ]
        return page_of(
            replies, limit=limit, at=lambda one: one.created_at, tiebreak=lambda one: one.id
        )
