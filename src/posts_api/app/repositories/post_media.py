"""The images attached to posts, as rows. The files themselves are in the storage."""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.infrastructure.database.models import PostMediaModel


@dataclass(frozen=True)
class NewMedia:
    key: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class StoredMedia:
    id: uuid.UUID
    key: str
    position: int


class PostMediaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, post_id: uuid.UUID, media: Sequence[NewMedia]) -> list[StoredMedia]:
        """Attach the files to the post, in the order given: that order is the position."""
        rows = [
            PostMediaModel(
                post_id=post_id,
                position=position,
                s3_key=one.key,
                mime_type=one.mime_type,
                size_bytes=one.size_bytes,
            )
            for position, one in enumerate(media)
        ]
        self._session.add_all(rows)
        # Flushed so PostgreSQL hands out the ids before the response is built.
        await self._session.flush()
        return [StoredMedia(row.id, row.s3_key, row.position) for row in rows]

    async def for_posts(self, post_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[StoredMedia]]:
        """The images of every one of those posts, in a single query."""
        found = await self._session.execute(
            select(PostMediaModel)
            .where(PostMediaModel.post_id.in_(list(post_ids)))
            .order_by(PostMediaModel.post_id, PostMediaModel.position)
        )
        by_post: dict[uuid.UUID, list[StoredMedia]] = {}
        for row in found.scalars():
            by_post.setdefault(row.post_id, []).append(
                StoredMedia(row.id, row.s3_key, row.position)
            )
        return by_post
