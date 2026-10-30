"""Everything muting reads and writes in PostgreSQL."""

import uuid

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.infrastructure.database.models import MuteModel


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
