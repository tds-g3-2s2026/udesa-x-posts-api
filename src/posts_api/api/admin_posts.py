"""Post numbers for the backoffice. Any administrator may read them."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime

from posts_api.api.deps import AdministratorDep, SessionDep
from posts_api.api.posts import ServiceDep
from posts_api.api.schemas.posts import AccountCountsSummary, PostMetrics
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.services.account_counts import AccountCountsService

router = APIRouter(prefix="/admin/posts", tags=["admin"])


def get_account_counts_service(session: SessionDep) -> AccountCountsService:
    return AccountCountsService(PostRepository(session), FollowRepository(session))


AccountCountsServiceDep = Annotated[AccountCountsService, Depends(get_account_counts_service)]


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
    """Followers and posts of one account, for its detail in the backoffice (E5-H4).

    Under `/admin/posts` because the gateway already sends that prefix here, and
    `/admin` on its own goes to users-api.
    """
    counts = await service.counts_of(user_id)
    return AccountCountsSummary(followers=counts.followers, posts=counts.posts)
