"""Keeping the trending ranking for a while, without naming where it is kept."""

from abc import ABC, abstractmethod

from posts_api.app.models.trending import TrendingTopic


class TrendingCache(ABC):
    """The ranking is stored whole: one entry, read and written as a unit."""

    @abstractmethod
    async def get(self) -> list[TrendingTopic] | None:
        """The stored ranking, or None when there is no entry or it expired."""

    @abstractmethod
    async def set(self, topics: list[TrendingTopic], ttl_seconds: int) -> None:
        """Store the ranking, replacing any previous one, for `ttl_seconds`."""
