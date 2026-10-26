"""Everything blocking reads and writes in PostgreSQL.

Shares the session of the request with `FollowRepository` and
`FollowRequestRepository`, so the block and everything it tears down land in
one transaction.
"""

import uuid

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.follow import BlockedAccount
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, Cursor, apply_cursor, page_of
from posts_api.infrastructure.database.models import BlockModel, UserProfileModel


class BlockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> bool:
        """Record the block, and report whether it is new.

        `ON CONFLICT DO NOTHING` instead of reading first: two taps on the
        button arriving together would both read "not blocked", and the second
        insert would fail on the primary key.
        """
        result = await self._session.execute(
            insert(BlockModel)
            .values(blocker_id=blocker_id, blocked_id=blocked_id)
            .on_conflict_do_nothing()
        )
        return result.rowcount > 0

    async def remove(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(BlockModel).where(
                BlockModel.blocker_id == blocker_id, BlockModel.blocked_id == blocked_id
            )
        )

    async def has_blocked(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> bool:
        row = await self._session.get(BlockModel, (blocker_id, blocked_id))
        return row is not None

    async def excluded_ids(
        self, viewer_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> list[uuid.UUID]:
        rows = await self._session.execute(
            select(BlockModel.blocker_id, BlockModel.blocked_id).where(
                or_(
                    and_(BlockModel.blocker_id == viewer_id, BlockModel.blocked_id.in_(user_ids)),
                    and_(BlockModel.blocked_id == viewer_id, BlockModel.blocker_id.in_(user_ids)),
                )
            )
        )
        return sorted({blocked if blocker == viewer_id else blocker for blocker, blocked in rows})

    async def blocked_by(
        self,
        blocker_id: uuid.UUID,
        *,
        cursor: Cursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[BlockedAccount], str | None]:
        """The accounts `blocker_id` blocked, most recent first."""
        base = (
            select(BlockModel.blocked_id, BlockModel.created_at, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == BlockModel.blocked_id)
            .where(BlockModel.blocker_id == blocker_id)
        )
        statement = apply_cursor(
            base,
            order_by=BlockModel.created_at,
            tiebreak_by=BlockModel.blocked_id,
            cursor=cursor,
            limit=limit,
        )
        found = await self._session.execute(statement)
        rows = [
            BlockedAccount(id=blocked_id, handle=handle, created_at=created_at)
            for blocked_id, created_at, handle in found.all()
        ]
        return page_of(
            rows, limit=limit, at=lambda one: one.created_at, tiebreak=lambda one: one.id
        )
