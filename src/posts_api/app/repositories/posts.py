"""Everything the post endpoints need from PostgreSQL.

The service above asks in terms of `Post`/`PostWithAuthor`, from
`app/models/post.py`. Nothing that leaves this file is a SQLAlchemy row, the
same separation `follows` keeps between its repository and its storage model.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.post import Post, PostWithAuthor
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
    )


class PostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, author_id: uuid.UUID, content: str) -> Post:
        row = PostModel(author_id=author_id, content=content)
        self._session.add(row)
        # Flushed so the row gets its id and timestamp from PostgreSQL before
        # the response is built, without closing the transaction.
        await self._session.flush()
        await self._session.refresh(row)
        return _to_post(row)

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
        return PostWithAuthor(
            id=post.id,
            author_id=post.author_id,
            author_handle=handle,
            content=post.content,
            created_at=post.created_at,
            likes_count=post.likes_count,
            retweets_count=post.retweets_count,
            replies_count=post.replies_count,
        )
