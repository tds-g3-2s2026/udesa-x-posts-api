"""Everything muting reads and writes in PostgreSQL."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.follow import MutedAccount
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, Cursor, apply_cursor, page_of
from posts_api.infrastructure.database.models import MuteModel, UserProfileModel


class MuteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, muter_id: uuid.UUID, muted_id: uuid.UUID) -> None:
        """Record the mute. Muting twice leaves the first one as it was.

        `ON CONFLICT DO NOTHING` instead of reading first, for the same reason
        as blocks: two taps arriving together would both read "not muted".
        """
        await self._session.execute(
            insert(MuteModel).values(muter_id=muter_id, muted_id=muted_id).on_conflict_do_nothing()
        )

    async def remove(self, muter_id: uuid.UUID, muted_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(MuteModel).where(MuteModel.muter_id == muter_id, MuteModel.muted_id == muted_id)
        )

    async def muted_by(
        self,
        muter_id: uuid.UUID,
        *,
        cursor: Cursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[MutedAccount], str | None]:
        """The accounts `muter_id` muted, most recent first."""
        base = (
            select(MuteModel.muted_id, MuteModel.created_at, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == MuteModel.muted_id)
            .where(MuteModel.muter_id == muter_id)
        )
        statement = apply_cursor(
            base,
            order_by=MuteModel.created_at,
            tiebreak_by=MuteModel.muted_id,
            cursor=cursor,
            limit=limit,
        )
        found = await self._session.execute(statement)
        rows = [
            MutedAccount(id=muted_id, handle=handle, created_at=created_at)
            for muted_id, created_at, handle in found.all()
        ]
        return page_of(
            rows, limit=limit, at=lambda one: one.created_at, tiebreak=lambda one: one.id
        )
