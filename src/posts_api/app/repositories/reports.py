"""Everything reporting reads and writes in PostgreSQL."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import distinct, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.report import Report, ReportReason
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, CountCursor
from posts_api.infrastructure.database.models import ReportModel, UserProfileModel

PENDING = "pending"


@dataclass(frozen=True)
class ReportCase:
    """One reported account in the backoffice inbox, with what is still pending about it."""

    user_id: uuid.UUID
    handle: str | None
    distinct_reporters: int
    reports: int
    last_reported_at: datetime
    reasons: tuple[ReportReason, ...]


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

    async def pending_cases(
        self, *, cursor: CountCursor | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[list[ReportCase], str | None]:
        """One case per account with pending reports, most different reporters first.

        Ties go to the account reported most recently, and then to the id, so
        the order is total and the cursor neither repeats nor skips a case.
        Accounts users-api already closed are left out: there is nothing left
        to decide about them.
        """
        reporters = func.count(distinct(ReportModel.reporter_id))
        last_reported_at = func.max(ReportModel.created_at)
        statement = (
            select(
                ReportModel.target_id,
                UserProfileModel.handle,
                reporters,
                func.count(),
                last_reported_at,
                func.array_agg(distinct(ReportModel.reason)),
            )
            .join(UserProfileModel, UserProfileModel.id == ReportModel.target_id)
            .where(ReportModel.status == PENDING, UserProfileModel.deleted_at.is_(None))
            .group_by(ReportModel.target_id, UserProfileModel.handle)
        )
        if cursor is not None:
            # In HAVING and not in WHERE: what the cursor remembers are counts
            # over the group, not columns of a row.
            statement = statement.having(
                tuple_(reporters, last_reported_at, ReportModel.target_id)
                < tuple_(cursor.count, cursor.at, cursor.tiebreak)
            )
        statement = statement.order_by(
            reporters.desc(), last_reported_at.desc(), ReportModel.target_id.desc()
        ).limit(limit + 1)

        found = await self._session.execute(statement)
        cases = [
            ReportCase(
                user_id=target_id,
                handle=handle,
                distinct_reporters=distinct_reporters,
                reports=reports,
                last_reported_at=last_at,
                reasons=tuple(sorted(ReportReason(reason) for reason in reasons)),
            )
            for target_id, handle, distinct_reporters, reports, last_at, reasons in found.all()
        ]
        # One past the page was asked for: getting it back is what says there
        # is a next one, the same as `page_of`.
        page = cases[:limit]
        if len(cases) <= limit:
            return page, None
        last = page[-1]
        return page, CountCursor(
            count=last.distinct_reporters, at=last.last_reported_at, tiebreak=last.user_id
        ).encode()
