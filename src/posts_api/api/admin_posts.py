"""Post numbers for the backoffice dashboard. Any administrator may read them."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from posts_api.api.deps import AdministratorDep
from posts_api.api.posts import ServiceDep
from posts_api.api.schemas.posts import PostMetrics

router = APIRouter(prefix="/admin/posts", tags=["admin"])


@router.get("/metrics")
async def post_metrics(
    # With its offset, mandatory: where "today" starts depends on who asks.
    since: Annotated[AwareDatetime, Query()],
    _: AdministratorDep,
    service: ServiceDep,
) -> PostMetrics:
    return PostMetrics(published=await service.count_published_since(since))
