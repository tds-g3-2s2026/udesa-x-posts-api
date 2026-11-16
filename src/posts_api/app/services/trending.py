"""The trending ranking: the hashtags of the last day, shared by every viewer.

The ranking does not depend on who asks, so it is computed once and kept in the
cache until the entry expires. Expiry is the only way it is refreshed.
"""

from datetime import UTC, datetime, timedelta

from posts_api.app.models.trending import TrendingTopic
from posts_api.app.repositories.trending import TrendingRepository
from posts_api.app.repositories.trending_cache import TrendingCache

CACHE_TTL_SECONDS = 900
LIMIT = 10
WINDOW = timedelta(hours=24)


class TrendingService:
    def __init__(self, cache: TrendingCache, repository: TrendingRepository) -> None:
        self._cache = cache
        self._repository = repository

    async def ranking(self) -> list[TrendingTopic]:
        cached = await self._cache.get()
        if cached is not None:
            return cached
        topics = await self._repository.top(since=datetime.now(UTC) - WINDOW, limit=LIMIT)
        await self._cache.set(topics, CACHE_TTL_SECONDS)
        return topics
