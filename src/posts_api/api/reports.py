from typing import Annotated

from fastapi import APIRouter, Depends, status

from posts_api.api.deps import CurrentUserDep, RedisDep, SessionDep, UsersApiDep
from posts_api.api.schemas.reports import CreateReportRequest, ReportSummary
from posts_api.app.repositories.account_review import AccountReview
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.reports import ReportRepository
from posts_api.app.services.reports import ReportService
from posts_api.infrastructure.redis.rate_limiter import RedisRateLimiter
from posts_api.infrastructure.users_api.account_review import HttpAccountReview

router = APIRouter(prefix="/reports", tags=["reports"])


def get_account_review(users_api: UsersApiDep) -> AccountReview:
    return HttpAccountReview(users_api)


def get_report_service(
    session: SessionDep,
    redis: RedisDep,
    account_review: Annotated[AccountReview, Depends(get_account_review)],
) -> ReportService:
    return ReportService(
        ReportRepository(session),
        FollowRepository(session),
        PostRepository(session),
        RedisRateLimiter(redis),
        account_review,
    )


ServiceDep = Annotated[ReportService, Depends(get_report_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def report(
    body: CreateReportRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
    service: ServiceDep,
) -> ReportSummary:
    """Report an account, or a post as its author. Who reports comes from the token."""
    created = await service.report(
        current_user, reason=body.reason, user_id=body.user_id, post_id=body.post_id
    )
    # Committed here and not when the request ends: users-api must hear about
    # the review only once the report that triggered it is stored for good.
    await session.commit()
    await service.review_if_due(created.target_id)
    return ReportSummary.of(created)
