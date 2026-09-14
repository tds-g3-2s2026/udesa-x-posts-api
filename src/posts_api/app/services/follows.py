"""The rules of following someone.

This is where E3-H1 lives. There is no FastAPI and no SQLAlchemy here on
purpose: the service receives a repository and raises `ProblemError`, so the
rules can be read, tested and defended without starting the application.
"""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.rate_limiter import RateLimiter

# Its own prefix so the counter cannot collide with another one on the same Redis.
RATE_LIMIT_KEY = "follow:rate:{user_id}"


class FollowService:
    def __init__(
        self,
        repository: FollowRepository,
        rate_limiter: RateLimiter,
        *,
        follow_limit: int,
        window_seconds: int,
    ) -> None:
        self._repository = repository
        self._rate_limiter = rate_limiter
        self._follow_limit = follow_limit
        self._window_seconds = window_seconds

    async def follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        """Establish the relationship, or leave it as it already was.

        Following twice is not an error: the second call finds the relationship
        and returns. The client retrying a request it never saw answered gets
        the same result as the first time.
        """
        if follower_id == followee_id:
            raise ProblemError(
                status=409,
                code="cannot-follow-yourself",
                title="No se pudo seguir la cuenta",
                detail="No podés seguirte a vos mismo",
            )

        await self._charge_the_rate_limit(follower_id)

        await self._repository.ensure_profile(follower_id)
        target = await self._repository.find_profile(followee_id)
        if target is None:
            raise ProblemError(
                status=404,
                code="user-not-found",
                title="No se pudo seguir la cuenta",
                detail="La cuenta que querés seguir no existe",
            )

        if target.needs_approval:
            # A protected account turns the follow into a request that its
            # owner approves. That circuit is the next piece of E3-H1, and
            # until it lands the endpoint says so instead of following anyway.
            raise ProblemError(
                status=409,
                code="follow-needs-approval",
                title="No se pudo seguir la cuenta",
                detail="La cuenta es protegida y todavía no se pueden enviar solicitudes",
            )

        if await self._repository.is_following(follower_id, followee_id):
            return

        # Both in the same session, so the same transaction carries the
        # relationship and the counters: either the two land or neither does.
        await self._repository.add_follow(follower_id, followee_id)
        await self._repository.move_counters(follower_id, followee_id, by=1)

    async def unfollow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        """Undo the relationship. Not following the account is already the result."""
        removed = await self._repository.remove_follow(follower_id, followee_id)
        if removed:
            await self._repository.move_counters(follower_id, followee_id, by=-1)

    async def _charge_the_rate_limit(self, follower_id: uuid.UUID) -> None:
        """Count the attempt, and refuse it if the window is already full.

        The charge happens before the database is touched: a limit that only
        applies after the expensive work has run does not protect anything.
        """
        key = RATE_LIMIT_KEY.format(user_id=follower_id)
        attempts = await self._rate_limiter.hit(key, window_seconds=self._window_seconds)
        if attempts <= self._follow_limit:
            return

        seconds_left = await self._rate_limiter.seconds_left(key)
        raise ProblemError(
            status=429,
            code="too-many-follows",
            title="Demasiadas solicitudes de seguimiento",
            detail=f"Alcanzaste el límite de {self._follow_limit} por hora. Probá más tarde.",
            headers={"Retry-After": str(seconds_left)},
        )
