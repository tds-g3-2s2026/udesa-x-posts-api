"""What the backoffice reads from this service. Any administrator may read it.

Everything hangs from `/admin/posts` because the gateway sends that prefix here,
and `/admin` on its own goes to users-api. A new prefix would need a gateway
route deployed before the backoffice can reach it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from posts_api.api.deps import AdministratorDep, SessionDep
from posts_api.api.posts import ServiceDep
from posts_api.api.schemas.pagination import CursorPage
from posts_api.api.schemas.posts import AccountCountsSummary, PostMetrics
from posts_api.api.schemas.reports import ReportCaseSummary
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.reports import ReportRepository
from posts_api.app.services.account_counts import AccountCountsService
from posts_api.app.services.report_cases import ReportCaseService

router = APIRouter(prefix="/admin/posts", tags=["admin"])


def get_account_counts_service(session: SessionDep) -> AccountCountsService:
    return AccountCountsService(PostRepository(session), FollowRepository(session))


AccountCountsServiceDep = Annotated[AccountCountsService, Depends(get_account_counts_service)]


def get_report_case_service(session: SessionDep) -> ReportCaseService:
    return ReportCaseService(ReportRepository(session))


ReportCaseServiceDep = Annotated[ReportCaseService, Depends(get_report_case_service)]


@router.get("/metrics")
async def post_metrics(
    # With its offset, mandatory: where "today" starts depends on who asks.
    since: Annotated[AwareDatetime, Query()],
    _: AdministratorDep,
    service: ServiceDep,
) -> PostMetrics:
    return PostMetrics(published=await service.count_published_since(since))


@router.get("/accounts/{user_id}/counts")
async def account_counts(
    user_id: uuid.UUID, _: AdministratorDep, service: AccountCountsServiceDep
) -> AccountCountsSummary:
    """Followers and posts of one account, for its detail in the backoffice (E5-H4)."""
    counts = await service.counts_of(user_id)
    return AccountCountsSummary(followers=counts.followers, posts=counts.posts)


@router.get("/reports/cases")
async def report_cases(
    _: AdministratorDep,
    service: ReportCaseServiceDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[ReportCaseSummary]:
    """Accounts with pending reports, the one reported by the most different people
    first (E5-H7 CA.1). Twenty per page, with `nextCursor` for the next one."""
    cases, next_cursor = await service.pending_cases(cursor=cursor)
    return CursorPage(items=[ReportCaseSummary.of(one) for one in cases], next_cursor=next_cursor)
