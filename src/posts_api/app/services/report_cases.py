"""The backoffice side of the reports: the cases an administrator decides (E5-H7).

Apart from `reports.py`, which is how a user reports another and when an
account goes under review. A case is every pending report about one account:
the inbox shows accounts, as the story speaks of reports "of the same user".

No FastAPI and no SQLAlchemy here, the same shape `ReportService` uses.
"""

import uuid
from datetime import UTC, datetime

from posts_api.app.errors import ProblemError
from posts_api.app.events import admin_action_recorded
from posts_api.app.models.report import ReportStatus
from posts_api.app.pagination import CountCursor
from posts_api.app.repositories.account_review import ReviewRelease, ReviewReleaseUnavailableError
from posts_api.app.repositories.administrator_directory import (
    AdministratorDirectory,
    AdministratorDirectoryUnavailableError,
)
from posts_api.app.repositories.outbox import OutboxRepository
from posts_api.app.repositories.reports import ReportCase, ReportRepository

REPORT_DISMISSED = "report.dismissed"
REPORT_RESOLVED = "report.resolved"


class ReportCaseService:
    def __init__(
        self,
        reports: ReportRepository,
        release: ReviewRelease,
        administrators: AdministratorDirectory,
        outbox: OutboxRepository,
    ) -> None:
        self._reports = reports
        self._release = release
        self._administrators = administrators
        self._outbox = outbox

    async def pending_cases(
        self, *, cursor: str | None = None
    ) -> tuple[list[ReportCase], str | None]:
        """The inbox, the account reported by the most different people first (CA.1).

        Different people and not reports: one person may report the same
        account once a day (E3-H5 CA.3), so counting rows would put first
        whoever insists the most. It is the same measure ADR-011 uses for the
        review threshold.
        """
        decoded = CountCursor.decode(cursor) if cursor is not None else None
        return await self._reports.pending_cases(cursor=decoded)

    async def dismiss(self, administrator_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """The reports were unfounded: they leave the inbox and the account is released (CA.2)."""
        await self._close(administrator_id, user_id, ReportStatus.DISMISSED, REPORT_DISMISSED)

    async def resolve(self, administrator_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """The case was dealt with: its reports become resolved and leave the inbox (CA.3).

        "Suspender" in the inbox blocks the account in users-api first and then
        resolves; the release below leaves a suspended account as it is.
        """
        await self._close(administrator_id, user_id, ReportStatus.RESOLVED, REPORT_RESOLVED)

    async def _close(
        self,
        administrator_id: uuid.UUID,
        user_id: uuid.UUID,
        status: ReportStatus,
        action: str,
    ) -> None:
        """Close the pending reports, release the account and record who did it.

        Runs inside the request's transaction: nothing is committed until it
        returns, so a release that fails leaves every report pending for the
        administrator to try again (ADR-020).
        """
        if not await self._reports.has_pending(user_id):
            return
        try:
            actor_email = await self._administrators.email_of(administrator_id)
        except AdministratorDirectoryUnavailableError as error:
            raise ProblemError(
                status=503,
                code="users-api-unavailable",
                title="No se pudo cerrar el caso",
                detail="No se pudo obtener la identidad del administrador. Probá de nuevo",
            ) from error

        now = datetime.now(UTC)
        closed = await self._reports.close_pending(
            user_id, status=status, decided_by=administrator_id, decided_at=now
        )
        if closed == 0:
            # Nothing pending: the case was already closed, by this administrator
            # a moment ago or by another one. Same answer, nothing to record.
            return

        try:
            await self._release.lift_review(user_id)
        except ReviewReleaseUnavailableError as error:
            raise ProblemError(
                status=503,
                code="users-api-unavailable",
                title="No se pudo cerrar el caso",
                detail="No se pudo levantar la revisión de la cuenta. Probá de nuevo en un momento",
            ) from error

        await self._outbox.add(
            admin_action_recorded(
                administrator_id,
                actor_email,
                action,
                user_id,
                closed,
                now=now,
            )
        )
