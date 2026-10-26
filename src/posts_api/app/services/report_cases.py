"""The backoffice side of the reports: the cases an administrator decides (E5-H7).

Apart from `reports.py`, which is how a user reports another and when an
account goes under review. A case is every pending report about one account:
the inbox shows accounts, as the story speaks of reports "of the same user".

No FastAPI and no SQLAlchemy here, the same shape `ReportService` uses.
"""

from posts_api.app.pagination import CountCursor
from posts_api.app.repositories.reports import ReportCase, ReportRepository


class ReportCaseService:
    def __init__(self, reports: ReportRepository) -> None:
        self._reports = reports

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
