"""The rules of following someone.

This is where E3-H1 lives. There is no FastAPI and no SQLAlchemy here on
purpose: the service receives a repository and raises `ProblemError`, so the
rules can be read, tested and defended without starting the application.
"""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.repositories.follows import FollowRepository


class FollowService:
    def __init__(self, repository: FollowRepository) -> None:
        self._repository = repository

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

        await self._repository.add_follow(follower_id, followee_id)

    async def unfollow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        """Undo the relationship. Not following the account is already the result."""
        await self._repository.remove_follow(follower_id, followee_id)
