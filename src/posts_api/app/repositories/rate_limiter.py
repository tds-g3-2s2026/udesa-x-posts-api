"""Counting actions over a window, without naming where the count is kept."""

from abc import ABC, abstractmethod


class RateLimiter(ABC):
    """Counter that forgets on its own.

    The window opens with the first mark and the marks that follow do not push
    it forward, so whoever reaches the limit gets out after the configured time
    instead of staying blocked while they keep trying.
    """

    @abstractmethod
    async def hit(self, key: str, *, window_seconds: int) -> int:
        """Count one mark and return how many there are in the open window."""

    @abstractmethod
    async def seconds_left(self, key: str) -> int:
        """How long until the window closes. Zero if there is none open."""
