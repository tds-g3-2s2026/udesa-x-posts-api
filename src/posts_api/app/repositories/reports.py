"""Everything reporting reads and writes in PostgreSQL."""

import uuid

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.report import Report, ReportReason
from posts_api.infrastructure.database.models import ReportModel


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        reporter_id: uuid.UUID,
        target_id: uuid.UUID,
        *,
        reason: ReportReason,
        post_id: uuid.UUID | None,
    ) -> Report:
        row = ReportModel(
            reporter_id=reporter_id, target_id=target_id, post_id=post_id, reason=reason.value
        )
        self._session.add(row)
        # Flushed and refreshed so the id and the timestamp PostgreSQL assigns
        # are there for the response, the same as `PostRepository.create`.
        await self._session.flush()
        await self._session.refresh(row)
        return Report(
            id=row.id,
            reporter_id=row.reporter_id,
            target_id=row.target_id,
            post_id=row.post_id,
            reason=ReportReason(row.reason),
            created_at=row.created_at,
        )

    async def distinct_reporters_of(self, target_id: uuid.UUID) -> int:
        """How many different accounts reported this one, ever.

        Counts reporters and not rows: E3-H5 CA.2 speaks of reports "from
        different accounts", so one account reporting every day still counts
        once.
        """
        found = await self._session.execute(
            select(func.count(distinct(ReportModel.reporter_id))).where(
                ReportModel.target_id == target_id
            )
        )
        return found.scalar_one()
