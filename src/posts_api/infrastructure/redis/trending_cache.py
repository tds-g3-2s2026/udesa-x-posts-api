"""The trending ranking in Redis, as one JSON document under one key.

The expiry is Redis's own, so an entry disappears without any job running.
"""

import json
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

from posts_api.app.models.trending import TrendingTopic
from posts_api.app.repositories.trending_cache import TrendingCache

KEY = "trending:topics"


@dataclass
class RedisTrendingCache(TrendingCache):
    redis: Redis

    async def get(self) -> list[TrendingTopic] | None:
        raw = await self.redis.get(KEY)
        if raw is None:
            return None
        return [TrendingTopic(**item) for item in json.loads(raw)]

    async def set(self, topics: list[TrendingTopic], ttl_seconds: int) -> None:
        payload = json.dumps([asdict(topic) for topic in topics])
        await self.redis.set(KEY, payload, ex=ttl_seconds)
