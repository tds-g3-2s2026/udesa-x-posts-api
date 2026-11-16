"""The trending hashtags endpoint."""

from fastapi import APIRouter

from posts_api.api.deps import CurrentUserDep, TrendingServiceDep
from posts_api.api.schemas.trending import TrendingTopicResponse

router = APIRouter(prefix="/trending", tags=["trending"])


@router.get("")
async def read_trending(
    _: CurrentUserDep, service: TrendingServiceDep
) -> list[TrendingTopicResponse]:
    """The most used hashtags of the last 24 hours, the same for every viewer."""
    topics = await service.ranking()
    return [TrendingTopicResponse.of(topic) for topic in topics]
