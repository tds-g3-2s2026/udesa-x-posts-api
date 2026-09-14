"""The counter of the rate limit, on Redis.

Redis fits because the key has to disappear by itself: nobody runs a job to
free the accounts that reached the limit, the window simply expires.
"""

from dataclasses import dataclass

from redis.asyncio import Redis

from posts_api.app.repositories.rate_limiter import RateLimiter


@dataclass
class RedisRateLimiter(RateLimiter):
    redis: Redis

    async def hit(self, key: str, *, window_seconds: int) -> int:
        marks = await self.redis.incr(key)
        # The expiry is set only on the first mark. Setting it on every one
        # would push the window forward with each attempt and leave somebody
        # who keeps retrying blocked forever.
        if marks == 1:
            await self.redis.expire(key, window_seconds)
        return marks

    async def seconds_left(self, key: str) -> int:
        remaining = await self.redis.ttl(key)
        # Redis answers -2 when the key is gone and -1 when it never expires.
        return remaining if remaining > 0 else 0
