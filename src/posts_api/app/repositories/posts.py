"""Everything the post-creation endpoint needs from PostgreSQL.

The service above asks in terms of `Post`, from `app/models/post.py`. Nothing
that leaves this file is a SQLAlchemy row, the same separation `follows` keeps
between its repository and its storage model.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.post import Post
from posts_api.infrastructure.database.models import PostModel


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
